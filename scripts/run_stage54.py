"""One formal F round on frozen vision/maps; never reads camera references."""
import gzip,json,time,hashlib
from run_stage52 import ROOT,DATA,sha,save,read_pose,trace_signature
from geophotoloc.maps import LandmarkStore
from geophotoloc.models import VisionExtractionResult,MapMatchingResult
from geophotoloc.models.maps import GeoBounds
from geophotoloc.localization import Stage54PoseSolver
from geophotoloc.localization.automatic_refinement import build_automatic_refinement

OUT=ROOT/'docs/evaluation/stage5_4';OLD=ROOT/'docs/evaluation/stage5_2'

def dump(path,data):
 path.parent.mkdir(parents=True,exist_ok=True)
 body=data.model_dump_json() if hasattr(data,'model_dump_json') else json.dumps(data,ensure_ascii=False,allow_nan=False,separators=(',',':'))
 path.write_bytes(gzip.compress(body.encode(),compresslevel=9,mtime=0))

def main():
 OUT.mkdir(parents=True,exist_ok=True)
 if (OUT/'inference_manifest.json').exists():raise ValueError('Formal round already frozen; do not overwrite')
 for base in (DATA,OLD):
  for name,digest in json.loads((base/'inference_manifest.json').read_text(encoding='utf-8'))['artifacts'].items():
   if sha(base/name)!=digest:raise ValueError('Historical evidence modified')
 db=ROOT/'.cache/geophotoloc/maps.sqlite3'
 if sha(db)!=json.loads((DATA/'map_snapshot.json').read_text())['sha256']:raise ValueError('Map snapshot differs')
 sources=list((ROOT/'src/geophotoloc/localization').glob('*.py'))+[ROOT/'src/geophotoloc/models/pose.py']
 rules=dict(version='5.4',source_sha256_lf={str(p.relative_to(ROOT)):hashlib.sha256(p.read_text(encoding='utf-8').encode()).hexdigest() for p in sources},
  visual='s=max(0,xb-xa-x_tolerance); no bbox w=.5*s; bbox g=max(0,bxmin-axmax-x_tolerance); W=max(widths,x_tolerance); w=(g+.5*s)/(W+g+.5*s)',
  neutral=.5,quality='round(score,6),round(geometry,6),round(relation_or_neutral,6),independent reliable count, E diversity/stable coordinates',
  generation='Original E tile cells, score window, exact bounded merge; relation affects only retention/ranking',new_api_budget=0)
 rp=OUT/'rules_frozen_before_inference.json'
 if rp.exists() and json.loads(rp.read_text(encoding='utf-8'))!=rules:raise ValueError('Frozen rules changed')
 save(rp,rules);checks=[]
 with LandmarkStore(db) as store:
  bounds={r:GeoBounds.model_validate_json(store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(r,)).fetchone()[0]) for r in store.coverage_regions()}
  for sample in json.loads((DATA/'inference_inputs.json').read_text(encoding='utf-8')):
   key=sample['id'];vp=DATA/'inputs'/f'{key}.vision.json'
   if not vp.exists():checks.append(dict(case=key,status='VISION_UNAVAILABLE',reason='Historical API failure, not retried'));continue
   target=OUT/'poses'/f'F_{key}.json.gz'
   if target.exists():raise ValueError('Partial output exists; do not overwrite')
   v=VisionExtractionResult.model_validate_json(vp.read_bytes());m=MapMatchingResult.model_validate_json((DATA/'inputs'/f'{key}.matches.json').read_bytes())
   e=read_pose(OLD/'poses'/f'E_{key}.json.gz')
   guard_cache=ROOT/'.cache'/f'stage54_guard_{key}.json.gz'
   # Reuse the reference-free guard output after JSON tuple/list normalization.
   f=read_pose(guard_cache) if guard_cache.exists() else Stage54PoseSolver(store,e.config).solve(v,m)
   ec=e.config.model_dump();fc=f.config.model_dump();ec.pop('selection_strategy');fc.pop('selection_strategy')
   same_physical=[r.model_dump(mode='json') for r in e.feasible_regions]==[r.model_dump(mode='json') for r in f.feasible_regions]
   if ec!=fc or trace_signature(e)!=trace_signature(f) or not same_physical:
    dump(ROOT/'.cache'/f'stage54_guard_{key}.json.gz',f)
    print(dict(config_differences={k:[ec[k],fc[k]] for k in ec if ec[k]!=fc[k]},same_trace=trace_signature(e)==trace_signature(f),same_physical=e.feasible_regions==f.feasible_regions),flush=True)
    raise ValueError('Frozen E/F config, grid, geometry scores or physical domain differ: '+key)
   dump(target,f)
   old=json.loads(gzip.decompress((OLD/'refinement'/f'{key}.json.gz').read_bytes()))
   a=build_automatic_refinement(v,m,f,bounds,old['layers'][0]);dump(OUT/'refinement'/f'{key}.json.gz',a)
   checks.append(dict(case=key,status=f.status,same_grid_scores_and_physical=True,trace_sha256=trace_signature(f),E_seconds=e.elapsed_seconds,F_seconds=f.elapsed_seconds,F_regions=len(f.regions),source_E_sha256=sha(OLD/'poses'/f'E_{key}.json.gz')))
   print(key,round(f.elapsed_seconds,3),flush=True)
 save(OUT/'inference_checks.json',checks)
 files=[p for p in OUT.rglob('*') if p.is_file()]
 save(OUT/'inference_manifest.json',dict(artifacts={str(p.relative_to(OUT)):sha(p) for p in files},historical_manifest_sha256=sha(OLD/'inference_manifest.json'),map_sha256=sha(db),new_api_requests=0))

if __name__=='__main__':main()
