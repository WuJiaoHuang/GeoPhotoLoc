"""Controlled nested S0/S1/S2 on an existing E grid; no location references."""
from collections import defaultdict
import hashlib,json
from time import perf_counter
import numpy as np
from shapely import intersects_xy,make_valid
from shapely.geometry import Point,Polygon,shape,mapping
from shapely.ops import unary_union
from geophotoloc.models import GeoPoint
from geophotoloc.models.pose import PoseConstraintScore
from geophotoloc.models.refinement import SpatialRefinementResult
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from .projection import to_local_geometry
from .region_selection import sampled_cell_geometry,preferred_entries
from .selection_v2 import select_quality_modes,evidence_quality
from .robust_scoring import order_constraints
from .footprints import exterior_vertices

LABELS={
 'S0':['Names/OSM identity assignments only','Same finite sampled envelope and fixed observation-distance prior','No image order, projection or heading ranking; no ground standing mask'],
 'S1':['S0 + conservative LEFT_OF/RIGHT_OF in unknown heading','Only reliable coordinates, explicit identity and exact primary name/complete outline','Overlap, missing outline, contradictory or uncertain identity pairs remain indeterminate'],
 'S2':['S1 + E robust geometry and physical mask','Same FOV/projection/outline assumptions and fixed score weights','Evidence-first bounded selection; no calibrated probability']}



def polygonal_valid(geometry,repairs,label,*,geographic=False):
    if geometry.is_valid:return geometry
    from .regions import components
    # Preserve component fill semantics; whole-MultiPolygon even/odd repair can
    # erase broad areas when reprojected components touch at numeric slivers.
    parts=components(geometry)
    repaired=unary_union([p for part in parts for p in components(part if part.is_valid else make_valid(part))])
    delta=abs(repaired.area-geometry.area)
    tolerance=max(1e-14 if geographic else 1e-4,abs(geometry.area)*1e-9)
    if delta>tolerance:raise ValueError('Substantial invalid-geometry repair refused: '+label)
    repairs.append(dict(label=label,method='component-wise make_valid then exact union, no buffer',area_delta=delta,
                        area_units='square_degrees' if geographic else 'square_metres'))
    return repaired


def _angular_arrays(points,geometry):
    vertices=exterior_vertices(geometry)
    directions=vertices[None,:,:]-points[:,None,:]
    angles=np.sort(np.degrees(np.arctan2(directions[:,:,0],directions[:,:,1]))%360,axis=1)
    gaps=np.diff(np.column_stack([angles,angles[:,0]+360]),axis=1)
    indices=np.argmax(gaps,axis=1);width=360-gaps[np.arange(len(points)),indices]
    start=angles[np.arange(len(points)),(indices+1)%angles.shape[1]]
    center=(start+width/2)%360
    # Inside a footprint/exterior (including its courtyard) cannot order silhouettes.
    polygons=[geometry] if geometry.geom_type=='Polygon' else list(geometry.geoms)
    inside=np.zeros(len(points),dtype=bool)
    for p in polygons:inside|=intersects_xy(Polygon(p.exterior),points[:,0],points[:,1])
    return center,width,inside


def conservative_relation_mask(points,observations,candidates,geometries,relations,config):
    points=np.asarray(points,dtype=float).reshape(-1,2)
    passed=np.ones(len(points),dtype=bool);trusted=set();skipped={};arrays={}
    for key,candidate in candidates.items():
        o=observations[key];e=candidate.entity;g=geometries.get(key)
        lexical=(candidate.query_source=='primary' and candidate.score_components.get('name_similarity',0)>=1-1e-9)
        complete=e.complete_geometry and e.geometry_precision=='complete_outline' and g is not None and g.is_valid and not g.is_empty and g.geom_type in {'Polygon','MultiPolygon'}
        if not(o.coordinates_reliable and not o.identity_uncertain and lexical and complete and e.category in {'building','tower','bridge','attraction','historic'}):
            skipped[key]='unreliable_coordinate_or_identity_or_lexical_match_or_complete_outline';continue
        trusted.add(key)
    edges=order_constraints(observations,relations,config)
    contradictory={frozenset((e['left'],e['right'])) for e in edges if e['downweight_reasons']}
    reports=[]
    for edge in edges:
        a,b=edge['left'],edge['right']
        if a not in trusted or b not in trusted or frozenset((a,b)) in contradictory:continue
        if a not in arrays:arrays[a]=_angular_arrays(points,geometries[a]) if len(points) else (np.array([]),np.array([]),np.zeros(0,dtype=bool))
        if b not in arrays:arrays[b]=_angular_arrays(points,geometries[b]) if len(points) else (np.array([]),np.array([]),np.zeros(0,dtype=bool))
        ca,wa,ia=arrays[a];cb,wb,ib=arrays[b]
        delta=(cb-ca+180)%360-180;half=(wa+wb)/2
        determined=(wa<180)&(wb<180)&~(ia|ib)&(np.abs(delta)+half<180-config.angular_tolerance_deg)&(np.abs(delta)>half+config.angular_tolerance_deg)
        conflict=determined&(delta<0);passed&=~conflict
        reports.append(dict(left=a,right=b,satisfied=int(np.sum(determined&(delta>0))),conflicts=int(conflict.sum()),indeterminate=int((~determined).sum())))
    return passed,dict(trusted_landmarks=sorted(trusted),skipped_landmarks=skipped,relations=reports,
        meaning='Conditionally trusted engineering gate, not independent identity confirmation or a probability')


