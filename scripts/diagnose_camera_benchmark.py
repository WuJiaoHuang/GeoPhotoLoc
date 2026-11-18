"""Post-inference metrics/audit. References never generate or rerank candidates."""
import gzip,hashlib,json,math
from collections import Counter,defaultdict
from pathlib import Path
import numpy as np
from shapely.geometry import Point,shape
from geophotoloc.models import GeoPoint,VisionExtractionResult
from geophotoloc.models.pose import PoseLocalizationResult
from geophotoloc.geometry.coordinates import LocalCoordinateSystem,horizontal_distance
from geophotoloc.localization.projection import to_local_geometry
from geophotoloc.app.evaluation import evaluate_camera_location
from run_camera_benchmark import OUT,ROOT,digest,save


def percentile_summary(values):
 values=[v for v in values if v is not None and math.isfinite(v)]
 return dict(n=len(values),median_m=float(np.median(values)) if values else None,p25_m=float(np.percentile(values,25)) if values else None,
             p75_m=float(np.percentile(values,75)) if values else None,p90_m=float(np.percentile(values,90)) if values else None,min_m=min(values,default=None),max_m=max(values,default=None))


def verify_manifest(root):
 manifest=json.loads((root/'inference_manifest.json').read_text(encoding='utf-8'))
 manifest['artifacts']={name.replace('\\','/'):sha for name,sha in manifest['artifacts'].items()}
 for name,sha in manifest['artifacts'].items():
  if digest(root/name)!=sha:raise ValueError('Inference artifact modified: '+name)
 return manifest


def classify(vision_count,reliable_vision,matched,pose):
 if reliable_vision<2:return 'vision_insufficient_reliable_observations'
 if matched<2:return 'map_insufficient_matched_objects'
 if not sum(h.searched_points for h in pose.hypotheses):return 'geometry_no_eligible_hypothesis'
 traces=[t for h in pose.hypotheses for t in h.sample_trace]
 if not any(t.get('hard_feasible') for t in traces):return 'geometry_no_hard_feasible_sample'
 if not pose.regions:return 'geometry_scoring_or_region_selection_empty'
 return 'candidates_produced_not_necessarily_correct'


def audit_existing_points(pose,reference,bounds):
 # Linear transform derives each original search CRS from stored map bounds, not reference.
 contexts={};rows=[];hypotheses=[]
 all_scores=[t['score'] for h in pose.hypotheses for t in h.sample_trace if t.get('feasible') and 'score' in t]
 for h in pose.hypotheses:
  b=bounds[h.region_id]
  system=contexts.setdefault(h.region_id,LocalCoordinateSystem(GeoPoint(latitude=(b['south']+b['north'])/2,longitude=(b['west']+b['east'])/2)))
  ref_xy=system.to_local(reference)
  points=h.sample_trace
  if not points:
   hypotheses.append(dict(hypothesis_id=h.id,assignments=h.assignments,searched=0,reasons=h.reasons));continue
  distances=[math.hypot(t['x']-ref_xy[0],t['y']-ref_xy[1]) for t in points]
  closest=min(range(len(points)),key=lambda i:distances[i]);near=[i for i,d in enumerate(distances) if d<=200]
  candidates=sorted((i for i in near if points[i].get('feasible')),key=lambda i:(-points[i].get('score',0),distances[i]))
  picked=list(dict.fromkeys([closest]+candidates[:3]))
  selected=[]
  for i in picked:
   t=points[i];score=t.get('score');p=system.to_geographic((t['x'],t['y']))
   selected.append(dict(distance_m=distances[i],location=p.model_dump(),trace=t,
       global_score_rank_lower=1+sum(s>score for s in all_scores) if t.get('feasible') and score is not None else None,
       containing_preferred_ranks=[rank+1 for rank,r in enumerate(pose.regions) if r.hypothesis_id==h.id and shape(r.geometry).covers(Point(p.longitude,p.latitude))]))
  counts=Counter(t.get('selection_stage','not_recorded') for t in points)
  nearby_counts=Counter(points[i].get('selection_stage','not_recorded') for i in near)
  hypotheses.append(dict(hypothesis_id=h.id,assignments=h.assignments,unknowns=h.unknown_image_ids,searched=h.searched_points,nearest_sample_m=distances[closest],
       samples_within_200m=len(near),hard_feasible_within_200m=sum(points[i].get('hard_feasible',False) for i in near),stage_counts=dict(counts),nearby_stage_counts=dict(nearby_counts),examples=selected,
       candidate_flow_counts=dict(searched=len(points),physical_audit_pass=sum(t.get('hard_feasible',False) for t in points),visual_score_pass=sum(t.get('feasible',False) for t in points),
         window_eligible=sum(t.get('window_cutoff') is not None and t.get('score',-1)>=t['window_cutoff'] for t in points),
         member_points_before_region_cap=counts.get('region_cap',0)+counts.get('preferred',0),member_points_after_region_cap=counts.get('preferred',0),
         output_regions=sum(r.hypothesis_id==h.id for r in pose.regions)),
       warnings=h.reasons))
  rows.extend(dict(distance_m=distances[i],**points[i]) for i in near)
 return dict(hypotheses=hypotheses,nearby_stage_counts=dict(Counter(r.get('selection_stage','not_recorded') for r in rows)),
             nearest_sample_m=min((h['nearest_sample_m'] for h in hypotheses if 'nearest_sample_m' in h),default=None),
             searched_near_reference=bool(rows),note='Existing rounded traces only, 200m diagnostic radius; reference never inserted as sample. Point rank includes duplicate hypotheses, is not output region rank.')


