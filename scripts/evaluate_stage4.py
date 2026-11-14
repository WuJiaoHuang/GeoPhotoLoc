"""Offline real-data pose evaluation. No truth, source descriptions or vision API."""
import json
import hashlib
from pathlib import Path
from geophotoloc.maps import LandmarkStore,MapMatcher
from geophotoloc.models import VisionExtractionResult
from geophotoloc.localization import PoseSolver


def main():
    root=Path(__file__).resolve().parents[1]
    output=root/'docs/evaluation/stage4'
    output.mkdir(parents=True,exist_ok=True)
    summary=[]
    with LandmarkStore() as store:
        for path in sorted((root/'docs/evaluation/stage2_1/results').glob('*.json')):
            vision=VisionExtractionResult.model_validate_json(path.read_text(encoding='utf-8'))
            matches=MapMatcher(store).match(vision)
            result=PoseSolver(store).solve(vision,matches)
            (output/f'{path.stem}.json').write_text(result.model_dump_json(indent=2)+'\n',encoding='utf-8')
            (output/f'{path.stem}.geojson').write_text(json.dumps(result.geojson,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            record=dict(sample=path.stem,status=result.status,regions=len(result.regions),
                        vision_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                        seconds=result.elapsed_seconds,points=sum(h.searched_points for h in result.hypotheses),
                        hypotheses=[dict(id=h.id,assignments=h.assignments,points=h.searched_points,
                                         feasible=h.feasible_points,filtered=h.filtered_points,limited=h.limited,
                                         reasons=h.reasons) for h in result.hypotheses])
            summary.append(record)
            print(json.dumps(record,ensure_ascii=False),flush=True)
    (output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    main()
