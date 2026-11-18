"""Truth-free cached Pipeline -> A/B/C/D evaluation; live vision requires --live."""
import argparse, gzip, hashlib, json, platform, sys
from datetime import datetime, timezone
from pathlib import Path
import httpx
from openai import OpenAI
from geophotoloc.app.pipeline import LocalizationPipeline, PipelineFailure
from geophotoloc.config import VisionConfig
from geophotoloc.vision import VisionAnalyzer
from geophotoloc.maps import LandmarkStore, MapMatcher
from geophotoloc.localization import PoseSolver
from geophotoloc.models import VisionExtractionResult
from geophotoloc.models.maps import MapMatchingResult
from evaluate_stage5_1b import configurations, summarize

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evaluation/real_camera_diagnostics'
BUDGET=20

def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def save(path,value):
 path.parent.mkdir(parents=True,exist_ok=True)
 tmp=path.with_suffix(path.suffix+'.tmp')
 tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(path)

def reserve_request(ledger,sample_id,image_sha):
 if len(ledger)>=BUDGET:raise ValueError('Total HTTP request budget exhausted')
 if any(r['image_sha256']==image_sha for r in ledger):raise ValueError('Image already attempted; no automatic retry')
 row=dict(attempt=len(ledger)+1,sample_id=sample_id,image_sha256=image_sha,status='started',
          started_at_utc=datetime.now(timezone.utc).isoformat(),sdk_max_retries=0,actual_cost=None,cost_note='Actual charge unavailable; token usage is not an invoice')
 ledger.append(row);return row

def load_input(sample):
 base=OUT/'inputs'/sample['id']
 return (VisionExtractionResult.model_validate_json(base.with_suffix('.vision.json').read_bytes()),
         MapMatchingResult.model_validate_json(base.with_suffix('.matches.json').read_bytes()))

def dump_pose(path,result):
 path.parent.mkdir(parents=True,exist_ok=True)
 path.write_bytes(gzip.compress((result.model_dump_json()+'\n').encode(),compresslevel=9,mtime=0))