def build_spatial_refinement(vision,matching,pose,bounds):
    start=perf_counter();config=pose.config
    if not(config.robust_geometry and config.dual_regions and config.audit_hard_feasibility):raise ValueError('Robust dual-region traces required')
    observations={o.id:o for o in vision.landmarks}
    lookup={(m.image_landmark_id,c.entity.id):c for m in matching.matches for c in m.candidates}
    local_layers={s:defaultdict(list) for s in ('S0','S1','S2')};systems={};hypotheses=[];ranked=[];repairs=[]
    counts={s:dict(actual=0,passed=0,seconds=0.) for s in local_layers};used=set();used_pairs=set();grid=[]
    feasible={r.hypothesis_id:r for r in pose.feasible_regions}
    for h in pose.hypotheses:
        if not h.searched_points:continue
        if not h.sample_trace or any('phase' not in t for t in h.sample_trace):raise ValueError('Diagnostic trace phases required; never invent a replacement grid')
        b=bounds[h.region_id]
        if h.region_id not in systems:systems[h.region_id]=LocalCoordinateSystem(GeoPoint(latitude=(b.south+b.north)/2,longitude=(b.west+b.east)/2))
        system=systems[h.region_id]
        candidates={k:lookup[k,v] for k,v in h.assignments.items()}
        geometries={k:to_local_geometry(shape(c.entity.geometry),system) if c.entity.geometry else Point(system.to_local(c.entity.location)) for k,c in candidates.items()}
        domain=polygonal_valid(to_local_geometry(shape(h.search_geometry),system),repairs,h.id+':domain')
        # Retain exactly the pre-existing distance-eligible samples, even standing failures.
        traces=[t for t in h.sample_trace if 'outside_exact_distance_domain' not in t.get('reasons',[])]
        points=[(t['x'],t['y']) for t in traces];fine={p for p,t in zip(points,traces) if t['phase']=='fine'}
        grid.append(dict(id=h.id,assignments=h.assignments,points=points,phases=[t['phase'] for t in traces]))
        def envelope(selected):
            selected=set(selected)
            return sampled_cell_geometry(sorted(selected-fine),sorted(selected&fine),h.coarse_spacing_m,config.fine_spacing_m,domain)
        timer=perf_counter();s0=envelope(points);t0=perf_counter()-timer
        timer=perf_counter();mask,audit=conservative_relation_mask(points,observations,candidates,geometries,vision.relations,config)
        s1_points=[p for p,keep in zip(points,mask) if keep]
        s1=s0 if mask.all() else envelope(s1_points).intersection(s0);t1=perf_counter()-timer
        timer=perf_counter();physical=polygonal_valid(to_local_geometry(shape(feasible[h.id].geometry),system),repairs,h.id+':physical') if h.id in feasible else Polygon()
        scores={p:PoseConstraintScore(feasible=True,score=t['score'],components=t.get('components',{}),reliable_landmark_count=t.get('reliable_landmarks',0))
                for p,t,keep in zip(points,traces,mask) if keep and t['feasible']}
        allowed=physical.intersection(s1)
        entries=preferred_entries(scores,fine,h.coarse_spacing_m,config.fine_spacing_m,allowed,config.score_window,config.preferred_tile_size_m) if scores else []
        chosen,selection=select_quality_modes(entries,scores,config.max_regions_per_hypothesis,config.preferred_tile_size_m**2)
        s2=unary_union([g for g,_ in chosen]).intersection(s1)
        t2=perf_counter()-timer
        retained=set(p for _,members in chosen for p in members)
        for g,members in chosen:
            best=min(members,key=lambda p:(-scores[p].score,p));value=scores[best]
            ranked.append(dict(hypothesis_id=h.id,region_id=h.region_id,geometry=mapping(to_geographic(g,system)),area_m2=g.area,
              score=value.score,quality=list(evidence_quality(value)),best_location=system.to_geographic(best).model_dump(),members=len(members)))
        if s1.difference(s0).area>1e-4 or s2.difference(s1).area>1e-4:raise RuntimeError('Nested layer invariant violated')
        for s,g,n,seconds in [('S0',s0,len(points),t0),('S1',s1,len(s1_points),t1),('S2',s2,len(retained),t2)]:
            local_layers[s][h.region_id].append(g);counts[s]['actual']+=len(points);counts[s]['passed']+=n;counts[s]['seconds']+=seconds
        used.update(k for k in h.assignments if observations[k].coordinates_reliable)
        used_pairs.update((e['left'],e['right']) for e in audit['relations'])
        hypotheses.append(dict(id=h.id,region_id=h.region_id,assignments=h.assignments,input_visited_points=h.searched_points,distance_rejected_points=h.searched_points-len(points),points=len(points),relation_passed=len(s1_points),full_geometry_scored=len(scores),retained_points=len(retained),
            areas_m2=dict(S0=s0.area,S1=s1.area,S2=s2.area),relations=audit,selection=selection,source_spacing_m=h.coarse_spacing_m,
            interpretation='Same finite grid; counts are point-hypothesis records, not unique locations'))
    layers=[];features=[];previous=None;previous_geographic=None
    for stage,regions in local_layers.items():
        unions={rid:unary_union(parts) for rid,parts in regions.items()}
        area=sum(g.area for g in unions.values());geographic=unary_union([polygonal_valid(to_geographic(g,systems[rid]),repairs,stage+':display:'+rid,geographic=True) for rid,g in unions.items()])
        if previous_geographic is not None:geographic=geographic.intersection(previous_geographic)
        geometry=mapping(geographic);previous_geographic=geographic
        layer=dict(stage=stage,geometry=geometry,area_m2=area,reduction_from_previous=None if previous in (None,0) else 1-area/previous,
           actual_points=counts[stage]['actual'],passed_points=counts[stage]['passed'],reliable_landmarks=len(used),reliable_relations=0 if stage=='S0' else len(used_pairs),
           ranked=stage=='S2',seconds=counts[stage]['seconds'],constraints=LABELS[stage])
        layers.append(layer);features.append(dict(type='Feature',geometry=geometry,properties=dict(stage=stage,area_m2=area,ranked=stage=='S2')));previous=area
    ranked.sort(key=lambda r:(tuple(-q for q in r['quality']),r['hypothesis_id'],r['best_location']['latitude'],r['best_location']['longitude']))
    for i,r in enumerate(ranked,1):r['rank']=i
    result=dict(layers=layers,ranked_regions=ranked,hypotheses=hypotheses,geojson=dict(type='FeatureCollection',features=features),
      geometry_repairs=repairs,grid_fingerprint=hashlib.sha256(json.dumps(grid,sort_keys=True).encode()).hexdigest(),elapsed_seconds=perf_counter()-start,
      warnings=['S2 is controlled S1-constrained refinement, distinct from soft-order E Preferred','S0/S1 are unranked; no invented Top-1',
        'Sampled cells, not exhaustive continuous domains; rounding follows saved 1e-6m traces','Areas use local metres; WGS84 display chords clipped again to enforce visible nesting','Unknown identities may leave the union broad despite individual relation gains',
        'All layers inherit fixed distance/finite budget/partial OSM coverage assumptions','Area reduction alone is not a localization accuracy improvement'])
    if not grid:result['warnings'].append('No eligible shared multi-landmark grid; insufficient evidence, no manufactured position')
    return SpatialRefinementResult.model_validate(result).model_dump(mode='json')


def to_geographic(geometry,system):
    from .projection import to_wgs84_geometry
    return to_wgs84_geometry(geometry,system)


def build_reliable_spatial_refinement(vision,matching,pose,bounds,historical,*,evidence=None):
    """Independent Stage 5.3 path; historical S0/S1/S2 remain byte-preserved."""
    from .refinement_reliable import build_reliable_refinement
    return build_reliable_refinement(vision,matching,pose,bounds,historical,evidence=evidence)
