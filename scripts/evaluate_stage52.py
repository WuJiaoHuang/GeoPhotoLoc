"""Independent post-solve E and S0/S1/S2 evaluation; cannot search or rerank."""
import gzip,json
from pathlib import Path
from collections import Counter
import numpy as np
from shapely.geometry import Point,shape
from geophotoloc.models import GeoPoint
from geophotoloc.app.evaluation import evaluate_camera_location
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from geophotoloc.localization.projection import to_local_geometry
from run_stage52 import ROOT,DATA,OUT,sha,save,read_pose


def main():
 manifest=json.loads((OUT/'inference_manifest.json').read_text(encoding='utf-8'))
 def verify():
  for name,digest in manifest['artifacts'].items():
   if sha(OUT/name)!=digest:raise ValueError('Stage52 inference modified')
  for name,digest in manifest['historical_artifacts'].items():
   if sha(DATA/name)!=digest:raise ValueError('Historical artifacts modified')
 verify()
 inputs=json.loads((DATA/'inference_inputs.json').read_text(encoding='utf-8'))
 for x in inputs:
  if (DATA/'inputs'/f"{x['id']}.vision.json").exists():
   for prefix in ('poses/E_','refinement/'):
    name=f"{prefix}{x['id']}.json.gz"
    if name not in {k.replace('\\','/') for k in manifest['artifacts']}:raise ValueError('Incomplete independent inference')
 # Only now read camera positions; this module imports no Solver or sampler.
 refs=json.loads((DATA/'dataset_references.json').read_text(encoding='utf-8'))['samples']
 previous=json.loads((DATA/'post_evaluation/metrics.json').read_text(encoding='utf-8'))
 names=dict(baseline='A',robust_only='B',identity_only='C',joint_full='D')
 comparison=[dict(**r,algorithm=names[r['group']]) for r in previous]
 refinement_rows=[];point_records=[]
 for ref in refs:
  key=ref['id'];base=dict(case=key,split=ref['split'],coordinate_quality='Q2 self reported; unknown accuracy')
  pose_path=OUT/'poses'/f'E_{key}.json.gz'
  if not pose_path.exists():
   comparison.append(dict(**base,algorithm='E',status='VISION_UNAVAILABLE',top1_point_distance_m=None,nearest_region_distance_m=None,topk={str(k):False for k in (3,5,10)}))
   for stage in ('S0','S1','S2'):refinement_rows.append(dict(**base,stage=stage,status='VISION_UNAVAILABLE',area_m2=None,reference_contains=None,nearest_region_distance_m=None,topk=None))
   continue
  reference=GeoPoint(latitude=ref['reference']['latitude'],longitude=ref['reference']['longitude']);system=LocalCoordinateSystem(reference)
  pose=read_pose(pose_path);evaluated=evaluate_camera_location(pose,reference)
  audits=[d for h in pose.hypotheses for d in h.selection_audit.get('decisions',[])]
  top_quality=max((tuple(d['quality']) for d in audits),default=None)
  d_row=next(r for r in previous if r['case']==key and r['group']=='joint_full')
  comparison.append(dict(**base,**evaluated,algorithm='E',topk={str(k):any(rank<=k for rank in evaluated['containing_ranks']) for k in (3,5,10)},
    seconds=pose.elapsed_seconds,points=sum(h.searched_points for h in pose.hypotheses),output_regions=len(pose.regions),
    preferred_area_m2=pose.preferred_area_m2,region_areas_m2=[r.area_m2 for r in pose.regions],feasible_area_m2=pose.feasible_area_m2,
    feasible_contains_reference=d_row.get('feasible_contains_reference'),feasible_note='Exact D/E physical geometry equality verified; same historical coverage evaluator',
    globally_top_quality_omitted=sum(not d['retained'] and tuple(d['quality'])==top_quality and d['reason']!='covered_by_retained_mode' for d in audits),
    per_hypothesis_top_quality_omitted=sum(h.selection_audit.get('omitted_top_quality_modes',0) for h in pose.hypotheses),
    selection_counts=dict(Counter(d['reason'] for d in audits))))
  data=json.loads(gzip.decompress((OUT/'refinement'/f'{key}.json.gz').read_bytes()))
  for layer in data['layers']:
   geom=to_local_geometry(shape(layer['geometry']),system)
   ranks=[r['rank'] for r in data['ranked_regions'] if shape(r['geometry']).covers(Point(reference.longitude,reference.latitude))] if layer['ranked'] else None
   refinement_rows.append(dict(**base,stage=layer['stage'],status=pose.status,area_m2=layer['area_m2'],
     reduction_from_previous=layer['reduction_from_previous'],reference_contains=geom.covers(Point(0,0)),nearest_region_distance_m=geom.distance(Point(0,0)) if not geom.is_empty else None,
     actual_points=layer['actual_points'],passed_points=layer['passed_points'],reliable_landmarks=layer['reliable_landmarks'],reliable_relations=layer['reliable_relations'],
     topk={str(k):any(rank<=k for rank in ranks) for k in (3,5,10)} if ranks is not None else None,
     phase_seconds=layer['seconds'],E_solve_seconds=pose.elapsed_seconds if layer['stage']=='S2' else None,ablation_seconds=data['elapsed_seconds'],
     cost_note='Fixed E-generated population; phase seconds reuse cached full-geometry scores, not end-to-end latency',
     per_hypothesis_relation_reductions=[dict(hypothesis_id=h['id'],relations=len(h['relations']['relations']),S0=h['areas_m2']['S0'],S1=h['areas_m2']['S1']) for h in data['hypotheses']] if layer['stage']=='S1' else None))
  # Existing point evidence only, no new proposals or re-scoring at reference.
  if ref['split']!='holdout':
   bounds=json.loads((ROOT/'docs/evaluation/stage3/imports.json').read_text(encoding='utf-8'))
   from diagnose_camera_benchmark import audit_existing_points
   point_records.append(dict(**base,**audit_existing_points(pose,reference,{b['region_id']:b['bounds'] for b in bounds})))
 summary=[]
 for partition in ('all_new','development','holdout','legacy_diagnostic'):
  for algo in ('A','B','C','D','E'):
   rows=[r for r in comparison if r['algorithm']==algo and (r['split']!='legacy_diagnostic' if partition=='all_new' else r['split']==partition)]
   errors=[r['top1_point_distance_m'] for r in rows if r.get('top1_point_distance_m') is not None]
   def hit(r,k):return r.get('topk',r.get('preferred_topk_hits',{})).get(str(k),False)
   summary.append(dict(partition=partition,algorithm=algo,total=len(rows),valid=len(errors),missing=len(rows)-len(errors),
    median_m=float(np.median(errors)) if errors else None,p90_m=float(np.percentile(errors,90)) if errors else None,
    topk={str(k):dict(hits=sum(hit(r,k) for r in rows),denominator=len(rows)) for k in (3,5,10)}))
 save(OUT/'evaluation/comparison.json',comparison);save(OUT/'evaluation/refinement.json',refinement_rows)
 save(OUT/'evaluation/summary.json',summary);save(OUT/'evaluation/E_point_diagnostics.json',point_records)
 verify()
 print(json.dumps([r for r in summary if r['partition']=='all_new'],ensure_ascii=False,indent=2))

if __name__=='__main__':main()
