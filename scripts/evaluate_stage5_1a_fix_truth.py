"""Independent audit AFTER all inference; never generates or adds candidates."""
import hashlib,json
from collections import Counter
from pathlib import Path
import numpy as np
from shapely import get_coordinates
from shapely.geometry import Point,shape
from evaluate_stage5_1a_fix import OUTPUT,GROUPS,CASES,ROOT
from evaluate_stage5_1a import load_inputs
from geophotoloc.models import GeoPoint,PoseLocalizationResult
from geophotoloc.models.maps import GeoBounds
from geophotoloc.maps import LandmarkStore
from geophotoloc.app.evaluation import evaluate_camera_location
from geophotoloc.geometry.coordinates import horizontal_distance
from geophotoloc.localization.search import SearchContext
from geophotoloc.localization.partial import evaluate_partial_pose
from geophotoloc.localization.enhanced import evaluate_enhanced_pose
from geophotoloc.localization.footprints import circular_segments,intersect_segments
from math import atan,degrees,radians,tan


def main():
    manifest=json.loads((OUTPUT/'run_manifest.json').read_text(encoding='utf-8'))
    for name,digest in manifest['artifacts'].items():
        if hashlib.sha256((OUTPUT/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Incomplete or modified inference artifacts')
    for group in GROUPS:
        for case in CASES:
            if f'{group}_{case}.json' not in manifest['artifacts']:raise ValueError('All independent solves required')
    # Reference file is opened only after completion/integrity checks.
    references=json.loads((ROOT/'docs/evaluation/stage5/camera_truth.json').read_text(encoding='utf-8'))
    records=[];diagnostics=[];contexts={}
    with LandmarkStore() as store:
        for group in GROUPS:
            for ref in references:
                case=ref['case']
                result=PoseLocalizationResult.model_validate_json((OUTPUT/f'{group}_{case}.json').read_text(encoding='utf-8'))
                record=dict(group=group,case=case,source=ref['source'],reference_kind=ref['kind'],evaluated=ref['kind']=='camera_location')
                if not record['evaluated']:
                    record['reason']='Bridge-level description only; no fabricated metre error';records.append(record);continue
                reference=GeoPoint(latitude=ref['latitude'],longitude=ref['longitude'])
                record.update(evaluate_camera_location(result,reference))
                record['top1_medoid_distance_m']=horizontal_distance(reference,result.regions[0].region_medoid) if result.regions and result.regions[0].region_medoid else None
                record['reference_inside_search_domain']=any(shape(h.search_geometry).covers(Point(reference.longitude,reference.latitude)) for h in result.hypotheses if h.search_geometry)
                record['reference_inside_sampled_cell_coverage']=any(shape(h.sampled_geometry).covers(Point(reference.longitude,reference.latitude)) for h in result.hypotheses if h.sampled_geometry)
                vision,matching,_=load_inputs(case)
                observations={o.id:o for o in vision.landmarks}
                lookup={(m.image_landmark_id,c.entity.id):c for m in matching.matches for c in m.candidates}
                near=[]
                for h in result.hypotheses:
                    if not h.sample_trace:continue
                    if h.region_id not in contexts:
                        raw=store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(h.region_id,)).fetchone()[0]
                        contexts[h.region_id]=SearchContext(store,h.region_id,GeoBounds.model_validate_json(raw))
                    ctx=contexts[h.region_id];p=ctx.system.to_local(reference)
                    points=np.array([(t['x'],t['y']) for t in h.sample_trace])
                    distances=np.hypot(points[:,0]-p[0],points[:,1]-p[1])
                    indexes=np.flatnonzero(distances<=200)
                    selected=sorted(indexes,key=lambda i:distances[i])[:20]
                    near.append(dict(hypothesis_id=h.id,nearest_evaluated_sample_m=float(distances.min()),
                        samples_within_200m=len(indexes),feasible_within_200m=sum(h.sample_trace[i]['feasible'] for i in indexes),
                        rejection_reasons=dict(Counter(reason for i in indexes for reason in h.sample_trace[i]['reasons'])),
                        closest_existing_samples=[dict(distance_m=float(distances[i]),**h.sample_trace[i]) for i in selected]))
                    if group!='full_enhanced':continue
                    candidates=[(image_id,lookup[(image_id,entity_id)]) for image_id,entity_id in sorted(h.assignments.items())]
                    entities={key:c.entity for key,c in candidates}
                    xy={key:ctx.system.to_local(e.location) for key,e in entities.items()}
                    geoms={key:ctx.project_entity(e) for key,e in entities.items()}
                    target_geoms=[g for e,g in zip(entities.values(),geoms.values()) if e.complete_geometry and e.geometry_precision=='complete_outline']
                    filters=ctx.filter_reasons(p,target_geoms,allow_uncovered=True)
                    config=result.config.model_copy(update=dict(visibility_soft=False,footprint_constraints=True))
                    partial=evaluate_partial_pose(p,observations,entities,xy,geoms,[c.score for _,c in candidates],vision.relations,config,ctx,standing_filters=filters)
                    outlines={}
                    for key,g in geoms.items():
                        if g is not None:
                            coords=get_coordinates(g);outlines[key]=[tuple(v) for v in coords[::max(1,len(coords)//32)]]
                    old=evaluate_enhanced_pose(p,observations,entities,xy,outlines,[c.score for _,c in candidates],vision.relations,config,ctx,geoms,standing_filters=filters)
                    # Independent witnesses for failed configured FOV/principal hypotheses.
                    witness=[]
                    for fov in config.fov_degrees:
                        for principal in config.principal_points:
                            allowed=[(0.,360.)];first_empty=None
                            for fp in partial.footprint_evidence:
                                key=fp['image_landmark_id'];x=observations[key].x
                                if not observations[key].coordinates_reliable or fp['geometry_quality']!='COMPLETE_OUTLINE':continue
                                scale=2*tan(radians(fov/2))
                                low=degrees(atan((max(0,x-config.observation_x_tolerance)-principal)*scale))
                                high=degrees(atan((min(1,x+config.observation_x_tolerance)-principal)*scale))
                                allowed=intersect_segments(allowed,circular_segments(fp['left_bound_deg']-high,fp['angular_width_deg']+high-low))
                                if not allowed:first_empty=key;break
                            witness.append(dict(fov=fov,principal=principal,first_inconsistent_image_id=first_empty,heading_intervals=allowed))
                    diagnostics.append(dict(case=case,hypothesis_id=h.id,assignments=h.assignments,known_surface_filters=filters,
                        original_full_outline_model_at_reference=old.model_dump(mode='json'),
                        partial_model_at_reference=partial.model_dump(mode='json'),heading_observation_witness=witness))
                record['nearby_grid_diagnostics']=near
                record['nearest_actual_sample_m']=min((n['nearest_evaluated_sample_m'] for n in near),default=None)
                records.append(record)
    (OUTPUT/'camera_evaluation.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUTPUT/'reference_constraint_diagnostics.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps([dict(group=r['group'],case=r['case'],inside_search=r.get('reference_inside_search_domain'),inside_sampled=r.get('reference_inside_sampled_cell_coverage'),nearest_sample=r.get('nearest_actual_sample_m'),nearest_region=r.get('nearest_region_distance_m'),top1=r.get('top1_point_distance_m')) for r in records],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
