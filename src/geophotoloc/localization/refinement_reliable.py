"""Stage 5.3 independent construction on frozen E traces and historical layers."""
from collections import defaultdict,Counter
from time import perf_counter
import hashlib,json
from shapely.geometry import Point,Polygon,shape,mapping
from shapely.ops import unary_union
from geophotoloc.models import GeoPoint
from geophotoloc.models.pose import PoseConstraintScore
from geophotoloc.models.refinement import ReliableRefinementResult,SpatialRefinementResult
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from .spatial_refinement import polygonal_valid,to_geographic
from .projection import to_local_geometry
from .region_selection import sampled_cell_geometry,preferred_entries
from .selection_v2 import select_quality_modes,evidence_quality
from .relation_reliability import classify_relations


def build_reliable_refinement(vision,matching,pose,bounds,historical,*,evidence=None):
    start=perf_counter();config=pose.config
    SpatialRefinementResult.model_validate(historical)
    if not(config.robust_geometry and config.dual_regions and config.audit_hard_feasibility):raise ValueError('Frozen robust traces required')
    obs={o.id:o for o in vision.landmarks};lookup={(m.image_landmark_id,c.entity.id):c for m in matching.matches for c in m.candidates}
    systems={};parts={s:defaultdict(list) for s in ('S1-R','S2-R')};stats={s:dict(points=0,passed=0,seconds=0.) for s in parts}
    physical_by_id={r.hypothesis_id:r for r in pose.feasible_regions}
    audits=[];ranked=[];repairs=[];grid=[];counts=Counter()
    for h in pose.hypotheses:
        if not h.searched_points:continue
        if not h.sample_trace or any('phase' not in t for t in h.sample_trace):raise ValueError('Original trace required')
        b=bounds[h.region_id]
        system=systems.setdefault(h.region_id,LocalCoordinateSystem(GeoPoint(latitude=(b.south+b.north)/2,longitude=(b.west+b.east)/2)))
        candidates={k:lookup[k,v] for k,v in h.assignments.items()}
        geometries={k:to_local_geometry(shape(c.entity.geometry),system) if c.entity.geometry else Point(system.to_local(c.entity.location)) for k,c in candidates.items()}
        traces=[t for t in h.sample_trace if 'outside_exact_distance_domain' not in t.get('reasons',[])]
        points=[(t['x'],t['y']) for t in traces];fine={p for p,t in zip(points,traces) if t['phase']=='fine'}
        grid.append(dict(id=h.id,assignments=h.assignments,points=points,phases=[t['phase'] for t in traces]))
        domain=polygonal_valid(to_local_geometry(shape(h.search_geometry),system),repairs,h.id+':domain')
        def envelope(selected):
            selected=set(selected)
            return sampled_cell_geometry(sorted(selected-fine),sorted(selected&fine),h.coarse_spacing_m,config.fine_spacing_m,domain)
        timer=perf_counter();mask,audit=classify_relations(points,obs,candidates,geometries,vision.relations,config,evidence)
        # Reuse local S0 union once for both paths, never a hull or buffer.
        s0=envelope(points);selected=[p for p,keep in zip(points,mask) if keep]
        s1=s0 if mask.all() else envelope(selected).intersection(s0);t1=perf_counter()-timer
        timer=perf_counter();physical=polygonal_valid(to_local_geometry(shape(physical_by_id[h.id].geometry),system),repairs,h.id+':physical') if h.id in physical_by_id else Polygon()
        scores={p:PoseConstraintScore(feasible=True,score=t['score'],components=t.get('components',{}),reliable_landmark_count=t.get('reliable_landmarks',0)) for p,t,keep in zip(points,traces,mask) if keep and t['feasible']}
        allowed=physical.intersection(s1)
        entries=preferred_entries(scores,fine,h.coarse_spacing_m,config.fine_spacing_m,allowed,config.score_window,config.preferred_tile_size_m) if scores else []
        chosen,selection=select_quality_modes(entries,scores,config.max_regions_per_hypothesis,config.preferred_tile_size_m**2)
        s2=unary_union([g for g,_ in chosen]).intersection(s1);t2=perf_counter()-timer
        retained={p for _,members in chosen for p in members}
        for g,members in chosen:
            best=min(members,key=lambda p:(-scores[p].score,p));v=scores[best]
            ranked.append(dict(stage='S2-R',hypothesis_id=h.id,geometry=mapping(to_geographic(g,system)),area_m2=g.area,score=v.score,quality=list(evidence_quality(v)),best_location=system.to_geographic(best).model_dump()))
        if s1.difference(s0).area>1e-4 or s2.difference(s1).area>1e-4:raise RuntimeError('Reliability containment violated')
        for s,g,n,elapsed in [('S1-R',s1,len(selected),t1),('S2-R',s2,len(retained),t2)]:
            parts[s][h.region_id].append(g);stats[s]['points']+=len(points);stats[s]['passed']+=n;stats[s]['seconds']+=elapsed
        for relation in audit['relations']:counts.update(relation['counts'])
        audits.append(dict(id=h.id,assignments=h.assignments,points=points,relations=audit,areas_m2={'S0':s0.area,'S1-R':s1.area,'S2-R':s2.area},selection=selection))
    fingerprint=hashlib.sha256(json.dumps(grid,sort_keys=True).encode()).hexdigest()
    if fingerprint!=historical['grid_fingerprint']:raise ValueError('Historical grid mismatch')
    layers={l['stage']:l for l in historical['layers']};s0area=layers['S0']['area_m2'];previous=shape(layers['S0']['geometry'])
    for stage in parts:
        unions={rid:unary_union(gs) for rid,gs in parts[stage].items()};area=sum(g.area for g in unions.values())
        geographic=unary_union([polygonal_valid(to_geographic(g,systems[rid]),repairs,stage+':display:'+rid,geographic=True) for rid,g in unions.items()]).intersection(previous)
        previous=geographic
        from .regions import components
        layers[stage]=dict(stage=stage,geometry=mapping(geographic),area_m2=area,reduction_from_previous=None if stage=='S1-R' or layers['S1-R']['area_m2']==0 else 1-area/layers['S1-R']['area_m2'],
          reduction_from_s0=None if not s0area else 1-area/s0area,actual_points=stats[stage]['points'],passed_points=stats[stage]['passed'],
          reliable_landmarks=layers['S0']['reliable_landmarks'],reliable_relations=len({(r['left'],r['right']) for h in audits for r in h['relations']['relations'] if r['counts']['HARD']}),
          ranked=stage=='S2-R',seconds=stats[stage]['seconds'],constraints=['HARD conflicts only; SOFT means diagnostic only; UNKNOWN neutral','Independent identity/full visibility evidence required for HARD'],relation_counts={k:counts[k] for k in ('HARD','SOFT','UNKNOWN')},region_count=len(components(geographic)))
    ranked.sort(key=lambda r:(tuple(-v for v in r['quality']),r['hypothesis_id'],r['best_location']['latitude'],r['best_location']['longitude']))
    for i,r in enumerate(ranked,1):r['rank']=i
    ordered=[layers[s] for s in ('S0','S1','S1-R','S2','S2-R')]
    return ReliableRefinementResult.model_validate(dict(layers=ordered,ranked_regions=historical['ranked_regions']+ranked,hypotheses=audits,
      geojson={'type':'FeatureCollection','features':[dict(type='Feature',geometry=l['geometry'],properties={'stage':l['stage']}) for l in ordered]},grid_fingerprint=fingerprint,
      elapsed_seconds=perf_counter()-start,geometry_repairs=repairs,warnings=historical['warnings']+['S1 and S1-R are parallel; S2-R descends only from S1-R','No independent full-visibility/identity evidence means no HARD relation; no shrink is a valid result','SOFT scores never change coverage or original geometry scores'])).model_dump(mode='json')
