import inspect,json,sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from shapely.geometry import box
from PIL import Image
from geophotoloc.localization.diagnostics import annotate_selection
from geophotoloc.localization import PoseSolver,PoseSearchConfig
from geophotoloc.maps import LandmarkStore,MapMatcher
from test_pose_solver import setup_scene
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from run_camera_benchmark import reserve_request,BUDGET
from collect_camera_dataset import camera_template


def test_explicit_camera_template_only():
 assert camera_template('{{Location|31.2|121.5|heading:40}}')['latitude']==31.2
 assert camera_template('{{Location dec|39.9|116.4}}')['longitude']==116.4
 assert camera_template('{{Object location|31.2|121.5}}') is None
 assert camera_template('EXIF GPSLatitude=31.2') is None
 assert camera_template('{{Location|91|121}}') is None


def test_twenty_requests_global_budget_and_duplicate_guard():
 ledger=[]
 for i in range(BUDGET):reserve_request(ledger,str(i),str(i))
 assert len(ledger)==20 and ledger[-1]['attempt']==20
 with pytest.raises(ValueError,match='budget'):reserve_request(ledger,'extra','extra')
 with pytest.raises(ValueError,match='already attempted'):reserve_request([{'image_sha256':'same'}],'different_id','same')
 assert len(ledger)==20


def test_distinct_filtering_stages_and_window_values():
 points=[(10,10),(20,10),(30,10),(800,10)]
 scores={p:SimpleNamespace(score=s) for p,s in zip(points,[.9,.1,.85,.8])}
 a,b=box(0,0,15,15),box(790,0,820,15)
 trace=[dict(x=x,y=y,feasible=True) for x,y in points]+[dict(x=99,y=99,hard_feasible=False,selection_stage='hard_rejected')]
 annotate_selection(trace,scores,[(a,[points[0]]),(b,[points[3]])],[a],PoseSearchConfig(dual_regions=True),[])
 assert [r['selection_stage'] for r in trace]==['preferred','below_score_window','cell_clipping_or_no_component_membership','region_cap','hard_rejected']
 assert trace[1]['window_cutoff']==pytest.approx(.82)
 assert trace[3]['score_rank_within_hypothesis']==3
 assert [s.score for s in scores.values()]==[.9,.1,.85,.8]


def test_observer_keeps_geometry_scores_and_search_exactly(extraction,photo):
 with LandmarkStore(':memory:') as store:
  vision,_=setup_scene(extraction,photo,store);matching=MapMatcher(store).match(vision)
  config=PoseSearchConfig(adaptive_extent=True,viewpoint_fix=True,robust_geometry=True,joint_identity=True,dual_regions=True,audit_hard_feasibility=True,max_total_points=160,max_points_per_hypothesis=80,max_joint_hypotheses=3)
  old=PoseSolver(store,config).solve(vision,matching)
  new=PoseSolver(store,config.model_copy(update={'record_diagnostic_trace':True})).solve(vision,matching)
  assert [r.model_dump() for r in old.regions]==[r.model_dump() for r in new.regions]
  assert old.feasible_area_m2==new.feasible_area_m2
  assert [h.searched_points for h in old.hypotheses]==[h.searched_points for h in new.hypotheses]
  traces=[t for h in new.hypotheses for t in h.sample_trace]
  assert traces and all('hard_feasible' in t and 'selection_stage' in t for t in traces)
  assert all(t['selection_stage']!='awaiting_selection' for t in traces)


def test_frozen_dataset_separates_reference_and_inference():
 root=ROOT/'docs/evaluation/real_camera_diagnostics'
 inputs=json.loads((root/'inference_inputs.json').read_text(encoding='utf-8'))
 refs=json.loads((root/'dataset_references.json').read_text(encoding='utf-8'))['samples']
 assert len(inputs)==14
 groups={}
 for r in refs:
  groups.setdefault(r['source_group'],set()).add(r['split'])
 assert all(len(s)==1 for s in groups.values())
 assert sum(r['split']=='holdout' for r in refs)==6
 for row in inputs:
  assert set(row)=={'id','file','image_sha256'}
  with Image.open(root/row['file']) as im:assert not im.getexif()
 source=(ROOT/'scripts/run_camera_benchmark.py').read_text(encoding='utf-8')
 assert 'dataset_references' not in source and 'camera_truth' not in source
 import ast
 tree=ast.parse(source)
 assert all(k.arg not in {'regions','search_bounds'} for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in {'MapMatcher','RecorderMatcher','PoseSearchConfig','LocalizationPipeline'} for k in n.keywords)
 assert 'max_retries=0' in source
 assert list(inspect.signature(PoseSolver.solve).parameters)==['self','vision_result','map_matching_result']


def test_error_distribution_and_failure_classification():
 from diagnose_camera_benchmark import percentile_summary,classify
 stats=percentile_summary([None,10,20,30,40])
 assert stats['n']==4 and stats['median_m']==25 and stats['p90_m']==pytest.approx(37)
 assert percentile_summary([None])['median_m'] is None
 empty=SimpleNamespace(hypotheses=[],regions=[])
 assert classify(0,0,0,empty)=='vision_insufficient_reliable_observations'
 assert classify(3,3,1,empty)=='map_insufficient_matched_objects'
 assert classify(3,3,3,empty)=='geometry_no_eligible_hypothesis'
 rejected=SimpleNamespace(hypotheses=[SimpleNamespace(searched_points=1,sample_trace=[{'hard_feasible':False}])],regions=[])
 assert classify(3,3,3,rejected)=='geometry_no_hard_feasible_sample'
 rejected.hypotheses[0].sample_trace[0]['hard_feasible']=True
 assert classify(3,3,3,rejected)=='geometry_scoring_or_region_selection_empty'