def detailed_score_audits(audits):
 from geophotoloc.maps import LandmarkStore
 from geophotoloc.models.maps import MapMatchingResult,GeoBounds
 from geophotoloc.localization.search import SearchContext
 from geophotoloc.localization.robust_scoring import evaluate_robust_pose
 configs=json.loads((OUT/'frozen_configs.json').read_text(encoding='utf-8'))
 from geophotoloc.models.pose import PoseSearchConfig
 contexts={}
 if digest(ROOT/'.cache/geophotoloc/maps.sqlite3')!=json.loads((OUT/'map_snapshot.json').read_text())['sha256']:raise ValueError('Map snapshot differs; detailed audit forbidden')
 with LandmarkStore(ROOT/'.cache/geophotoloc/maps.sqlite3') as store:
  for audit in audits:
   config=PoseSearchConfig(**configs[audit['group']])
   if not config.robust_geometry:continue
   key=audit['case'];vision=VisionExtractionResult.model_validate_json((OUT/'inputs'/f'{key}.vision.json').read_bytes())
   matching=MapMatchingResult.model_validate_json((OUT/'inputs'/f'{key}.matches.json').read_bytes())
   observations={o.id:o for o in vision.landmarks}
   lookup={(m.image_landmark_id,c.entity.id):c for m in matching.matches for c in m.candidates}
   pose=PoseLocalizationResult.model_validate_json(gzip.decompress((OUT/'poses'/f"{audit['group']}_{key}.json.gz").read_bytes()))
   reports={h.id:h for h in pose.hypotheses}
   for h in audit['hypotheses']:
    if not h.get('examples'):continue
    report=reports[h['hypothesis_id']];rid=report.region_id
    if rid not in contexts:
     raw=store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(rid,)).fetchone()[0]
     contexts[rid]=SearchContext(store,rid,GeoBounds.model_validate_json(raw))
    ctx=contexts[rid];selected=[(k,lookup[k,v]) for k,v in sorted(report.assignments.items())]
    entities={k:c.entity for k,c in selected};coordinates={k:ctx.system.to_local(e.location) for k,e in entities.items()};geometries={k:ctx.project_entity(e) for k,e in entities.items()}
    for example in h['examples']:
     t=example['trace'];point=(t['x'],t['y'])
     if not t.get('hard_feasible'):continue
     score=evaluate_robust_pose(point,observations,entities,coordinates,geometries,[c.score for _,c in selected],vision.relations,config,ctx)
     example['detailed_score_audit']=score.model_dump(mode='json')
     example['rounded_trace_score_delta']=score.score-t.get('score',0)
     example['audit_note']='Existing rounded sample only; detailed scoring cannot change outputs; 1e-6m coordinate rounding can perturb discrete ties.'
 return audits


