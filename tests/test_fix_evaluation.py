import hashlib,importlib.util,inspect,json
from pathlib import Path
from geophotoloc.localization import PoseSolver
from geophotoloc.models.pose import PoseLocalizationResult

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evaluation/stage5_1a_fix'


def module():
    import sys
    sys.path.insert(0,str(ROOT/'scripts'))
    import evaluate_stage5_1a_fix
    return evaluate_stage5_1a_fix


def test_common_parameters_and_reference_isolation():
    configs=module().configurations()
    switches={'adaptive_extent','footprint_constraints','visibility_soft'}
    common=[{k:v for k,v in c.model_dump().items() if k not in switches} for c in configs.values()]
    assert all(c==common[0] for c in common)
    assert common[0]['max_total_points']==24000 and common[0]['observation_x_tolerance']==.06
    assert list(inspect.signature(PoseSolver.solve).parameters)==['self','vision_result','map_matching_result']
    source=(ROOT/'scripts/evaluate_stage5_1a_fix.py').read_text(encoding='utf-8')
    assert 'camera_truth' not in source and 'evaluate_camera_location' not in source
    post=(ROOT/'scripts/evaluate_stage5_1a_fix_truth.py').read_text(encoding='utf-8')
    assert '.solve(' not in post and 'plan_samples(' not in post
    assert post.index("manifest['artifacts']")<post.index('camera_truth.json')


def test_real_artifacts_budgets_coverage_and_inference_integrity():
    manifest=json.loads((OUT/'run_manifest.json').read_text(encoding='utf-8'))
    hashes={}
    for name,digest in manifest['artifacts'].items():
        assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==digest
    for group in module().GROUPS:
        records=json.loads((OUT/f'{group}_summary.json').read_text(encoding='utf-8'))
        assert len(records)==4
        for record in records:
            case=record['case']
            result=PoseLocalizationResult.model_validate_json((OUT/f'{group}_{case}.json').read_text(encoding='utf-8'))
            assert hashes.setdefault(case,record['input_sha256'])==record['input_sha256']
            assert record['searched_points']==sum(h.searched_points for h in result.hypotheses)<=24000
            assert result.diagnostics.get('visibility_review_points',0)<=100
            assert all(h.searched_points<=4500 for h in result.hypotheses)
            if group!='baseline':
                assert all(h.searched_points<=h.budget for h in result.hypotheses)
                assert all(h.visibility_review_points<=20 for h in result.hypotheses)
            if group!='full_enhanced':assert not result.reviewed_candidates
            if case=='oriental_pearl':assert result.status=='INSUFFICIENT_EVIDENCE' and result.regions==[]
            for h in result.hypotheses:
                assert len(h.sample_trace)==h.searched_points
                assert 0<=h.sampling_completion_ratio<=1
            for region in result.regions:
                assert region.best_scored_point is not None and region.region_medoid is not None
                assert region.best_score.feasible and region.best_score.conflicts==0
                if not region.best_score.visibility_reviewed:
                    assert not region.best_score.visibility_evidence and region.best_score.stage2_score is None
            for feature in result.geojson['features']:
                if feature['properties']['kind']!='region_medoid':
                    assert {'satisfied','conflicts','indeterminate','candidate_point_count'}<=feature['properties'].keys()
    evaluation=json.loads((OUT/'camera_evaluation.json').read_text(encoding='utf-8'))
    assert len(evaluation)==16
    assert all(not r['evaluated'] for r in evaluation if r['case']=='guangzhou_skyline')


def test_instrumented_legacy_replays_reproduce_archived_geometries_and_scores():
    for case in ('beijing_cbd','north_bund','guangzhou_skyline'):
        archived=json.loads((ROOT/f'docs/evaluation/stage5_1a/full_enhanced_{case}.json').read_text(encoding='utf-8'))
        replay=json.loads((OUT/f'legacy_replay_{case}.json').read_text(encoding='utf-8'))
        fields=('geometry','best_location','area_m2','assignments')
        assert len(archived['regions'])==len(replay['regions'])
        for a,b in zip(archived['regions'],replay['regions']):
            assert {k:a[k] for k in fields}=={k:b[k] for k in fields}
            assert a['best_score']['score']==b['best_score']['score']
        assert replay['diagnostics']['visibility_review_points']>100
