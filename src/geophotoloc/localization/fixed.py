"""Component-balanced search and post-search visibility review. No image paths."""
from collections import defaultdict
from itertools import combinations
from time import perf_counter,process_time
import numpy as np
from shapely import intersects_xy,get_coordinates
from shapely.geometry import Point,box,shape,mapping
from shapely.ops import unary_union
from geophotoloc.maps.matching import same_physical_entity
from geophotoloc.models.maps import GeoBounds
from geophotoloc.models.pose import PoseHypothesis,CandidateRegion,PoseLocalizationResult,PoseConstraintScore,FeasibleRegion
from .projection import to_local_geometry
from .search import SearchContext
from .regions import cell_region,components,geographic_mapping
from .extent import distance_feasible_domain,within_observation_distance
from .sampling import allocate_budget,plan_samples,spatial_order,feasible_medoid
from .scoring import evaluate_pose
from .partial import evaluate_partial_pose
from .visibility import cached_visibility
from .hypotheses import generate_identity_hypotheses,assignment_valid,independent_ids
from .robust_scoring import evaluate_robust_pose
from .region_selection import preferred_entries,sampled_cell_geometry,physical_union_area,tiled_union_area


def diversified_regions(polygons,scores,limit):
    """Keep local modes, then spatially separated modes, never area-only top one."""
    if len(polygons)<=limit:return polygons
    centers=[(p.representative_point().x,p.representative_point().y) for p in polygons]
    points=list(scores);xy=np.array(points)
    quality=[max((scores[p].score for p,inside in zip(points,intersects_xy(poly,xy[:,0],xy[:,1])) if inside),default=0) for poly in polygons]
    seed=centers[min(range(len(polygons)),key=lambda i:(-quality[i],centers[i]))]
    order=spatial_order(centers,limit,seed=seed)
    return [polygons[centers.index(p)] for p in order]


