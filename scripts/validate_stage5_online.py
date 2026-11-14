"""Explicit live test, maximum two HTTP attempts, same authorized model only.

Does not read camera_truth.json. Post-solve metrics are a separate script.
"""
import json
from datetime import datetime,timezone
from pathlib import Path
import httpx
from openai import OpenAI
from geophotoloc.config import VisionConfig
from geophotoloc.vision import VisionAnalyzer
from geophotoloc.app.pipeline import LocalizationPipeline,PipelineFailure
from geophotoloc.app.visualization import download_payloads,build_map

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/evaluation/stage5'


def main():
    config=VisionConfig.from_env()
    if config.model!='qwen3.8-flash' or config.base_url.rstrip('/')!='https://dashscope.aliyuncs.com/compatible-mode/v1':
        raise ValueError('No live test sent: configured model/endpoint differs from authorization')
    config=config.model_copy(update={'timeout':180,'max_retries':0})
    ledger_path=DATA/'live_requests.json'
    ledger=json.loads(ledger_path.read_text(encoding='utf-8')) if ledger_path.exists() else []
    if (DATA/'north_bund_pipeline.json').exists():
        print('Saved live result already exists; zero additional requests')
        return
    def record(request):
        if len(ledger)>=2:
            raise ValueError('Two-request Stage 5 budget exhausted')
        ledger.append({'attempt':len(ledger)+1,'model':config.model,'endpoint':config.base_url,
                       'timeout_seconds':180,'max_retries':0,'started_utc':datetime.now(timezone.utc).isoformat(),
                       'status':'started'})
        ledger_path.write_text(json.dumps(ledger,indent=2)+'\n',encoding='utf-8')
    original=Path('.env').read_bytes()
    with httpx.Client(event_hooks={'request':[record]}) as http:
        with OpenAI(api_key=config.api_key.get_secret_value(),base_url=config.base_url,
                    timeout=180,max_retries=0,http_client=http) as client:
            pipeline=LocalizationPipeline(ROOT/'.cache/geophotoloc/maps.sqlite3',vision_config=config,
                                          analyzer=VisionAnalyzer(config,client))
            try:
                result=pipeline.run(DATA/'north_bund.jpg')
                (DATA/'north_bund_pipeline.json').write_text(result.model_dump_json()+'\n',encoding='utf-8')
                payloads=download_payloads(result)
                (DATA/'north_bund_annotated.png').write_bytes(payloads['annotated_png'])
                (DATA/'north_bund.geojson').write_bytes(payloads['geojson'])
                # Native complete HTML is a reviewable artifact; offline assets embedded.
                html=build_map(result,offline=True).get_root().render()
                html='\n'.join(line if line.strip() else '' for line in html.splitlines())+'\n'
                (DATA/'north_bund_map.html').write_text(html,encoding='utf-8')
                cached=pipeline.run(DATA/'north_bund.jpg')
                assert cached.cache_hit and len(ledger)<=2
                ledger[-1].update(status='success',vision_landmarks=len(result.vision.landmarks),
                                   matched_objects=sum(bool(x.candidates) for x in result.matching.matches),
                                   pose_status=result.localization.status,regions=len(result.localization.regions),
                                   duplicate_run_used_cache=True)
                print(json.dumps(ledger[-1],ensure_ascii=False),flush=True)
            except PipelineFailure as error:
                if ledger:
                    ledger[-1].update(status='failed',code=error.code,message=str(error))
                print(f'Live Pipeline failed: {error.code}: {error}',flush=True)
            finally:
                ledger_path.write_text(json.dumps(ledger,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
                assert Path('.env').read_bytes()==original


if __name__=='__main__':
    main()
