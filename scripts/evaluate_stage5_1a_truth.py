"""Independent post-solve truth evaluation; never imported by solver or inference runner."""
import json
from pathlib import Path
from shapely.geometry import Point,shape
from geophotoloc.models import GeoPoint,PoseLocalizationResult
from geophotoloc.app.evaluation import evaluate_camera_location
from geophotoloc.geometry.coordinates import horizontal_distance

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=ROOT/'docs/evaluation/stage5_1a'


def main():
    truths=json.loads((ROOT/'docs/evaluation/stage5/camera_truth.json').read_text(encoding='utf-8'))
    # Require all sixteen independent solves before opening any output for evaluation.
    groups=('baseline','extent_only','footprint_only','full_enhanced')
    for group in groups:
        for truth in truths:
            if not (OUTPUT/f"{group}_{truth['case']}.json").exists():
                raise ValueError('Run all independent ablations before post-solve evaluation')
    records=[]
    for group in groups:
        for truth in truths:
            case=truth['case']
            result=PoseLocalizationResult.model_validate_json((OUTPUT/f'{group}_{case}.json').read_text(encoding='utf-8'))
            record=dict(group=group,case=case,truth_kind=truth['kind'],source=truth['source'])
            if truth['kind']!='camera_location':
                record.update(evaluated=False,reason='Only bridge-level reference; no fabricated metre accuracy')
            else:
                point=GeoPoint(latitude=truth['latitude'],longitude=truth['longitude'])
                record.update(evaluated=True,**evaluate_camera_location(result,point))
                record['truth_inside_searched_rectangle']=any(shape(h.search_geometry).covers(Point(point.longitude,point.latitude))
                                                            for h in result.hypotheses if h.search_geometry)
                record['nearest_representative_distance_m']=min((horizontal_distance(point,r.best_location) for r in result.regions),default=None)
            records.append(record)
    (OUTPUT/'camera_evaluation.json').write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    # Post-solve geometry diagnostics at source-reported camera coordinates.
    # These observations never enter search, ranking, or map matching.
    from geophotoloc.maps import LandmarkStore
    from geophotoloc.models.maps import GeoBounds,MapLandmark
    from geophotoloc.localization.search import SearchContext
    from geophotoloc.localization.projection import to_local_geometry
    from geophotoloc.localization.visibility import potential_visibility
    diagnostics=[]
    standing=[]
    with LandmarkStore() as store:
        for truth in truths:
            if truth['kind']!='camera_location':
                continue
            result=PoseLocalizationResult.model_validate_json((OUTPUT/f"full_enhanced_{truth['case']}.json").read_text(encoding='utf-8'))
            entities={raw['id']:MapLandmark.model_validate_json(json.dumps(raw)) for raw in result.matched_landmarks}
            for hypothesis in result.hypotheses:
                row=store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(hypothesis.region_id,)).fetchone()
                context=SearchContext(store,hypothesis.region_id,GeoBounds.model_validate_json(row[0]))
                p=context.system.to_local(GeoPoint(latitude=truth['latitude'],longitude=truth['longitude']))
                if not any(item['case']==truth['case'] for item in standing):
                    standing.append(dict(case=truth['case'],standing_filters=context.filter_reasons(p,[],allow_uncovered=True)))
                targets=[]
                for image_id,entity_id in hypothesis.assignments.items():
                    entity=entities[entity_id]
                    full=entity.complete_geometry and entity.geometry_precision=='complete_outline' and entity.geometry
                    geometry=to_local_geometry(shape(entity.geometry),context.system) if full else Point(context.system.to_local(entity.location))
                    targets.append(dict(image_landmark_id=image_id,entity_id=entity_id,name=entity.name,
                                        distance_to_geometry_m=geometry.distance(Point(p)),
                                        visibility=potential_visibility(p,geometry,context,target_entity=entity).to_dict()))
                diagnostics.append(dict(case=truth['case'],hypothesis_id=hypothesis.id,
                    truth_within_all_target_distance_limits=all(result.config.minimum_distance_m<t['distance_to_geometry_m']<=result.config.max_observation_distance_m for t in targets),
                    map_coverage_status=context.coverage_status(Point(p)),targets=targets))
    (OUTPUT/'postsolve_visibility.json').write_text(json.dumps(diagnostics,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (OUTPUT/'postsolve_standing.json').write_text(json.dumps(standing,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(records,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
