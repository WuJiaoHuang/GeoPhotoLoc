"""Independent post-solve measurements; cannot insert, search or rerank poses."""
import hashlib,json
from collections import Counter
import numpy as np
from shapely.geometry import Point,shape
from geophotoloc.maps import LandmarkStore
from geophotoloc.models import GeoPoint
from geophotoloc.models.maps import GeoBounds
from geophotoloc.geometry.coordinates import horizontal_distance,LocalCoordinateSystem
from geophotoloc.localization.projection import to_local_geometry
from geophotoloc.localization.search import SearchContext
from geophotoloc.localization.robust_scoring import evaluate_robust_pose
from geophotoloc.app.evaluation import evaluate_camera_location
from evaluate_stage5_1b import ROOT,OUTPUT,GROUPS,CASES,read_result
from evaluate_stage5_1a import load_inputs


def main():
    manifest=json.loads((OUTPUT/'run_manifest.json').read_text(encoding='utf-8'))
    required={f'{g}_{c}.json.gz' for g in GROUPS for c in CASES}|{f'{g}_summary.json' for g in GROUPS}
    if set(manifest['artifacts'])!=required:raise ValueError('All sixteen independent solves and four summaries required')
    for name,digest in manifest['artifacts'].items():
        if hashlib.sha256((OUTPUT/name).read_bytes()).hexdigest()!=digest:raise ValueError('Incomplete inference artifact')
    references=json.loads((ROOT/'docs/evaluation/stage5/camera_truth.json').read_text(encoding='utf-8'))
    records=[];nearby=[];evidence=[];contexts={}
    with LandmarkStore() as store:
        def get_context(region_id):
            if region_id not in contexts:
                raw=store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(region_id,)).fetchone()[0]
                contexts[region_id]=SearchContext(store,region_id,GeoBounds.model_validate_json(raw))
            return contexts[region_id]
        for group in GROUPS:
            for ref in references:
                case=ref['case'];pose=read_result(group,case)
                for region in pose.regions:
                    s=region.best_score
                    evidence.append(dict(group=group,case=case,region_id=region.id,hypothesis_id=region.hypothesis_id,assignments=region.assignments,
                        unknown_image_ids=s.unknown_image_ids,outlier_image_ids=s.outlier_image_ids,reliable_landmark_count=s.reliable_landmark_count,
                        projection=s.projection_evidence,order=s.order_evidence,outlier_comparisons=s.outlier_comparisons))
                record=dict(group=group,case=case,evaluated=ref['kind']=='camera_location',source=ref['source'],reference_kind=ref['kind'],
                            feasible_area_m2=pose.feasible_area_m2,preferred_area_m2=pose.preferred_area_m2)
                if not record['evaluated']:
                    record['reason']='Only bridge-level description, no fabricated metre error';records.append(record);continue
                reference=GeoPoint(latitude=ref['latitude'],longitude=ref['longitude'])
                record.update(evaluate_camera_location(pose,reference))
                system=LocalCoordinateSystem(reference)
                local=[to_local_geometry(shape(r.geometry),system) for r in pose.feasible_regions]
                record['feasible_contains_reference']=any(g.covers(Point(0,0)) for g in local)
                record['nearest_feasible_distance_m']=min((g.distance(Point(0,0)) for g in local),default=None)
                record['preferred_topk_hits']={str(k):any(rank<=k for rank in record['containing_ranks']) for k in (1,3,5,10)}
                record['top1_medoid_distance_m']=horizontal_distance(reference,pose.regions[0].region_medoid) if pose.regions else None
                record['reference_in_sampled_coverage']=any(shape(h.sampled_geometry).covers(Point(reference.longitude,reference.latitude)) for h in pose.hypotheses if h.sampled_geometry)
                vision,matching,_=load_inputs(case);observations={o.id:o for o in vision.landmarks}
                lookup={(m.image_landmark_id,c.entity.id):c for m in matching.matches for c in m.candidates}
                record['nearby_evaluated_samples']=0;record['nearby_feasible_samples']=0
                for hypothesis in pose.hypotheses:
                    if not hypothesis.sample_trace:continue
                    ctx=get_context(hypothesis.region_id);p=ctx.system.to_local(reference)
                    points=np.array([(t['x'],t['y']) for t in hypothesis.sample_trace])
                    distance=np.hypot(points[:,0]-p[0],points[:,1]-p[1]);indexes=np.flatnonzero(distance<=200)
                    record['nearby_evaluated_samples']+=len(indexes)
                    record['nearby_feasible_samples']+=sum(hypothesis.sample_trace[i]['feasible'] for i in indexes)
                    reason_counts=Counter(reason for i in indexes for reason in hypothesis.sample_trace[i]['reasons'])
                    entry=dict(group=group,case=case,hypothesis_id=hypothesis.id,unknown_image_ids=hypothesis.unknown_image_ids,
                        nearest_sample_m=float(distance.min()),samples_within_200m=len(indexes),feasible_within_200m=sum(hypothesis.sample_trace[i]['feasible'] for i in indexes),rejection_reasons=dict(reason_counts))
                    preferred=[shape(r.geometry) for r in pose.regions if r.hypothesis_id==hypothesis.id]
                    entry['nearby_feasible_retained_as_preferred']=sum(hypothesis.sample_trace[i]['feasible'] and any(g.covers(Point((q:=ctx.system.to_geographic(tuple(points[i]))).longitude,q.latitude)) for g in preferred) for i in indexes)
                    if pose.config.robust_geometry and len(indexes):
                        existing=int(min(indexes,key=lambda i:distance[i]));xy=tuple(points[existing])
                        candidates=[(key,lookup[(key,entity_id)]) for key,entity_id in sorted(hypothesis.assignments.items())]
                        entities={key:c.entity for key,c in candidates};coords={key:ctx.system.to_local(e.location) for key,e in entities.items()};geoms={key:ctx.project_entity(e) for key,e in entities.items()}
                        filters=ctx.filter_reasons(xy,list(geoms.values()),allow_uncovered=True)
                        audit=evaluate_robust_pose(xy,observations,entities,coords,geoms,[c.score for _,c in candidates],vision.relations,pose.config,ctx,standing_filters=filters)
                        entry['closest_existing_sample_audit']=dict(distance_m=float(distance[existing]),original_trace=hypothesis.sample_trace[existing],score=audit.model_dump(mode='json'),
                            note='Only an already evaluated point is re-audited; no new sampling or region/rank modifications')
                    nearby.append(entry)
                records.append(record)
    (OUTPUT/'camera_evaluation.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUTPUT/'nearby_sample_audit.json').write_text(json.dumps(nearby,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUTPUT/'candidate_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    assert all(hashlib.sha256((OUTPUT/name).read_bytes()).hexdigest()==digest for name,digest in manifest['artifacts'].items())
    print(json.dumps([dict(group=r['group'],case=r['case'],feasible_hit=r.get('feasible_contains_reference'),preferred_hit=r.get('truth_inside_any'),nearest_preferred=r.get('nearest_region_distance_m'),top1=r.get('top1_point_distance_m')) for r in records],ensure_ascii=False,indent=2))


if __name__=='__main__':main()
