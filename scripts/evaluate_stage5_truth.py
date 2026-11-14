"""Independent post-solve evaluation; truth never enters any inference API."""
import json
from pathlib import Path
from geophotoloc.models import GeoPoint,PoseLocalizationResult
from geophotoloc.app.evaluation import evaluate_camera_location

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/evaluation/stage5'


def main():
    truths=json.loads((DATA/'camera_truth.json').read_text(encoding='utf-8'))
    evaluations=[]
    for truth in truths:
        record=dict(case=truth['case'],source=truth['source'],truth_kind=truth['kind'])
        if truth['kind']!='camera_location':
            record.update(evaluated=False,reason='Only bridge-level description; no metre error calculated')
        else:
            if truth['case']=='north_bund':
                path=DATA/'north_bund_pipeline.json'
                if not path.exists():
                    record.update(evaluated=False,reason='Live inference result unavailable; failure not dropped')
                    evaluations.append(record)
                    continue
                pose=PoseLocalizationResult.model_validate(json.loads(path.read_text(encoding='utf-8'))['localization'])
            else:
                pose=PoseLocalizationResult.model_validate_json((ROOT/f"docs/evaluation/stage4/{truth['case']}.json").read_text(encoding='utf-8'))
            record.update(evaluated=True,**evaluate_camera_location(pose,GeoPoint(latitude=truth['latitude'],longitude=truth['longitude'])))
            point=GeoPoint(latitude=truth['latitude'],longitude=truth['longitude'])
            from shapely.geometry import Point,shape
            searched=[h.search_geometry for h in pose.hypotheses if h.search_geometry]
            record['truth_inside_searched_extent']=(any(shape(g).covers(Point(point.longitude,point.latitude)) for g in searched)
                                                   if searched else None)
        evaluations.append(record)
    (DATA/'camera_evaluation.json').write_text(json.dumps(evaluations,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(evaluations,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
