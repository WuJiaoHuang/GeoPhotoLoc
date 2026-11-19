"""One frozen formal inference round. No camera references or external requests."""
import gzip,json,hashlib,time
from pathlib import Path
from run_stage52 import ROOT,DATA,sha,save,read_pose
from geophotoloc.models import VisionExtractionResult,MapMatchingResult
from geophotoloc.models.maps import GeoBounds
from geophotoloc.maps import LandmarkStore
from geophotoloc.localization.spatial_refinement import build_reliable_spatial_refinement

OUT=ROOT/'docs/evaluation/stage5_3';OLD=ROOT/'docs/evaluation/stage5_2'

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if (OUT/'inference_manifest.json').exists():raise ValueError('Formal round already frozen; evaluate existing outputs, never silently rerun')
 for base in (DATA,OLD):
  manifest=json.loads((base/'inference_manifest.json').read_text(encoding='utf-8'))
  for name,digest in manifest['artifacts'].items():
   if sha(base/name)!=digest:raise ValueError('Historical evidence changed')
 db=ROOT/'.cache/geophotoloc/maps.sqlite3'
 if sha(db)!=json.loads((DATA/'map_snapshot.json').read_text())['sha256']:raise ValueError('Map snapshot differs')
 sources=[ROOT/'src/geophotoloc/localization'/n for n in ('relation_reliability.py','refinement_reliable.py','spatial_refinement.py')]+[ROOT/'src/geophotoloc/models/refinement.py']
 rules=dict(version='5.3',source_sha256={str(p.relative_to(ROOT)):sha(p) for p in sources},
   evidence_policy='No independent identity/full silhouette confirmations in frozen inputs; conservative defaults only',
   angular_tolerance='Reuse pose.config.angular_tolerance_deg',image_tolerance='Reuse pose.config.x_tolerance',
   soft_rule={'satisfied':1.,'indeterminate':.5,'conflict':0.,'no_soft':None},new_api_budget=0)
 rule_path=OUT/'rules_frozen_before_inference.json'
 if rule_path.exists() and json.loads(rule_path.read_text(encoding='utf-8'))!=rules:raise ValueError('Frozen rules changed; stop')
 save(rule_path,rules);checks=[];started=time.perf_counter()
 with LandmarkStore(db) as store:
  bounds={r:GeoBounds.model_validate_json(store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(r,)).fetchone()[0]) for r in store.coverage_regions()}
  for sample in json.loads((DATA/'inference_inputs.json').read_text(encoding='utf-8')):
   key=sample['id'];vp=DATA/'inputs'/f'{key}.vision.json'
   if not vp.exists():checks.append(dict(case=key,status='VISION_UNAVAILABLE',reason='Historical failed request; no retry'));continue
   v=VisionExtractionResult.model_validate_json(vp.read_bytes());m=MapMatchingResult.model_validate_json((DATA/'inputs'/f'{key}.matches.json').read_bytes())
   p=read_pose(OLD/'poses'/f'E_{key}.json.gz');old=json.loads(gzip.decompress((OLD/'refinement'/f'{key}.json.gz').read_bytes()))
   target=OUT/'refinement'/f'{key}.json.gz';target.parent.mkdir(exist_ok=True)
   if target.exists():raise ValueError('Partial output exists: investigate before resuming, never overwrite')
   new=build_reliable_spatial_refinement(v,m,p,bounds,old)
   target.write_bytes(gzip.compress(json.dumps(new,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode(),compresslevel=9,mtime=0))
   for l in old['layers']:assert next(x for x in new['layers'] if x['stage']==l['stage'])==l
   checks.append(dict(case=key,status=p.status,grid_fingerprint=new['grid_fingerprint'],historical_layers_equal=True,seconds=new['elapsed_seconds'],source_pose_sha256=sha(OLD/'poses'/f'E_{key}.json.gz')))
   print(key,round(new['elapsed_seconds'],3),flush=True)
 save(OUT/'inference_checks.json',checks)
 files=[p for p in OUT.rglob('*') if p.is_file()]
 save(OUT/'inference_manifest.json',dict(artifacts={str(p.relative_to(OUT)):sha(p) for p in files},historical_manifest_sha256=sha(OLD/'inference_manifest.json'),map_sha256=sha(db),total_seconds=time.perf_counter()-started,new_api_requests=0))

if __name__=='__main__':main()
