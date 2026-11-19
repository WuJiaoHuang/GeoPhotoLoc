"""Independent post-inference evaluation. Camera references never enter F."""
import gzip,json
import numpy as np
from shapely.geometry import Point,shape
from geophotoloc.models import GeoPoint
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from geophotoloc.localization.projection import to_local_geometry
from geophotoloc.app.evaluation import evaluate_camera_location
from geophotoloc.app.order_comparison import compare_region_orders
from run_stage54 import ROOT,DATA,OUT,OLD,save,sha,read_pose


def main():
 manifest=json.loads((OUT/'inference_manifest.json').read_text(encoding='utf-8'))
 def verify():
  for name,digest in manifest['artifacts'].items():
   if sha(OUT/name)!=digest:raise ValueError('Inference changed')
 verify()
 refs=json.loads((DATA/'dataset_references.json').read_text(encoding='utf-8'))['samples']
 previous=json.loads((OLD/'evaluation/comparison.json').read_text(encoding='utf-8'))
 rows=[r for r in previous if r['algorithm'] in ('D','E')];ablation=[];changes=[];nearby=[]
 bounds={r['region_id']:r['bounds'] for r in json.loads((ROOT/'docs/evaluation/stage3/imports.json').read_text(encoding='utf-8'))}
 for ref in refs:
  key=ref['id'];base=dict(case=key,split=ref['split'],coordinate_quality='Q2 self-reported; accuracy unknown');path=OUT/'poses'/f'F_{key}.json.gz'
  if not path.exists():
   rows.append(dict(**base,algorithm='F',status='VISION_UNAVAILABLE',top1_point_distance_m=None,nearest_region_distance_m=None,topk={str(k):False for k in (3,5,10)},failure_stage='vision'))
   for s in ('A0','A1','A2'):ablation.append(dict(**base,stage=s,status='VISION_UNAVAILABLE',area_m2=None,reference_contains=None,nearest_region_distance_m=None))
   continue
  f=read_pose(path);e=read_pose(OLD/'poses'/f'E_{key}.json.gz');reference=GeoPoint(latitude=ref['reference']['latitude'],longitude=ref['reference']['longitude']);system=LocalCoordinateSystem(reference)
  result=evaluate_camera_location(f,reference);change=compare_region_orders(e,f);changes.append(dict(case=key,**change))
  values=[v for h in f.hypotheses for v in h.automatic_relation_audit.get('scores',[]) if v is not None]
  relations=[r for h in f.hypotheses for r in h.automatic_relation_audit.get('relations',[])]
  counts=dict(usable_visual_relations=sum(r['visual_weight']>0 for r in relations),determined_point_relations=sum(sum(r['determined']) for r in relations),
    min=min(values,default=None),max=max(values,default=None),mean=float(np.mean(values)) if values else None,p10=float(np.percentile(values,10)) if values else None,p90=float(np.percentile(values,90)) if values else None)
  matches=json.loads((DATA/'inputs'/f'{key}.matches.json').read_text(encoding='utf-8'))
  failure_stage=('map_matching' if not any(m['candidates'] for m in matches['matches']) else 'insufficient_independent_landmarks') if not any(h.searched_points for h in f.hypotheses) else 'physical_or_geometry_or_selection' if not result['containing_ranks'] else None
  rows.append(dict(**base,**result,algorithm='F',topk={str(k):any(rank<=k for rank in result['containing_ranks']) for k in (3,5,10)},
    preferred_area_m2=f.preferred_area_m2,feasible_area_m2=f.feasible_area_m2,output_regions=len(f.regions),region_areas_m2=[r.area_m2 for r in f.regions],
    relation_distribution=counts,region_relation_scores=[r.automatic_relation_score for r in f.regions],
    seconds=f.elapsed_seconds,points=sum(h.searched_points for h in f.hypotheses),changed_common_ranks=change['changed_common_ranks'],new_modes=change['new_modes'],dropped_modes=change['dropped_modes'],
    failure_stage=failure_stage))
  data=json.loads(gzip.decompress((OUT/'refinement'/f'{key}.json.gz').read_bytes()))
  for l in data['layers']:
   g=to_local_geometry(shape(l['geometry']),system)
   ablation.append(dict(**base,stage=l['stage'],status=f.status,area_m2=l['area_m2'],reference_contains=g.covers(Point(0,0)),nearest_region_distance_m=None if g.is_empty else g.distance(Point(0,0)),
    actual_points=l['actual_points'],passed_points=l['passed_points'],ranked=l['ranked'],relation_distribution=data['distribution'] if l['stage']=='A1' else None,
    topk={str(k):any(rank<=k for rank in result['containing_ranks']) for k in (3,5,10)} if l['stage']=='A2' else None))
  records=[]
  for h in f.hypotheses:
   a=h.automatic_relation_audit
   if not a.get('points'):continue
   b=bounds[h.region_id];local=LocalCoordinateSystem(GeoPoint(latitude=(b['south']+b['north'])/2,longitude=(b['west']+b['east'])/2));xy=np.array(local.to_local(reference));dist=np.linalg.norm(np.array(a['points'])-xy,axis=1);i=int(np.argmin(dist));p=a['points'][i]
   trace=next(t for t in h.sample_trace if (t['x'],t['y'])==tuple(p))
   records.append(dict(hypothesis_id=h.id,existing_xy=p,distance_m=float(dist[i]),relation_score=a['scores'][i],feasible=trace['feasible'],score=trace['score'],components=trace.get('components'),reasons=trace.get('reasons'),selection_stage=trace.get('selection_stage'),
     relations=[dict(left=r['left'],right=r['right'],weight=r['visual_weight'],consistency=r['consistency'][i],weighted=r['weighted_scores'][i],identity_evidence=r['identity_evidence'],reasons=r['reasons']) for r in a['relations']]))
  nearby.append(dict(case=key,existing_points=sorted(records,key=lambda r:r['distance_m'])))
 summary=[]
 for split in ('all_new','development','holdout','legacy_diagnostic'):
  for algorithm in ('D','E','F'):
   selected=[r for r in rows if r['algorithm']==algorithm and (r['split']!='legacy_diagnostic' if split=='all_new' else r['split']==split)]
   errors=[r['top1_point_distance_m'] for r in selected if r.get('top1_point_distance_m') is not None]
   summary.append(dict(split=split,algorithm=algorithm,total=len(selected),valid=len(errors),median_m=float(np.median(errors)) if errors else None,p90_m=float(np.percentile(errors,90)) if errors else None,
    topk={str(k):sum(r.get('topk',r.get('preferred_topk_hits',{})).get(str(k),False) for r in selected) for k in (3,5,10)}))
 save(OUT/'evaluation/comparison.json',rows);save(OUT/'evaluation/ablation.json',ablation);save(OUT/'evaluation/summary.json',summary);save(OUT/'evaluation/ranking_changes.json',changes);save(OUT/'evaluation/existing_points.json',nearby)
 verify();print(json.dumps([r for r in summary if r['split']=='all_new'],indent=2))

if __name__=='__main__':main()