def test_manifest_tampering_rejected_before_reference_access(tmp_path):
 from diagnose_camera_benchmark import verify_manifest
 import hashlib
 p=tmp_path/'pose.json';p.write_text('{}')
 (tmp_path/'inference_manifest.json').write_text(json.dumps({'artifacts':{'pose.json':hashlib.sha256(p.read_bytes()).hexdigest()}}))
 assert verify_manifest(tmp_path)['artifacts']
 p.write_text('{"changed":true}')
 with pytest.raises(ValueError,match='modified'):verify_manifest(tmp_path)
 source=(ROOT/'scripts/diagnose_camera_benchmark.py').read_text(encoding='utf-8')
 assert 'PoseSolver(' not in source and '.solve(' not in source and 'plan_samples(' not in source
 assert source.index('manifest=verify_manifest(OUT)')<source.index("refs=json.loads((OUT/'dataset_references.json')")


def test_point_center_fov_audit_is_only_a_diagnostic():
 import math
 from audit_camera_assumptions import point_pair_implied_fov
 angle=math.degrees(2*math.atan(.6*math.tan(math.radians(15))))
 assert point_pair_implied_fov(.2,.8,angle)==pytest.approx(30,abs=1e-9)
 assert point_pair_implied_fov(.5,.5,10) is None
 source=(ROOT/'scripts/audit_camera_assumptions.py').read_text(encoding='utf-8')
 assert '.solve(' not in source and 'plan_samples(' not in source


def test_timeout_only_recovery_never_repeats_success_or_exceeds_budget():
 from retry_camera_failures import reserve_retry
 failed={'attempt':1,'image_sha256':'a','status':'failed','code':'API_TIMEOUT'}
 ledger=[failed.copy()]
 row=reserve_retry(ledger,'id','a')
 assert len(ledger)==2 and row['retry_of']==1
 with pytest.raises(ValueError,match='Only one'):reserve_retry(ledger,'id','a')
 with pytest.raises(ValueError,match='Only one'):reserve_retry([{**failed,'status':'success'}],'id','a')
 with pytest.raises(ValueError,match='Only one'):reserve_retry([{**failed,'code':'INVALID_MODEL_OUTPUT'}],'id','a')
 with pytest.raises(ValueError,match='budget'):reserve_retry([failed.copy() for _ in range(20)],'id','a')


def test_recorded_evidence_budget_hashes_and_legacy_equivalence():
 import hashlib
 from collections import Counter
 root=ROOT/'docs/evaluation/real_camera_diagnostics'
 inputs=json.loads((root/'inference_inputs.json').read_text(encoding='utf-8'))
 frozen=json.loads((root/'dataset_freeze.json').read_text(encoding='utf-8'))
 assert hashlib.sha256((root/'dataset_references.json').read_bytes()).hexdigest()==frozen['reference_sha256']
 for row in inputs:
  assert hashlib.sha256((root/row['file']).read_bytes()).hexdigest()==row['image_sha256']
 ledger=json.loads((root/'api_requests.json').read_text(encoding='utf-8'))
 assert len(ledger)<=20
 assert max(Counter(r['image_sha256'] for r in ledger).values(),default=0)<=2
 successes=Counter(r['image_sha256'] for r in ledger if r['status']=='success')
 assert max(successes.values(),default=0)<=1
 assert all(r['model']=='qwen3.8-flash' and r['sdk_max_retries']==0 for r in ledger)
 equivalence=json.loads((root/'legacy_equivalence.json').read_text(encoding='utf-8'))
 assert len(equivalence)==8 and all(r['regions_and_feasible_exact'] and r['point_counts_exact'] for r in equivalence)


def test_fov_diagnostic_handles_nonmonotonic_same_side_rays():
 import math
 from audit_camera_assumptions import point_pair_implied_fov
 fov=30
 angle=abs(math.degrees(math.atan(.8*math.tan(math.radians(fov/2)))-math.atan(.6*math.tan(math.radians(fov/2)))))
 assert point_pair_implied_fov(.8,.9,angle)==pytest.approx(30,abs=1e-8)
 assert point_pair_implied_fov(.1,.9,90)==pytest.approx(math.degrees(2*math.atan(1/.8)))


def test_manifest_accepts_windows_separators_without_changing_payload(tmp_path):
 import hashlib
 from diagnose_camera_benchmark import verify_manifest
 folder=tmp_path/'poses';folder.mkdir();p=folder/'case.json';p.write_text('{}')
 sha=hashlib.sha256(p.read_bytes()).hexdigest()
 (tmp_path/'inference_manifest.json').write_text(json.dumps({'artifacts':{'poses\\case.json':sha}}))
 assert verify_manifest(tmp_path)['artifacts']=={'poses/case.json':sha}


def test_no_searched_point_has_null_distance_not_infinity():
 from diagnose_camera_benchmark import audit_existing_points
 from geophotoloc.models import GeoPoint
 h=SimpleNamespace(id='hyp',region_id='r',assignments={},sample_trace=[],reasons=['insufficient'])
 result=audit_existing_points(SimpleNamespace(hypotheses=[h],regions=[]),GeoPoint(latitude=31,longitude=121),{'r':dict(south=30,north=32,west=120,east=122)})
 assert result['nearest_sample_m'] is None and not result['searched_near_reference']
 json.dumps(result,allow_nan=False)