def main():
 manifest=verify_manifest(OUT)
 outcomes=json.loads((OUT/'run_outcomes.json').read_text(encoding='utf-8'))
 inputs=json.loads((OUT/'inference_inputs.json').read_text(encoding='utf-8'))
 if {r['case'] for r in outcomes}!={r['id'] for r in inputs}:raise ValueError('All inference outcomes must be finalized first')
 ledger=json.loads((OUT/'api_requests.json').read_text(encoding='utf-8'))
 if any(r['status']=='started' for r in ledger):raise ValueError('A live request or pipeline is still running')
 for sample in inputs:
  key=sample['id']
  if (OUT/'inputs'/f'{key}.vision.json').exists():
   expected={f'poses/{g}_{key}.json.gz' for g in ('baseline','robust_only','identity_only','joint_full')}|{f'summaries/{g}_{key}.json' for g in ('baseline','robust_only','identity_only','joint_full')}|{f'inputs/{key}.vision.json',f'inputs/{key}.matches.json'}
   if not expected<=manifest['artifacts'].keys():raise ValueError('All four groups must be frozen before reference access: '+key)
 freeze=json.loads((OUT/'dataset_freeze.json').read_text(encoding='utf-8'))
 if digest(OUT/'dataset_references.json')!=freeze['reference_sha256']:raise ValueError('References changed')
 refs=json.loads((OUT/'dataset_references.json').read_text(encoding='utf-8'))['samples']
 # Imported bounds and provenance are frozen for every group; no online request.
 imports=json.loads((ROOT/'docs/evaluation/stage3/imports.json').read_text(encoding='utf-8'))
 bounds={r['region_id']:r['bounds'] for r in imports}
 rows=[];audits=[]
 for ref in refs:
  key=ref['id'];vp=OUT/'inputs'/f'{key}.vision.json';mp=OUT/'inputs'/f'{key}.matches.json'
  vision=VisionExtractionResult.model_validate_json(vp.read_bytes()) if vp.exists() else None
  matching=json.loads(mp.read_text(encoding='utf-8')) if mp.exists() else None
  for group in ('baseline','robust_only','identity_only','joint_full'):
   path=OUT/'poses'/f'{group}_{key}.json.gz'
   row=dict(case=key,group=group,split=ref['split'],reference_quality=ref['reference']['quality'],reference_accuracy_m=ref['reference']['accuracy_m'],
      metric_note='Distance to self-reported camera coordinate, not surveyed positional error',top1_point_distance_m=None,nearest_region_distance_m=None,preferred_topk_hits={str(k):False for k in (3,5,10)})
   if not path.exists():
    row.update(stage='vision_api_or_schema_failure' if vision is None else 'map_or_geometry_execution_failure',candidate_regions=0);rows.append(row);continue
   pose=PoseLocalizationResult.model_validate_json(gzip.decompress(path.read_bytes()))
   loc=ref['reference'];reference=GeoPoint(latitude=loc['latitude'],longitude=loc['longitude'])
   row.update(evaluate_camera_location(pose,reference))
   row.update(preferred_topk_hits={str(k):any(rank<=k for rank in row['containing_ranks']) for k in (3,5,10)},seconds=pose.elapsed_seconds,
      searched_points=sum(h.searched_points for h in pose.hypotheses),identity_hypotheses=len(pose.hypotheses),searched_hypotheses=sum(h.searched_points>0 for h in pose.hypotheses),
      reliable_landmarks=pose.regions[0].best_score.reliable_landmark_count if pose.regions else 0,
      preferred_area_m2=pose.preferred_area_m2,feasible_area_m2=pose.feasible_area_m2,
      vision_landmarks=len(vision.landmarks),reliable_vision=sum(o.coordinates_reliable for o in vision.landmarks),matched_objects=sum(bool(m['candidates']) for m in matching['matches']))
   sys=LocalCoordinateSystem(reference)
   row['feasible_contains_reference']=any(to_local_geometry(shape(r.geometry),sys).covers(Point(0,0)) for r in pose.feasible_regions)
   from geophotoloc.maps.names import is_specific_name
   row['named_visual_objects']=sum(o.coordinates_reliable and any(is_specific_name(n) for n in ([o.name] if not o.identity_uncertain else [])+o.name_candidates) for o in vision.landmarks)
   row['stage']=classify(row['vision_landmarks'],row['reliable_vision'],row['matched_objects'],pose)
   if row['matched_objects']<2 and row['named_visual_objects']<2:row['stage']='vision_insufficient_specific_identity_evidence'
   row['search_domain_contains_reference']=any(shape(h.search_geometry).covers(Point(reference.longitude,reference.latitude)) for h in pose.hypotheses if h.search_geometry)
   row['assigned_reliable_max']=max((sum(o.coordinates_reliable for o in vision.landmarks if o.id in h.assignments) for h in pose.hypotheses),default=0)
   if pose.regions and not row['search_domain_contains_reference']:row['stage']='reference_outside_assignment_distance_search_domains'
   elif pose.regions and row['top1_point_distance_m']>200:row['stage']='candidate_ranking_or_model_mismatch'
   row['diagnostic_radius_m']=200
   rows.append(row)
   if ref['split']!='holdout':
    audit=audit_existing_points(pose,reference,bounds)
    audits.append(dict(case=key,group=group,**audit,top1=pose.regions[0].model_dump(mode='json') if pose.regions else None))
 summary=[]
 for split in ('all_new','development','holdout','legacy_diagnostic'):
  for group in ('baseline','robust_only','identity_only','joint_full'):
   selected=[r for r in rows if (r['split']!='legacy_diagnostic' if split=='all_new' else r['split']==split) and r['group']==group];n=len(selected)
   summary.append(dict(split=split,group=group,total_samples=n,valid_distance_samples=sum(r['top1_point_distance_m'] is not None for r in selected),
    no_distance_samples=sum(r['top1_point_distance_m'] is None for r in selected),error_distribution=percentile_summary([r['top1_point_distance_m'] for r in selected]),
    preferred_topk={str(k):dict(hits=sum(r['preferred_topk_hits'][str(k)] for r in selected),denominator=n) for k in (3,5,10)},
    feasible_hits=sum(r.get('feasible_contains_reference',False) for r in selected),stage_counts=dict(Counter(r['stage'] for r in selected))))
 save(OUT/'post_evaluation/metrics.json',rows);save(OUT/'post_evaluation/summary.json',summary);save(OUT/'post_evaluation/point_diagnostics.json',audits)
 if (ROOT/'.cache/geophotoloc/maps.sqlite3').exists():save(OUT/'post_evaluation/detailed_score_audits.json',detailed_score_audits(audits))
 verify_manifest(OUT)
 print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
