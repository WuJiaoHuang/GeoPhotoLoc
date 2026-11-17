import hashlib,inspect,json,sys
from pathlib import Path
from shapely.geometry import shape
from geophotoloc.localization import PoseSolver

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from evaluate_stage5_1b import OUTPUT,GROUPS,CASES,read_result,configurations
from evaluate_stage5_1a import load_inputs


def test_joint_inference_does_not_accept_or_read_positional_references():
    assert list(inspect.signature(PoseSolver.solve).parameters)==['self','vision_result','map_matching_result']
    source=(ROOT/'scripts/evaluate_stage5_1b.py').read_text(encoding='utf-8')
    assert 'camera_truth' not in source and 'evaluate_camera_location' not in source
    post=(ROOT/'scripts/evaluate_stage5_1b_truth.py').read_text(encoding='utf-8')
    assert '.solve(' not in post and 'plan_samples(' not in post
    assert post.index("manifest['artifacts']")<post.index('camera_truth.json')
    for config in configurations().values():
        assert config.search_bounds is None and config.max_total_points==24000
        assert (config.projection_weight,config.order_weight,config.identity_weight,config.geometry_weight)==(.4,.2,.25,.15)


def test_real_results_preserve_inputs_and_both_region_layers():
    manifest=json.loads((OUTPUT/'run_manifest.json').read_text(encoding='utf-8'))
    assert len(manifest['artifacts'])==20
    for name,digest in manifest['artifacts'].items():assert hashlib.sha256((OUTPUT/name).read_bytes()).hexdigest()==digest
    for group in GROUPS:
        records=json.loads((OUTPUT/f'{group}_summary.json').read_text(encoding='utf-8'))
        assert len(records)==4
        for record in records:
            case=record['case'];result=read_result(group,case)
            assert record['input_sha256']==load_inputs(case)[2]
            assert result.preferred_regions==result.regions
            assert sum(h.searched_points for h in result.hypotheses)<=24000
            assert all(h.searched_points<=h.budget<=4500 for h in result.hypotheses)
            assert result.diagnostics['visibility_review_points']<=100
            assert result.preferred_area_m2<=result.feasible_area_m2+1
            if case=='oriental_pearl':assert result.status=='INSUFFICIENT_EVIDENCE' and not result.regions
            if result.config.joint_identity:
                assert len(result.identity_hypotheses)<=12
                for key,pool in result.diagnostics['identity_generation']['candidate_pools'].items():assert len(pool)<=4
            if result.config.robust_geometry:
                for r in result.regions:
                    score=r.best_score;c=score.components
                    assert score.feasible and len(score.outlier_image_ids)<=1
                    assert score.reliable_landmark_count>=2 and 'AMBIGU' in score.identifiability
                    if score.reliable_landmark_count==2:assert 'TWO_LANDMARKS' in score.identifiability
                    assert abs(score.score-(.4*c['projection']+.2*c['order']+.25*c['identity']+.15*c['geometry']))<1e-8
                    assert score.projection_evidence and score.outlier_comparisons is not None
            if group=='joint_full':
                kinds={f['properties'].get('layer_type') for f in result.geojson['features']}
                if result.regions:assert {'preferred_region','feasible_region'}<=kinds
                assert all(f.priority=='LOW_UNRANKED' for f in result.feasible_regions)
            supplied=load_inputs(case)[1]
            candidates={(m.image_landmark_id,c.entity.id) for m in supplied.matches for c in m.candidates}
            for h in result.hypotheses:assert all((key,value) in candidates for key,value in h.assignments.items())
    evaluation=json.loads((OUTPUT/'camera_evaluation.json').read_text(encoding='utf-8'))
    assert len(evaluation)==16
    assert all(not r['evaluated'] for r in evaluation if r['case']=='guangzhou_skyline')


def test_new_control_retains_stage5_1a_fix_search_baseline_geometry():
    from geophotoloc.geometry.coordinates import LocalCoordinateSystem
    from geophotoloc.models import GeoPoint
    from geophotoloc.localization.projection import to_local_geometry
    imports=json.loads((ROOT/'docs/evaluation/stage3/imports.json').read_text(encoding='utf-8'))
    bounds={r['region_id']:r['bounds'] for r in imports}
    for case in CASES:
        current=read_result('baseline',case)
        previous=json.loads((ROOT/f'docs/evaluation/stage5_1a_fix/extent_only_{case}.json').read_text(encoding='utf-8'))
        assert len(current.regions)==len(previous['regions'])
        for a,b in zip(current.regions,previous['regions']):
            assert a.best_location.model_dump()==b['best_location']
            assert a.best_score.score==b['best_score']['score']
            box=bounds[a.region_id]
            system=LocalCoordinateSystem(GeoPoint(latitude=(box['south']+box['north'])/2,longitude=(box['west']+box['east'])/2))
            # Compare in the original metre CRS: WGS84 straight segments can
            # differ after exact planar union changes collinear segmentation.
            assert to_local_geometry(shape(a.geometry),system).symmetric_difference(to_local_geometry(shape(b['geometry']),system)).area<1e-4
