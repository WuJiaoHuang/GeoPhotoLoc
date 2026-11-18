"""One explicit 120s recovery pass for timeout-only failures; total budget stays 20."""
import json
from datetime import datetime,timezone
from pathlib import Path
import httpx
from openai import OpenAI
from geophotoloc.app.pipeline import LocalizationPipeline,PipelineFailure
from geophotoloc.config import VisionConfig
from geophotoloc.vision import VisionAnalyzer
from geophotoloc.maps import MapMatcher
from geophotoloc.localization import PoseSearchConfig
from run_camera_benchmark import OUT,ROOT,BUDGET,digest,save,dump_pose


def reserve_retry(ledger,key,sha):
 calls=[r for r in ledger if r['image_sha256']==sha]
 if len(ledger)>=BUDGET:raise ValueError('Global 20-request budget exhausted')
 if len(calls)!=1 or calls[0]['status']!='failed' or calls[0].get('code')!='API_TIMEOUT':raise ValueError('Only one timeout-only recovery per image permitted')
 row=dict(attempt=len(ledger)+1,sample_id=key,image_sha256=sha,status='started',retry_of=calls[0]['attempt'],
          started_at_utc=datetime.now(timezone.utc).isoformat(),sdk_max_retries=0,actual_cost=None,cost_note='Charge unavailable, timeout may still be billed')
 ledger.append(row);return row


def main():
 # First pass must be complete; never run concurrently with the first runner.
 if not (OUT/'inference_manifest.json').exists():raise ValueError('First pass incomplete')
 manifest=json.loads((OUT/'inference_manifest.json').read_text(encoding='utf-8'))
 backup=OUT/'first_pass_inference_manifest.json'
 if not backup.exists():save(backup,manifest)
 ledger_path=OUT/'api_requests.json';ledger=json.loads(ledger_path.read_text(encoding='utf-8'))
 samples=json.loads((OUT/'inference_inputs.json').read_text(encoding='utf-8'))
 config=VisionConfig.from_env().model_copy(update={'timeout':120.,'max_retries':0})
 if config.model!='qwen3.8-flash' or config.base_url.rstrip('/')!='https://dashscope.aliyuncs.com/compatible-mode/v1':raise ValueError('Unauthorized model/endpoint')
 search=PoseSearchConfig(**json.loads((OUT/'frozen_configs.json').read_text(encoding='utf-8'))['joint_full'])
 db=ROOT/'.cache/geophotoloc/maps.sqlite3'
 if digest(db)!=json.loads((OUT/'map_snapshot.json').read_text())['sha256']:raise ValueError('Map changed')
 original_env=digest(ROOT/'.env')
 for sample in samples:
  if len(ledger)>=BUDGET:break
  key=sample['id'];base=OUT/'inputs'/key;vp=base.with_suffix('.vision.json');mp=base.with_suffix('.matches.json')
  if vp.exists():continue
  calls=[r for r in ledger if r['image_sha256']==sample['image_sha256']]
  if len(calls)!=1 or calls[0].get('code')!='API_TIMEOUT':continue
  row=None
  def hook(request):
   nonlocal row
   row=reserve_retry(ledger,key,sample['image_sha256']);row.update(model=config.model,timeout_seconds=config.timeout);save(ledger_path,ledger)
  class Recorder(VisionAnalyzer):
   def _request(self,client,prepared):
    response=super()._request(client,prepared);save(OUT/'raw_responses'/f'{key}.json',response.model_dump(mode='json'))
    row.update(usage=response.usage.model_dump(mode='json') if response.usage else None,api_response_at_utc=datetime.now(timezone.utc).isoformat());save(ledger_path,ledger)
    return response
   def analyze_prepared(self,prepared):
    result=super().analyze_prepared(prepared);save(vp,result.model_dump(mode='json'));return result
  class RecorderMatcher(MapMatcher):
   def match(self,vision):
    result=super().match(vision);save(mp,result.model_dump(mode='json'));return result
  try:
   with httpx.Client(event_hooks={'request':[hook]}) as transport:
    with OpenAI(api_key=config.api_key.get_secret_value(),base_url=config.base_url,timeout=config.timeout,max_retries=0,http_client=transport) as client:
     pipeline=LocalizationPipeline(db,vision_config=config,analyzer=Recorder(config,client),search_config=search,matcher_factory=RecorderMatcher)
     result=pipeline.run(OUT/sample['file']);dump_pose(OUT/'poses'/f'joint_full_{key}.json.gz',result.localization)
   row.update(status='success')
  except PipelineFailure as error:
   if row is not None:row.update(status='vision_success_pipeline_failed' if vp.exists() else 'failed',stage=error.stage,code=error.code)
  finally:
   if row is not None:row.update(finished_at_utc=datetime.now(timezone.utc).isoformat());save(ledger_path,ledger)
   assert digest(ROOT/'.env')==original_env
  print(key,row['status'] if row else 'not_requested',len(ledger),'of',BUDGET,flush=True)
 save(OUT/'recovery_pass.json',dict(total_requests=len(ledger),request_budget=BUDGET,timeout_seconds=120,policy='One explicit timeout-only retry, original frozen order, no successful-image repeat, no geometry/identity parameter change',runner_sha256=digest(Path(__file__))))

if __name__=='__main__':main()
