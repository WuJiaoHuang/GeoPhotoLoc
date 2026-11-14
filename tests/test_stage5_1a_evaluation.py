import importlib.util
import inspect
import json
from pathlib import Path
from geophotoloc.localization import PoseSolver

ROOT=Path(__file__).resolve().parents[1]


def runner():
    spec=importlib.util.spec_from_file_location('ablation',ROOT/'scripts/evaluate_stage5_1a.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ablation_switches_only_and_same_cached_inputs():
    module=runner()
    configs=module.configurations()
    switch_names={'adaptive_extent','footprint_constraints','visibility_soft'}
    common=[{k:v for k,v in c.model_dump().items() if k not in switch_names} for c in configs.values()]
    assert all(c==common[0] for c in common)
    assert common[0]['coarse_spacing_m']==250 and common[0]['fine_spacing_m']==60
    assert [tuple(getattr(c,n) for n in ('adaptive_extent','footprint_constraints','visibility_soft')) for c in configs.values()]==list(module.GROUPS.values())
    for case in module.CASES:
        vision,matches,hashes=module.load_inputs(case)
        assert vision.landmarks and matches.matches and all(len(v)==64 for v in hashes.values())
        assert module.load_inputs(case)[2]==hashes


def test_no_truth_or_photo_paths_in_solver_inputs():
    assert list(inspect.signature(PoseSolver.solve).parameters)==['self','vision_result','map_matching_result']
    source=(ROOT/'scripts/evaluate_stage5_1a.py').read_text(encoding='utf-8')
    assert 'camera_truth' not in source and 'evaluate_camera_location' not in source
    for path in (ROOT/'src/geophotoloc/localization').glob('*.py'):
        assert 'camera_truth' not in path.read_text(encoding='utf-8')


def test_saved_real_ablation_evidence_is_complete_and_consistent():
    from geophotoloc.models.pose import PoseLocalizationResult
    output=ROOT/'docs/evaluation/stage5_1a'
    hashes={}
    for group in runner().GROUPS:
        records=json.loads((output/f'{group}_summary.json').read_text(encoding='utf-8'))
        assert {r['case'] for r in records}==set(runner().CASES)
        for record in records:
            case=record['case']
            result=PoseLocalizationResult.model_validate_json((output/f'{group}_{case}.json').read_text(encoding='utf-8'))
            assert record['config']==result.config.model_dump(mode='json')
            assert record['searched_points']==sum(h.searched_points for h in result.hypotheses)
            assert record['candidate_regions']==len(result.regions)
            assert all(h.searched_points<=4500 for h in result.hypotheses)
            assert record['searched_points']<=24000
            assert all(r.best_score.conflicts==0 and r.best_score.feasible for r in result.regions)
            assert hashes.setdefault(case,record['input_sha256'])==record['input_sha256']
            if case=='oriental_pearl':
                assert result.status=='INSUFFICIENT_EVIDENCE' and result.regions==[]
            for r in result.regions:
                for visibility in r.best_score.visibility_evidence:
                    if visibility['visibility_status']=='UNKNOWN':
                        assert visibility['quality']==.5
                if group in {'footprint_only','full_enhanced'}:
                    assert {'base_score','footprint_consistency','visibility_quality','geometry_completeness'}<=r.best_score.components.keys()
    evaluation=json.loads((output/'camera_evaluation.json').read_text(encoding='utf-8'))
    assert len(evaluation)==16
    assert all(not r['evaluated'] for r in evaluation if r['case']=='guangzhou_skyline')
