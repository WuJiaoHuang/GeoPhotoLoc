"""Read references only after all inference hashes are frozen; never rescore."""
import gzip,json
from collections import Counter
import numpy as np
from shapely.geometry import Point,shape
from geophotoloc.models import GeoPoint
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from geophotoloc.localization.projection import to_local_geometry
from run_stage53 import ROOT,DATA,OUT,OLD,sha,save,read_pose


def main():
 manifest=json.loads((OUT/'inference_manifest.json').read_text(encoding='utf-8'))
 def verify():
  for name,digest in manifest['artifacts'].items():
   if sha(OUT/name)!=digest:raise ValueError('Frozen inference changed')
  if sha(OLD/'inference_manifest.json')!=manifest['historical_manifest_sha256']:raise ValueError('History changed')
 verify()
 refs=json.loads((DATA/'dataset_references.json').read_text(encoding='utf-8'))['samples']
 oldmetrics=json.loads((OLD/'evaluation/refinement.json').read_text(encoding='utf-8'))
 bounds={r['region_id']:r['bounds'] for r in json.loads((ROOT/'docs/evaluation/stage3/imports.json').read_text(encoding='utf-8'))}
 rows=[];diagnostics=[]
 for ref in refs:
  key=ref['id'];path=OUT/'refinement'/f'{key}.json.gz';base=dict(case=key,split=ref['split'],coordinate_quality='Q2 author reported, accuracy unknown')
  if not path.exists():
   for stage in ('S0','S1','S1-R','S2','S2-R'):rows.append(dict(**base,stage=stage,status='VISION_UNAVAILABLE',area_m2=None,reference_contains=None,nearest_region_distance_m=None,reason='Historical API failure; not retried'))
   continue
  result=json.loads(gzip.decompress(path.read_bytes()));reference=GeoPoint(latitude=ref['reference']['latitude'],longitude=ref['reference']['longitude']);system=LocalCoordinateSystem(reference)
  s0=next(l['area_m2'] for l in result['layers'] if l['stage']=='S0')
  score_values=[s for h in result['hypotheses'] for s in h['relations']['soft_scores'] if s is not None]
  hist=Counter(round(s,6) for s in score_values)
  soft=dict(count=len(score_values),null_count=sum(s is None for h in result['hypotheses'] for s in h['relations']['soft_scores']),
    min=min(score_values,default=None),max=max(score_values,default=None),mean=float(np.mean(score_values)) if score_values else None,histogram={str(k):v for k,v in sorted(hist.items())})
  classes=Counter();point_counts=Counter();distinct={k:set() for k in ('HARD','SOFT','UNKNOWN')}
  for h in result['hypotheses']:
   audit=h['relations']
   for r in audit['relations']:
    classes.update(r['counts'])
    for c in distinct:
     if r['counts'][c]:distinct[c].add((r['left'],r['right']))
   for label,field in [('hard_satisfied','hard_satisfied'),('hard_conflicts','hard_conflicts'),('hard_indeterminate','hard_indeterminate')]:point_counts[label]+=sum(n>0 for n in audit[field])
  for l in result['layers']:
   stage=l['stage'];g=to_local_geometry(shape(l['geometry']),system)
   historical=next((r for r in oldmetrics if r['case']==key and r['stage']==stage),{})
   from geophotoloc.localization.regions import components
   ranks=[r['rank'] for r in result['ranked_regions'] if r.get('stage')=='S2-R' and shape(r['geometry']).covers(Point(reference.longitude,reference.latitude))] if stage=='S2-R' else None
   row=dict(**base,stage=stage,status='OK' if l['actual_points'] else 'INSUFFICIENT_EVIDENCE',area_m2=l['area_m2'],reduction_from_s0=None if not s0 else 1-l['area_m2']/s0,
      reference_contains=g.covers(Point(0,0)),nearest_region_distance_m=None if g.is_empty else g.distance(Point(0,0)),actual_points=l['actual_points'],passed_points=l['passed_points'],
      region_count=len(components(shape(l['geometry']))),ranked_region_count=sum(r.get('stage')=='S2-R' for r in result['ranked_regions']) if stage=='S2-R' else (len([r for r in result['ranked_regions'] if 'stage' not in r]) if stage=='S2' else None),
      phase_seconds=l['seconds'],construction_seconds=result['elapsed_seconds'],relation_point_counts={k:classes[k] for k in ('HARD','SOFT','UNKNOWN')} if stage in ('S1-R','S2-R') else None,
      distinct_relations_by_class={k:len(v) for k,v in distinct.items()} if stage in ('S1-R','S2-R') else None,
      hard_point_counts={k:point_counts[k] for k in ('hard_satisfied','hard_conflicts','hard_indeterminate')} if stage in ('S1-R','S2-R') else None,soft_scores=soft if stage in ('S1-R','S2-R') else None,
      topk={str(k):any(rank<=k for rank in ranks) for k in (3,5,10)} if ranks is not None else historical.get('topk'),
      reason=None if l['actual_points'] else 'No eligible shared multi-landmark grid; no manufactured location')
   if historical:
    assert row['area_m2']==historical['area_m2'] and row['reference_contains']==historical['reference_contains']
   rows.append(row)
  pose=read_pose(OLD/'poses'/f'E_{key}.json.gz');hlookup={h.id:h for h in pose.hypotheses}
  nearby=[]
  for h in result['hypotheses']:
   if not h['points']:continue
   ph=hlookup[h['id']];b=bounds[ph.region_id];local=LocalCoordinateSystem(GeoPoint(latitude=(b['south']+b['north'])/2,longitude=(b['west']+b['east'])/2));xy=np.array(local.to_local(reference))
   distances=np.linalg.norm(np.array(h['points'])-xy,axis=1);i=int(np.argmin(distances));p=h['points'][i];trace=next(t for t in ph.sample_trace if (t['x'],t['y'])==tuple(p))
   nearby.append(dict(hypothesis_id=h['id'],distance_m=float(distances[i]),point=p,feasible=trace['feasible'],score=trace['score'],components=trace.get('components'),reasons=trace.get('reasons'),
     soft_score=h['relations']['soft_scores'][i],hard_conflicts=h['relations']['hard_conflicts'][i],classifications=[dict(left=r['left'],right=r['right'],classification=r['classes'][i],order=r['orders'][i],reasons=r['reasons']) for r in h['relations']['relations']]))
  diagnostics.append(dict(case=key,nearest_existing_points=sorted(nearby,key=lambda x:x['distance_m'])))
 save(OUT/'evaluation/metrics.json',rows);save(OUT/'evaluation/point_diagnostics.json',diagnostics)
 summary=[]
 for stage in ('S0','S1','S1-R','S2','S2-R'):
  eligible=[r for r in rows if r['stage']==stage and r['split']!='legacy_diagnostic'];nonempty=[r for r in eligible if r.get('actual_points',0)>0]
  summary.append(dict(stage=stage,total=len(eligible),nonempty=len(nonempty),covered=sum(r['reference_contains'] for r in nonempty),median_area_m2=float(np.median([r['area_m2'] for r in nonempty])) if nonempty else None))
 save(OUT/'evaluation/summary.json',summary);verify();print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