def main(argv=None):
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--case',action='append');args=parser.parse_args(argv)
 samples=json.loads((OUT/'inference_inputs.json').read_text(encoding='utf-8'))
 configs={k:v.model_copy(update={'record_diagnostic_trace':True}) for k,v in configurations().items()}
 config_dump={k:v.model_dump(mode='json') for k,v in configs.items()}
 config_file=OUT/'frozen_configs.json'
 if config_file.exists() and json.loads(config_file.read_text(encoding='utf-8'))!=config_dump:raise ValueError('Frozen configuration changed')
 save(config_file,config_dump)
 ledger_path=OUT/'api_requests.json';ledger=json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else []
 original_env=digest(ROOT/'.env') if (ROOT/'.env').exists() else None
 db=ROOT/'.cache/geophotoloc/maps.sqlite3'
 db_sha=digest(db);db_file=OUT/'map_snapshot.json'
 if db_file.exists() and json.loads(db_file.read_text())['sha256']!=db_sha:raise ValueError('Frozen map snapshot changed')
 with LandmarkStore(db) as store:
  save(db_file,dict(sha256=db_sha,bytes=db.stat().st_size,coverage=store.coverage_regions(),note='Existing bounded OSM snapshot; no network imports; geographic labels are never supplied to matcher'))
 outcomes=[]
 for sample in samples:
  if args.case and sample['id'] not in args.case:continue
  key=sample['id'];image=OUT/sample['file'];sha=digest(image)
  if sha!=sample['image_sha256']:raise ValueError('Image modified after freeze')
  base=OUT/'inputs'/key;vp=base.with_suffix('.vision.json');mp=base.with_suffix('.matches.json')
  try:
   if not vp.exists():
    if not args.live:outcomes.append(dict(case=key,status='vision_not_cached'));continue
    if any(r['image_sha256']==sha for r in ledger):outcomes.append(dict(case=key,status='vision_previous_failure_no_retry'));continue
    config=VisionConfig.from_env()
    if config.model!='qwen3.8-flash' or config.base_url.rstrip('/')!='https://dashscope.aliyuncs.com/compatible-mode/v1':raise ValueError('Unauthorized model or endpoint')
    row=None
    def on_request(request):
     nonlocal row
     row=reserve_request(ledger,key,sha);row.update(model=config.model,timeout_seconds=config.timeout);save(ledger_path,ledger)
    class Recorder(VisionAnalyzer):
     def _request(self,client,prepared):
      response=super()._request(client,prepared)
      save(OUT/'raw_responses'/f'{key}.json',response.model_dump(mode='json'))
      if row is not None:row.update(usage=response.usage.model_dump(mode='json') if response.usage else None)
      return response
     def analyze_prepared(self,prepared):
      result=super().analyze_prepared(prepared);save(vp,result.model_dump(mode='json'));return result
    class RecorderMatcher(MapMatcher):
     def match(self,vision):
      result=super().match(vision);save(mp,result.model_dump(mode='json'));return result
    try:
     with httpx.Client(event_hooks={'request':[on_request]}) as transport:
      with OpenAI(api_key=config.api_key.get_secret_value(),base_url=config.base_url,timeout=config.timeout,max_retries=0,http_client=transport) as client:
       pipeline=LocalizationPipeline(db,vision_config=config,analyzer=Recorder(config,client),search_config=configs['joint_full'],matcher_factory=RecorderMatcher)
       result=pipeline.run(image)
       dump_pose(OUT/'poses'/f'joint_full_{key}.json.gz',result.localization)
     row.update(status='success')
    except PipelineFailure as error:
     if row is not None:row.update(status='vision_success_pipeline_failed' if vp.exists() else 'failed',stage=error.stage,code=error.code)
    finally:
     if row is not None:row.update(finished_at_utc=datetime.now(timezone.utc).isoformat());save(ledger_path,ledger)
   if not vp.exists():outcomes.append(dict(case=key,status='vision_failed'));continue
   vision=VisionExtractionResult.model_validate_json(vp.read_bytes())
   if not mp.exists():
    with LandmarkStore(db) as store:save(mp,MapMatcher(store).match(vision).model_dump(mode='json'))
   vision,matching=load_input(sample)
   hashes=dict(vision=digest(vp),matching=digest(mp))
   with LandmarkStore(db) as store:
    for group,config in configs.items():
     path=OUT/'poses'/f'{group}_{key}.json.gz';summary=OUT/'summaries'/f'{group}_{key}.json'
     if path.exists():
      from geophotoloc.models.pose import PoseLocalizationResult
      result=PoseLocalizationResult.model_validate_json(gzip.decompress(path.read_bytes()))
      if result.config!=config:raise ValueError('Cached configuration mismatch')
     else:
      result=PoseSolver(store,config).solve(vision,matching);dump_pose(path,result)
     save(summary,dict(group=group,**summarize(key,result,hashes)))
     print(json.dumps(dict(case=key,group=group,status=result.status,seconds=result.elapsed_seconds,regions=len(result.regions)),ensure_ascii=False),flush=True)
   outcomes.append(dict(case=key,status='completed',vision_landmarks=len(vision.landmarks),matched_objects=sum(bool(m.candidates) for m in matching.matches)))
  finally:
   assert (digest(ROOT/'.env') if (ROOT/'.env').exists() else None)==original_env
   save(OUT/'run_outcomes.json',outcomes)
 artifacts=list((OUT/'poses').glob('*.json.gz'))+list((OUT/'summaries').glob('*.json'))+list((OUT/'inputs').glob('*.json'))+[config_file,OUT/'inference_inputs.json',db_file]
 sources=list((ROOT/'src/geophotoloc/localization').glob('*.py'))+[ROOT/'src/geophotoloc/models/pose.py',Path(__file__).resolve()]
 save(OUT/'inference_manifest.json',dict(artifacts={str(p.relative_to(OUT)):digest(p) for p in sorted(artifacts)},source_sha256={str(p.relative_to(ROOT)):digest(p) for p in sources},python=sys.version,platform=platform.platform()))

if __name__=='__main__':main()