def solve_fixed(store,config,vision,matching):
    start=perf_counter();cpu_start=process_time()
    if not store.coverage_regions():raise ValueError('Map database is empty; import map coverage first')
    observations={o.id:o for o in vision.landmarks}
    lookup={(m.image_landmark_id,c.entity.id):c for m in matching.matches for c in m.candidates}
    original_hypotheses=matching.region_hypotheses
    identity_records=[];identity_diagnostics={}
    if config.joint_identity:
        generated,identity_records,identity_diagnostics=generate_identity_hypotheses(vision,matching,config)
        hypotheses=generated[:config.max_joint_hypotheses]
    else:
        hypotheses=original_hypotheses[:config.max_hypotheses]
    selected_sets=[]
    for h in hypotheses:
        selected=[]
        for image_id,entity_id in sorted(h.assignments.items()):
            c=lookup.get((image_id,entity_id))
            if c is None or image_id not in observations:raise ValueError('Unknown vision/map candidate')
            if h.region_id not in c.entity.region_ids:raise ValueError('Cross-region assignment rejected')
            selected.append((image_id,c))
        selected_sets.append(selected)
    if config.robust_geometry or config.joint_identity:
        eligible=[sum(observations[k].coordinates_reliable for k in independent_ids({k:c.entity for k,c in s},config))>=2 and assignment_valid(s,config) for s in selected_sets]
    else:
        eligible=[len(s)>=2 and sum(observations[k].coordinates_reliable for k,_ in s)>=2
                  and not any(same_physical_entity(a[1],b[1]) for a,b in combinations(s,2)) for s in selected_sets]
    active=[i for i,x in enumerate(eligible) if x]
    shares=allocate_budget([1]*len(active),config.max_total_points,config.max_points_per_hypothesis)
    budgets=dict(zip(active,shares))
    contexts={};reports=[];regions=[];used={};work={};feasible_regions=[];feasible_local=defaultdict(list);feasible_unmasked=defaultdict(list)
    limited=(identity_diagnostics.get('beam_pruned',0)>0 or identity_diagnostics.get('final_pruned',0)>0) if config.joint_identity else len(original_hypotheses)>len(hypotheses)
    timings=defaultdict(float)
    for index,(h,selected) in enumerate(zip(hypotheses,selected_sets)):
        begin=perf_counter();hid=f'hyp_{index+1}'
        report=PoseHypothesis(id=hid,region_id=h.region_id,assignments=h.assignments,budget=budgets.get(index,0))
        reports.append(report)
        entities={k:c.entity for k,c in selected};used.update({e.id:e.model_dump(mode='json') for e in entities.values()})
        report.unknown_image_ids=sorted(set(observations)-set(entities))
        if not eligible[index]:
            report.reasons=['fewer_than_two_reliable_landmarks; no precise pose generated' if len(selected)<2 or sum(observations[k].coordinates_reliable for k,_ in selected)<2 else 'duplicate_physical_entity_assignment_rejected'];continue
        if not report.budget:
            report.limited=limited=True;report.reasons=['identity_budget_unavailable'];continue
        if h.region_id not in contexts:
            row=store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(h.region_id,)).fetchone()
            if row is None:raise ValueError('Missing map coverage bounds')
            contexts[h.region_id]=SearchContext(store,h.region_id,GeoBounds.model_validate_json(row[0]))
        ctx=contexts[h.region_id];before_queries=ctx.strtree_queries
        ctx.enable_union_cache=config.audit_hard_feasibility or config.robust_geometry or config.joint_identity or config.dual_regions
        reliable_count=sum(observations[k].coordinates_reliable for k in independent_ids(entities,config))
        xy={k:ctx.system.to_local(e.location) for k,e in entities.items()}
        geometries={k:ctx.project_entity(e) for k,e in entities.items()}
        distances={k:g if e.complete_geometry and e.geometry_precision=='complete_outline' and (g:=geometries[k]) is not None and g.is_valid and g.geom_type in {'Polygon','MultiPolygon'} else Point(xy[k]) for k,e in entities.items()}
        outlines={}
        for k,g in distances.items():
            vertices=get_coordinates(g)
            if g.geom_type in {'Polygon','MultiPolygon'}:
                outlines[k]=[tuple(v) for v in vertices[::max(1,len(vertices)//32)]]
        if config.adaptive_extent:
            search=distance_feasible_domain(list(distances.values()),config.max_observation_distance_m)
        else:
            positions=list(xy.values());r=config.search_radius_m
            search=box(min(p[0] for p in positions)-r,min(p[1] for p in positions)-r,max(p[0] for p in positions)+r,max(p[1] for p in positions)+r).intersection(ctx.coverage)
        if config.search_bounds:
            b=config.search_bounds;search=search.intersection(to_local_geometry(box(b.west,b.south,b.east,b.north),ctx.system))
        if search.is_empty or search.area<=0:
            report.reasons=['empty_distance_feasible_domain'];continue
        report.search_geometry=geographic_mapping(search,ctx);report.search_area_m2=search.area;report.map_coverage_status=ctx.coverage_status(search)
        coarse_quota=max(1,int(report.budget*config.coarse_budget_fraction))
        fine_quota=int(report.budget*config.fine_budget_fraction) if config.refinement_levels else 0
        supplemental_quota=report.budget-coarse_quota-fine_quota
        plan=plan_samples(search,coarse_quota,config.minimum_coarse_spacing_m,config.maximum_coarse_spacing_m)
        report.coarse_spacing_m=plan.spacing
        report.budget_allocation=dict(coarse=coarse_quota,fine=fine_quota,supplemental=supplemental_quota,transfers=[])
        report.component_sampling=[dict(id=i,area_m2=p.area,coarse_points=0,fine_points=0,supplemental_points=0,allocated=plan.quotas[i]) for i,p in enumerate(plan.components)]
        scores={};seen=set();coarse=[];fine=[];trace=[];visited=[];hard_coarse=[];hard_fine=[]
        def assess(points,ids,phase):
            for p,cid in zip(points,ids):
                if p in seen:continue
                if report.searched_points>=report.budget:
                    report.limited=True;break
                seen.add(p);visited.append((p,config.fine_spacing_m if phase=='fine' else plan.spacing))
                report.searched_points+=1
                if phase=='fine':report.fine_points+=1
                else:report.coarse_points+=1
                report.component_sampling[cid][phase+'_points']+=1
                if not within_observation_distance([p],list(distances.values()),config.max_observation_distance_m)[0]:
                    report.distance_filtered_points+=1
                    trace.append(dict(x=round(p[0],6),y=round(p[1],6),feasible=False,reasons=['outside_exact_distance_domain']))
                    if config.record_diagnostic_trace:trace[-1].update(hard_feasible=False,phase=phase,selection_stage='hard_rejected')
                    continue
                filters=ctx.filter_reasons(p,list(distances.values()),allow_uncovered=config.adaptive_extent)
                hard_pass=not filters and all(g.distance(Point(p))>config.minimum_distance_m for g in distances.values())
                if hard_pass:
                    (hard_fine if phase=='fine' else hard_coarse).append(p)
                elif not filters and config.robust_geometry:
                    filters=['target_coincident_or_too_close']
                if filters:
                    score=PoseConstraintScore(feasible=False,score=0,reasons=['known_standing_surface_conflict'],filter_reasons=filters)
                    report.filtered_points+=1
                elif config.robust_geometry:
                    score=evaluate_robust_pose(p,observations,entities,xy,geometries,[c.score for _,c in selected],vision.relations,config,ctx,detailed=False)
                elif config.footprint_constraints:
                    score=evaluate_partial_pose(p,observations,entities,xy,geometries,[c.score for _,c in selected],vision.relations,config,ctx)
                else:
                    score=evaluate_pose(p,observations,entities,xy,outlines,[c.score for _,c in selected],vision.relations,config)
                    score.stage1_score=score.score
                report.confirmed_order_conflicts+=score.conflicts
                if not config.robust_geometry:
                    score.reliable_landmark_count=reliable_count
                    score.unknown_image_ids=report.unknown_image_ids
                trace.append(dict(x=round(p[0],6),y=round(p[1],6),feasible=score.feasible,score=score.score,reasons=score.reasons if not score.feasible else [],
                    outliers=score.outlier_image_ids,reliable_landmarks=score.reliable_landmark_count))
                if config.record_diagnostic_trace:
                    trace[-1].update(hard_feasible=hard_pass,phase=phase,components=dict(score.components),
                        filters=list(filters),unknowns=list(report.unknown_image_ids),fov=score.fov_degrees,heading=score.heading,
                        selection_stage='awaiting_selection' if score.feasible else 'hard_rejected' if not hard_pass else 'visual_rejected')
                if score.feasible:
                    score.map_coverage_status=ctx.coverage_status(Point(p));scores[p]=score
                    (fine if phase=='fine' else coarse).append(p)
                elif len(report.filtered_examples)<8:
                    report.filtered_examples.append(dict(location=ctx.system.to_geographic(p).model_dump(),raw_constraint_score=score.model_dump(),reasons=score.reasons))
        planned_work=len(plan.points)
        report.timings['preparation_seconds']=perf_counter()-begin
        phase_start=perf_counter();assess(plan.points,plan.component_ids,'coarse')
        report.timings['coarse_seconds']=perf_counter()-phase_start
        # Every feasible connected mode supplies its own cutoff, not one global cutoff.
        phase_start=perf_counter()
        initial=cell_region(coarse,plan.spacing,search,ctx) if coarse else []
        refine=diversified_regions(initial,scores,config.max_refine_components)
        if len(initial)>len(refine):report.limited=True;report.reasons.append('refinement_component_limit; coarse modes retained')
        fine_used=0
        if refine and fine_quota:
            quotas=allocate_budget([p.area for p in refine],fine_quota)
            for polygon,quota in zip(refine,quotas):
                fp=plan_samples(polygon.buffer(plan.spacing/2).intersection(search),quota,config.fine_spacing_m,config.fine_spacing_m,exclude=seen)
                planned_work+=len(fp.points)
                ids=[next((i for i,c in enumerate(plan.components) if c.covers(Point(p))),0) for p in fp.points]
                old=report.searched_points;assess(fp.points,ids,'fine');fine_used+=report.searched_points-old
        report.timings['fine_seconds']=perf_counter()-phase_start
        # Transfer genuinely unused phase allocations; supplement all domain components.
        remaining=report.budget-report.searched_points
        if remaining:
            report.budget_allocation['transfers'].append(dict(to='supplemental',unused_fine=max(0,fine_quota-fine_used),available=remaining))
            phase_start=perf_counter()
            supplement=plan_samples(search,remaining,plan.spacing,plan.spacing,exclude=seen,supplemental=True)
            planned_work+=len(supplement.points)
            assess(supplement.points,supplement.component_ids,'supplemental')
            report.timings['supplemental_seconds']=perf_counter()-phase_start
        report.feasible_points=len(scores);report.sample_trace=trace
        report.sampling_completion_ratio=report.searched_points/max(1,planned_work)
        report.budget_allocation.update(planned_work=planned_work,used_budget_ratio=report.searched_points/report.budget)
        accounting_start=perf_counter()
        visited_area=unary_union([box(p[0]-step/2,p[1]-step/2,p[0]+step/2,p[1]+step/2) for p,step in visited]).intersection(search)
        report.sampled_geometry=geographic_mapping(visited_area,ctx)
        report.unsearched_area_m2=max(0,search.area-visited_area.area)
        report.timings['coverage_accounting_seconds']=perf_counter()-accounting_start
        if plan.limited or report.unsearched_area_m2>1 or report.searched_points>=report.budget:
            report.limited=True;report.reasons.append('finite_sampling_budget_not_exhaustive_continuous_search')
        phase_start=perf_counter()
        modern_regions=config.audit_hard_feasibility or config.robust_geometry or config.joint_identity or config.dual_regions
        scored_raw=None
        if modern_regions:
            scored_raw=sampled_cell_geometry(coarse,fine,plan.spacing,config.fine_spacing_m,search)
            scored_geometry=scored_raw.difference(ctx.obstacle_union(scored_raw))
        else:
            all_polygons=cell_region(coarse,plan.spacing,search,ctx)+cell_region(fine,config.fine_spacing_m,search,ctx)
            scored_geometry=unary_union(all_polygons)
        connected=components(scored_geometry)
        hard_geometry=None
        if config.audit_hard_feasibility or config.dual_regions:
            hard_raw=scored_raw if config.robust_geometry else sampled_cell_geometry(hard_coarse,hard_fine,plan.spacing,config.fine_spacing_m,search)
            exclusions=unary_union([g.buffer(config.minimum_distance_m) for g in distances.values()])
            hard_raw=hard_raw.difference(exclusions)
            hard_geometry=hard_raw.difference(ctx.obstacle_union(hard_raw))
            feasible_unmasked[h.region_id].append(hard_raw)
            if not hard_geometry.is_empty:
                feasible_regions.append(FeasibleRegion(id=f'{hid}_feasible',hypothesis_id=hid,region_id=h.region_id,
                    geometry=geographic_mapping(hard_geometry,ctx),area_m2=hard_geometry.area,candidate_point_count=len(hard_coarse)+len(hard_fine),
                    component_count=len(components(hard_geometry)),assignments=h.assignments,map_coverage_status=ctx.coverage_status(hard_geometry)))
                feasible_local[h.region_id].append(hard_geometry)
        xy_points=list(scores);array=np.array(xy_points).reshape(-1,2)
        region_entries=[]
        for polygon in ([] if config.dual_regions else connected):
            mask=intersects_xy(polygon,array[:,0],array[:,1])
            members=[p for p,keep in zip(xy_points,mask) if keep]
            if not members:continue
            local_max=max(scores[p].score for p in members)
            support=[p for p in members if scores[p].score>=local_max-config.score_window]
            # Apply each component's own window, then retain disconnected
            # local modes separately; a broad bridge cannot merge them back.
            fine_set=set(fine)
            support_geometry=unary_union([box(p[0]-(config.fine_spacing_m if p in fine_set else plan.spacing)/2,
                p[1]-(config.fine_spacing_m if p in fine_set else plan.spacing)/2,
                p[0]+(config.fine_spacing_m if p in fine_set else plan.spacing)/2,
                p[1]+(config.fine_spacing_m if p in fine_set else plan.spacing)/2) for p in support]).intersection(polygon)
            support_xy=np.array(support)
            for mode in components(support_geometry):
                members=[p for p,inside in zip(support,intersects_xy(mode,support_xy[:,0],support_xy[:,1])) if inside]
                if members:region_entries.append((mode,members))
        if config.dual_regions and scores:
            region_entries=preferred_entries(scores,fine,plan.spacing,config.fine_spacing_m,hard_geometry,config.score_window,config.preferred_tile_size_m)
        original_entries=region_entries
        if config.selection_strategy=='quality_v2':
            from .selection_v2 import select_quality_modes
            region_entries,report.selection_audit=select_quality_modes(region_entries,scores,config.max_regions_per_hypothesis,config.preferred_tile_size_m**2)
            keep=[p for p,_ in region_entries]
        else:
            keep=diversified_regions([p for p,_ in region_entries],scores,config.max_regions_per_hypothesis)
        if config.record_diagnostic_trace:
            from .diagnostics import annotate_selection
            annotate_selection(trace,scores,original_entries,keep,config,connected,
                retained_members={p for _,members in region_entries for p in members} if config.selection_strategy=='quality_v2' else None)
        if config.selection_strategy=='quality_v2':
            if any(not d['retained'] and d['reason']!='covered_by_retained_mode' for d in report.selection_audit['decisions']):
                report.limited=True;report.reasons.append('quality_output_budget; omitted modes explicitly audited')
        elif len(keep)<len(region_entries):report.limited=True;report.reasons.append('diverse_output_region_limit')
        for polygon,members in region_entries:
            if not any(polygon is p for p in keep):continue
            best=min(members,key=lambda p:(-scores[p].score,p));medoid=feasible_medoid(members)
            if config.robust_geometry:
                for point in {best,medoid}:
                    detailed=evaluate_robust_pose(point,observations,entities,xy,geometries,[c.score for _,c in selected],vision.relations,config,ctx)
                    if detailed.score!=scores[point].score:raise RuntimeError('Detailed score disagrees with fast score')
                    detailed.map_coverage_status=scores[point].map_coverage_status
                    scores[point]=detailed
            geographic=geographic_mapping(polygon,ctx)
            region=CandidateRegion(id=f'{hid}_area_{len(regions)+1}',hypothesis_id=hid,region_id=h.region_id,
                geometry=geographic,best_location=ctx.system.to_geographic(best),best_scored_point=ctx.system.to_geographic(best),region_medoid=ctx.system.to_geographic(medoid),
                best_score=scores[best],area_m2=polygon.area,bounds_wgs84=shape(geographic).bounds,candidate_point_count=len(members),assignments=h.assignments,heading=scores[best].heading,
                refined=any(p in fine for p in members),touches_search_boundary=polygon.distance(search.boundary)<config.fine_spacing_m,
                uncertainty=['sampled_cells_not_statistical_confidence','partial_horizontal_visibility_not_3D','best_point_and_medoid_are_candidates_not_verified_locations','uncalibrated_intrinsics_and_identity'],map_coverage_status=ctx.coverage_status(polygon))
            regions.append(region)
            work[region.id]=dict(context=ctx,entities=entities,geometries=geometries,scores=scores,members=members,best=best,medoid=medoid,report=report,geometry=polygon)
        report.timings['regions_seconds']=perf_counter()-phase_start
        report.elapsed_seconds=perf_counter()-begin;report.strtree_queries=ctx.strtree_queries-before_queries
        limited|=report.limited
        for k,v in report.timings.items():timings[k]+=v
    # All coarse/fine searches above are ray-free. Review a bounded, fair pool.
    phase_start=perf_counter();reviewed=[]
    by_hyp=defaultdict(list)
    for region in regions:by_hyp[region.hypothesis_id].append(region)
    review_shares=allocate_budget([1]*len(by_hyp),config.max_visibility_points_total,config.max_visibility_points_per_hypothesis) if config.visibility_soft else [0]*len(by_hyp)
    for (hid,hregions),quota in zip(by_hyp.items(),review_shares):
        chosen=[];seen_review=set()
        for mode in ('best','medoid'):
            for region in hregions:
                w=work[region.id];p=w[mode]
                if p not in seen_review and len(chosen)<quota:
                    chosen.append((region,p));seen_review.add(p)
        for region,p in chosen:
            w=work[region.id];ctx=w['context'];score=w['scores'][p]
            before=ctx.strtree_queries;begin=perf_counter()
            for key,entity in w['entities'].items():
                g=w['geometries'][key]
                complete=entity.complete_geometry and entity.geometry_precision=='complete_outline'
                visibility=cached_visibility(p,g if complete else None,ctx,target_entity=entity,max_rays=config.visibility_max_rays,cache_size=config.visibility_cache_size)
                score.visibility_evidence.append(dict(image_landmark_id=key,**visibility.to_dict()))
            quality=sum(v['quality'] for v in score.visibility_evidence)/len(score.visibility_evidence)
            score.stage1_score=score.stage1_score if score.stage1_score is not None else score.score
            score.score=round(score.stage1_score+(0 if config.robust_geometry else .05*(quality-.5)),8);score.stage2_score=score.score;score.visibility_reviewed=True
            score.components['visibility_quality']=quality
            score.components['visibility_evidence_coverage']=sum(v['complete_ray_fraction'] for v in score.visibility_evidence)/len(score.visibility_evidence)
            report=w['report'];report.visibility_review_points+=1;report.strtree_queries+=ctx.strtree_queries-before
            report.timings['visibility_seconds']=report.timings.get('visibility_seconds',0)+perf_counter()-begin
            reviewed.append(dict(hypothesis_id=hid,location=ctx.system.to_geographic(p).model_dump(),score=score.model_dump(mode='json')))
        if config.visibility_soft and len(seen_review)<len({work[r.id]['best'] for r in hregions}):
            limited=True
            report=work[hregions[0].id]['report'];report.limited=True
            report.reasons.append('visibility_review_budget; unreviewed_candidates_remain_UNKNOWN')
    for region in regions:
        w=work[region.id];best=min(w['members'],key=lambda p:(-w['scores'][p].score,p))
        region.best_score=w['scores'][best];region.best_location=w['context'].system.to_geographic(best);region.best_scored_point=region.best_location;region.heading=region.best_score.heading
    timings['visibility_seconds']=perf_counter()-phase_start
    if config.selection_strategy=='quality_v2':
        from .selection_v2 import evidence_quality
        regions.sort(key=lambda r:(tuple(-v for v in evidence_quality(r.best_score)),r.hypothesis_id,r.best_location.latitude,r.best_location.longitude))
    else:
        regions.sort(key=lambda r:(-r.best_score.score,r.hypothesis_id,r.best_location.latitude,r.best_location.longitude))
    status='INSUFFICIENT_EVIDENCE' if not active else 'SEARCH_LIMITED' if limited else 'INSUFFICIENT_EVIDENCE' if not config.robust_geometry and regions and all(r.best_score.satisfied==0 for r in regions) else 'AMBIGUOUS' if regions else 'NO_FEASIBLE_POSE'
    features=[]
    for r in regions:
        props=dict(id=r.id,hypothesis_id=r.hypothesis_id,score=r.best_score.score,assignments=r.assignments,area_m2=r.area_m2,heading=r.heading,uncertainty=r.uncertainty,
                   satisfied=r.best_score.satisfied,conflicts=r.best_score.conflicts,indeterminate=r.best_score.indeterminate,candidate_point_count=r.candidate_point_count,
                   stage1_score=r.best_score.stage1_score,stage2_score=r.best_score.stage2_score,visibility_reviewed=r.best_score.visibility_reviewed)
        if config.dual_regions:props.update(layer_type='preferred_region',priority='PREFERRED_HEURISTIC',explanation='Ranked proposal, not a calibrated probability')
        features.append(dict(type='Feature',geometry=r.geometry,properties={**props,'kind':'candidate_region'}))
        features.append(dict(type='Feature',geometry=dict(type='Point',coordinates=[r.best_location.longitude,r.best_location.latitude]),properties={**props,'kind':'searched_representative_pose'}))
        features.append(dict(type='Feature',geometry=dict(type='Point',coordinates=[r.region_medoid.longitude,r.region_medoid.latitude]),properties={**props,'kind':'region_medoid'}))
    for r in feasible_regions:
        features.append(dict(type='Feature',geometry=r.geometry,properties=dict(id=r.id,hypothesis_id=r.hypothesis_id,kind='feasible_region',layer_type='feasible_region',priority=r.priority,explanation=r.explanation,area_m2=r.area_m2,map_coverage_status=r.map_coverage_status)))
    preferred_local=defaultdict(list)
    for r in regions:preferred_local[r.region_id].append(work[r.id]['geometry'])
    feasible_area=sum(physical_union_area(geoms,contexts[region_id]) for region_id,geoms in feasible_unmasked.items())
    preferred_area=sum(tiled_union_area(geoms,config.preferred_tile_size_m) if config.dual_regions and config.selection_strategy=='legacy' else unary_union(geoms).area for geoms in preferred_local.values())
    return PoseLocalizationResult(status=status,regions=regions,hypotheses=reports,config=config,matched_landmarks=list(used.values()),elapsed_seconds=perf_counter()-start,
        geojson=dict(type='FeatureCollection',features=features),reviewed_candidates=reviewed,
        feasible_regions=feasible_regions,preferred_regions=regions,feasible_area_m2=feasible_area,preferred_area_m2=preferred_area,
        identity_hypotheses=identity_records,identifiability='AMBIGUOUS' if active else 'INSUFFICIENT_EVIDENCE',
        warnings=['Heuristic scores are not probabilities','Sample completion is budgeted work, not exhaustive continuous coverage','Missing map data is not clear visibility or safe standing','Camera intrinsics and building heights are unknown'],
        diagnostics=dict(process_cpu_seconds=process_time()-cpu_start,timings=dict(timings),strtree_queries=sum(c.strtree_queries for c in contexts.values()),visibility_review_points=len(reviewed),context_loads=len(contexts),
                         identity_generation=identity_diagnostics,original_region_hypotheses=[h.model_dump(mode='json') for h in original_hypotheses],
                         obstacle_union_cache_hits=sum(getattr(c,'obstacle_union_hits',0) for c in contexts.values()),
                         obstacle_union_cache_misses=sum(getattr(c,'obstacle_union_misses',0) for c in contexts.values()),
                         obstacle_union_seconds=sum(getattr(c,'obstacle_union_seconds',0) for c in contexts.values()),
                         area_semantics='union per local region, then sum disjoint city regions; hypothesis sums are not unique area',
                         visibility_cache_hits=sum(getattr(c,'visibility_cache_hits',0) for c in contexts.values()),
                         visibility_cache_misses=sum(getattr(c,'visibility_cache_misses',0) for c in contexts.values()),
                         assigned_budget=sum(shares),unused_global_budget=config.max_total_points-sum(r.searched_points for r in reports)))
