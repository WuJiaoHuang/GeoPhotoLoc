"""Coarse-to-fine region search with bounded, separately evaluated identities."""
from time import perf_counter
from itertools import combinations
from shapely.geometry import Point, box, shape, mapping
from shapely import get_coordinates
from geophotoloc.maps.matching import same_physical_entity
from geophotoloc.models.maps import GeoBounds
from geophotoloc.models.pose import PoseSearchConfig, PoseHypothesis, CandidateRegion, PoseLocalizationResult, PoseConstraintScore
from .projection import to_local_geometry
from .scoring import evaluate_pose
from .search import SearchContext, grid
from .regions import cell_region, geographic_mapping
from .extent import adaptive_search_extent, distance_batches
from .enhanced import evaluate_enhanced_pose
from .sampling import feasible_medoid


class PoseSolver:
    def __init__(self, store, config=None):
        self.store,self.config = store,config or PoseSearchConfig()

    def solve(self, vision_result, map_matching_result):
        if self.config.viewpoint_fix and (self.config.adaptive_extent or self.config.footprint_constraints or self.config.visibility_soft or self.config.robust_geometry or self.config.joint_identity or self.config.dual_regions):
            from .fixed import solve_fixed
            return solve_fixed(self.store,self.config,vision_result,map_matching_result)
        started = perf_counter()
        config = self.config
        coverage = self.store.coverage_regions()
        if not coverage:
            raise ValueError("Map database is empty; import map coverage first")
        observations = {item.id:item for item in vision_result.landmarks}
        candidate_lookup = {(match.image_landmark_id,candidate.entity.id):candidate
                            for match in map_matching_result.matches for candidate in match.candidates}
        warnings = ["Scores are heuristic, not success probabilities or 95% confidence regions",
                    "Grid spacing and projection residual do not measure geographic accuracy",
                    "FOV and principal point are assumptions; no camera calibration or ground truth was used",
                    "Regions are unions of sampled cells, not guarantees that every interior point satisfies all constraints",
                    "Map omissions and inaccessible surfaces beyond known buildings/water are not modeled"]
        contexts,regions,reports,used_entities = {},[],[],{}
        total_points = 0
        limited = len(map_matching_result.region_hypotheses) > config.max_hypotheses
        hypotheses = map_matching_result.region_hypotheses[:config.max_hypotheses]
        if limited:
            warnings.append("Identity hypothesis budget truncated additional assignments")
        for index,hypothesis in enumerate(hypotheses):
            begin = perf_counter()
            identifier = f"hyp_{index+1}"
            report = PoseHypothesis(id=identifier,region_id=hypothesis.region_id,assignments=hypothesis.assignments)
            report.budget=min(config.max_points_per_hypothesis,config.max_total_points-total_points)
            reports.append(report)
            selected = []
            for image_id,entity_id in sorted(hypothesis.assignments.items()):
                candidate = candidate_lookup.get((image_id,entity_id))
                if candidate is None or image_id not in observations:
                    raise ValueError("Pose assignment references unknown vision/map candidate")
                if hypothesis.region_id not in candidate.entity.region_ids:
                    raise ValueError("Cross-region assignment rejected")
                selected.append((image_id,candidate))
                used_entities[candidate.entity.id] = candidate.entity.model_dump(mode="json")
            if any(same_physical_entity(a[1],b[1]) for a,b in combinations(selected,2)):
                report.reasons.append("duplicate_physical_entity_assignment_rejected")
                continue
            reliable_count = sum(observations[key].coordinates_reliable for key,_ in selected)
            if len(selected)<2 or reliable_count<2:
                report.reasons.append("fewer_than_two_reliable_landmarks; no precise pose generated")
                continue
            if total_points >= config.max_total_points:
                report.limited = limited = True
                report.reasons.append("global_point_budget_exhausted")
                continue
            if hypothesis.region_id not in contexts:
                row = self.store.connection.execute("SELECT bounds_json FROM regions WHERE id=?",(hypothesis.region_id,)).fetchone()
                if row is None:
                    raise ValueError("Missing map coverage bounds")
                contexts[hypothesis.region_id] = SearchContext(self.store,hypothesis.region_id,GeoBounds.model_validate_json(row[0]))
            context = contexts[hypothesis.region_id]
            entities = {key:c.entity for key,c in selected}
            coordinates = {key:context.system.to_local(entity.location) for key,entity in entities.items()}
            target_geometries = {key:to_local_geometry(shape(entity.geometry),context.system) if entity.geometry else None
                                 for key,entity in entities.items()}
            outlines = {}
            for key,entity in entities.items():
                used_entities[entity.id] = entity.model_dump(mode="json")
                g = target_geometries[key]
                if entity.geometry_precision == "complete_outline" and g is not None:
                    vertices = get_coordinates(g)
                    outlines[key] = [tuple(value) for value in vertices[::max(1,len(vertices)//32)]]
                else:
                    report.reasons.append(f"{key}: point/partial geometry downgrade")
            xy = list(coordinates.values())
            distance_geometries = {key:(target_geometries[key] if entity.complete_geometry and
                                   entity.geometry_precision == 'complete_outline' and target_geometries[key] is not None
                                   and target_geometries[key].geom_type in {'Polygon','MultiPolygon'} else Point(coordinates[key]))
                                   for key,entity in entities.items()}
            radius = config.search_radius_m
            expanded = box(min(p[0] for p in xy)-radius,min(p[1] for p in xy)-radius,
                           max(p[0] for p in xy)+radius,max(p[1] for p in xy)+radius)
            if config.adaptive_extent:
                expanded = adaptive_search_extent(list(distance_geometries.values()),config.max_observation_distance_m)
                search = expanded
                report.reasons.append('adaptive_rectangle_then_exact_all_target_distance_filter; map_bbox_not_camera_boundary')
            else:
                search = expanded.intersection(context.coverage)
            if config.search_bounds is not None:
                b = config.search_bounds
                search = search.intersection(to_local_geometry(box(b.west,b.south,b.east,b.north),context.system))
                report.reasons.append("explicit_configured_search_bounds_applied")
            if search.is_empty:
                report.reasons.append("empty_search_coverage_intersection")
                continue
            coverage_clipped = not config.adaptive_extent and not context.coverage.covers(expanded)
            report.search_geometry = geographic_mapping(search,context)
            report.search_area_m2 = search.area
            report.map_coverage_status = context.coverage_status(search)
            if coverage_clipped:
                report.reasons.append("search_extent_clipped_by_map_coverage")
            scores,coarse,fine,seen = {},[],[],set()
            coarse_support = set()
            visited=[]

            def assess(points, destination, coarse_level):
                nonlocal total_points,limited
                batches = distance_batches(points,list(distance_geometries.values()),config.max_observation_distance_m) if config.adaptive_extent else ((p,True) for p in points)
                for p,within_distance in batches:
                    if p in seen:
                        continue
                    if report.searched_points >= config.max_points_per_hypothesis or total_points >= config.max_total_points:
                        report.limited = limited = True
                        report.reasons.append("point_budget_exhausted; unsearched cells not classified infeasible")
                        break
                    seen.add(p)
                    if config.record_sample_trace:
                        visited.append((p,config.coarse_spacing_m if coarse_level else config.fine_spacing_m))
                    report.searched_points += 1
                    total_points += 1
                    if coarse_level:
                        report.coarse_points += 1
                    else:
                        report.fine_points += 1
                    if not within_distance:
                        report.distance_filtered_points += 1
                        if config.record_sample_trace:
                            report.sample_trace.append(dict(x=p[0],y=p[1],feasible=False,reasons=['outside_exact_distance_domain']))
                        continue
                    filters = context.filter_reasons(p,list(target_geometries.values()),allow_uncovered=config.adaptive_extent)
                    if config.footprint_constraints or config.visibility_soft:
                        score = evaluate_enhanced_pose(p,observations,entities,coordinates,outlines,
                            [candidate.score for _,candidate in selected],vision_result.relations,config,context,
                            target_geometries,standing_filters=filters)
                    elif config.adaptive_extent and any(g.distance(Point(p)) <= config.minimum_distance_m for g in distance_geometries.values()):
                        score = PoseConstraintScore(feasible=False,score=0,reasons=['observer_coincident_or_too_close_to_geometry'])
                    else:
                        score = evaluate_pose(p,observations,entities,coordinates,outlines,
                                              [candidate.score for _,candidate in selected],vision_result.relations,config)
                    score.map_coverage_status = context.coverage_status(Point(p))
                    report.confirmed_order_conflicts += score.conflicts
                    report.potentially_occluded_targets += sum(v['blocked_rays']>0 for v in score.visibility_evidence)
                    score.filter_reasons = filters
                    if config.record_sample_trace:
                        report.sample_trace.append(dict(x=p[0],y=p[1],feasible=score.feasible and not filters,score=score.score,reasons=filters or (score.reasons if not score.feasible else [])))
                    if filters:
                        report.filtered_points += 1
                        if len(report.filtered_examples)<8:
                            report.filtered_examples.append(dict(location=context.system.to_geographic(p).model_dump(),
                                                                 raw_constraint_score=score.model_dump(),reasons=filters))
                    if score.feasible and not filters:
                        scores[p] = score
                        destination.append(p)
            phase_started=perf_counter()
            assess(grid(search,config.coarse_spacing_m),coarse,True)
            report.timings['coarse_seconds']=perf_counter()-phase_started
            phase_started=perf_counter()
            if coarse:
                cutoff = max(scores[p].score for p in coarse)-config.score_window
                coarse_support = {p for p in coarse if scores[p].score>=cutoff}
                initial = cell_region(coarse_support,config.coarse_spacing_m,search,context)
                if config.refinement_levels and len(initial)>config.max_refine_components:
                    report.limited = limited = True
                    report.reasons.append("component_refinement_budget; coarse feasible regions retained")
                if not config.refinement_levels:
                    report.reasons.append("coarse_only_search_configured; fine refinement disabled")
                for polygon in (initial[:config.max_refine_components] if config.refinement_levels else []):
                    assess(grid(polygon.buffer(config.coarse_spacing_m).intersection(search),config.fine_spacing_m),fine,False)
            report.timings['fine_seconds']=perf_counter()-phase_started
            phase_started=perf_counter()
            report.feasible_points = len(scores)
            if scores:
                cutoff = max(value.score for value in scores.values())-config.score_window
                # Retain coarse support everywhere, including unrefined components.
                coarse_polys = cell_region(coarse_support,config.coarse_spacing_m,search,context)
                fine_polys = cell_region([p for p in fine if scores[p].score>=cutoff],config.fine_spacing_m,search,context)
                from shapely.ops import unary_union
                from .regions import components
                polygons = sorted(components(unary_union(coarse_polys+fine_polys)),key=lambda p:(-p.area,p.bounds))
                if len(polygons)>config.max_regions_per_hypothesis:
                    report.limited = limited = True
                    report.reasons.append("output_region_limit; omitted components remain possible")
                for polygon in polygons[:config.max_regions_per_hypothesis]:
                    members = [p for p in scores if (p in coarse_support or scores[p].score>=cutoff) and polygon.covers(Point(p))]
                    if not members:
                        continue
                    best = min(members,key=lambda p:(-scores[p].score,p))
                    geographic = geographic_mapping(polygon,context)
                    touches = polygon.distance(search.boundary)<max(config.fine_spacing_m,1)
                    uncertainty = ["sampled_cell_region_not_statistical_confidence", "unknown_FOV_and_optical_center", "approximate_visual_centers_and_outline_angles"]
                    if len(selected)==2:
                        uncertainty.append("two_landmarks_allow_continuous_position_and_identity_ambiguity")
                    if touches or coverage_clipped:
                        uncertainty.append("finite_search_or_map_boundary_may_truncate_solutions")
                    regions.append(CandidateRegion(
                        id=f"{identifier}_area_{len(regions)+1}",hypothesis_id=identifier,region_id=hypothesis.region_id,
                        geometry=geographic,best_location=context.system.to_geographic(best),best_score=scores[best],
                        area_m2=polygon.area,bounds_wgs84=shape(geographic).bounds,candidate_point_count=len(members),
                        assignments=hypothesis.assignments,heading=scores[best].heading,refined=any(p in fine for p in members),
                        touches_search_boundary=touches,uncertainty=uncertainty,
                        best_scored_point=context.system.to_geographic(best) if config.record_sample_trace else None,
                        region_medoid=context.system.to_geographic(feasible_medoid(members)) if config.record_sample_trace else None,
                        map_coverage_status=context.coverage_status(polygon)))
            report.timings['regions_seconds']=perf_counter()-phase_started
            if config.record_sample_trace:
                from shapely.ops import unary_union
                sampled=unary_union([box(p[0]-s/2,p[1]-s/2,p[0]+s/2,p[1]+s/2) for p,s in visited]).intersection(search)
                report.sampled_geometry=geographic_mapping(sampled,context)
                report.unsearched_area_m2=max(0,search.area-sampled.area)
                report.sampling_completion_ratio=report.searched_points/max(1,report.budget)
                report.coarse_spacing_m=config.coarse_spacing_m
            report.elapsed_seconds = round(perf_counter()-begin,6)
        regions.sort(key=lambda r:(-r.best_score.score,r.hypothesis_id,r.best_location.latitude,r.best_location.longitude))
        informative = any(len(h.assignments)>=2 for h in hypotheses)
        if (not informative or (reports and all(any("fewer_than_two" in reason for reason in h.reasons) for h in reports))
                or (regions and all(r.best_score.satisfied == 0 for r in regions))):
            status = "INSUFFICIENT_EVIDENCE"
        elif limited:
            status = "SEARCH_LIMITED"
        elif not regions:
            status = "NO_FEASIBLE_POSE"
        else:
            # Even a single two-landmark connected component remains a region,
            # never a proven unique camera location.
            status = "AMBIGUOUS"
        features = []
        for region in regions:
            properties = dict(id=region.id,hypothesis_id=region.hypothesis_id,score=region.best_score.score,
                              area_m2=region.area_m2,heading=region.heading,assignments=region.assignments,
                              satisfied=region.best_score.satisfied,conflicts=region.best_score.conflicts,
                              indeterminate=region.best_score.indeterminate,candidate_point_count=region.candidate_point_count,
                              uncertainty=region.uncertainty)
            features.append(dict(type="Feature",geometry=region.geometry,properties={**properties,"kind":"candidate_region"}))
            features.append(dict(type="Feature",geometry={"type":"Point","coordinates":[region.best_location.longitude,region.best_location.latitude]},
                                 properties={**properties,"kind":"searched_representative_pose"}))
        return PoseLocalizationResult(status=status,regions=regions,hypotheses=reports,config=config,
                                      warnings=warnings,matched_landmarks=list(used_entities.values()),
                                      elapsed_seconds=round(perf_counter()-started,6),
                                      geojson={"type":"FeatureCollection","features":features},
                                      diagnostics=dict(timings={key:sum(r.timings.get(key,0) for r in reports) for key in ('coarse_seconds','fine_seconds','regions_seconds')},
                                          visibility_seconds=sum(c.visibility_elapsed for c in contexts.values()),
                                          visibility_review_points=sum(getattr(c,'visibility_evaluated_points',0) for c in contexts.values()),
                                          strtree_queries=sum(c.strtree_queries for c in contexts.values())))


class BaselinePoseSolver(PoseSolver):
    """Original defaults, with all three enhancement switches forced off."""
    def __init__(self,store,config=None):
        config = config or PoseSearchConfig()
        super().__init__(store,config.model_copy(update=dict(adaptive_extent=False,footprint_constraints=False,visibility_soft=False,viewpoint_fix=False)))


class EnhancedPoseSolver(PoseSolver):
    """Repaired enhancement defaults; explicit viewpoint_fix=False replays 5.1A."""
    def __init__(self,store,config=None):
        config=config or PoseSearchConfig(adaptive_extent=True,footprint_constraints=True,visibility_soft=True)
        if 'viewpoint_fix' not in config.model_fields_set:
            config=config.model_copy(update={'viewpoint_fix':True})
        super().__init__(store,config)


class FixedPoseSolver(PoseSolver):
    """Fixed sampling/partial-frame/two-stage implementation; legacy stays available."""
    def __init__(self,store,config=None):
        config=config or PoseSearchConfig(adaptive_extent=True,footprint_constraints=True,visibility_soft=True)
        super().__init__(store,config.model_copy(update={'viewpoint_fix':True}))


class JointPoseSolver(FixedPoseSolver):
    """Stage 5.1B defaults; no positional reference accepted by solve()."""
    def __init__(self,store,config=None):
        super().__init__(store,config or PoseSearchConfig(adaptive_extent=True,robust_geometry=True,joint_identity=True,
            dual_regions=True,audit_hard_feasibility=True,visibility_soft=True,max_hypotheses=12))
