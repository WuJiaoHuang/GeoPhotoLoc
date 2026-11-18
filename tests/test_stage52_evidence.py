import gzip,hashlib,inspect,json,sys
from pathlib import Path
from shapely.geometry import shape
from geophotoloc.localization import Stage52PoseSolver
from geophotoloc.localization.spatial_refinement import build_spatial_refinement
ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/evaluation/real_camera_diagnostics'
OUT=ROOT/'docs/evaluation/stage5_2'
sys.path.insert(0,str(ROOT/'scripts'))
from run_stage52 import read_pose,trace_signature


def test_E_frozen_same_grids_scores_physical_domain_and_original_data():
 manifest=json.loads((OUT/'inference_manifest.json').read_text(encoding='utf-8'))
 for name,digest in manifest['artifacts'].items():assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==digest
 for name,digest in manifest['historical_artifacts'].items():assert hashlib.sha256((DATA/name).read_bytes()).hexdigest()==digest
 checks=json.loads((OUT/'inference_checks.json').read_text(encoding='utf-8'))
 assert len(checks)==14 and sum(r.get('same_grid_scores_and_feasible',False) for r in checks)==12
 for case in ('photo_02','legacy_beijing_cbd'):
  d=read_pose(DATA/'poses'/f'joint_full_{case}.json.gz');e=read_pose(OUT/'poses'/f'E_{case}.json.gz')
  assert trace_signature(d)==trace_signature(e) and d.feasible_regions==e.feasible_regions
  assert all(r.area_m2<=e.config.preferred_tile_size_m**2+1e-4 for r in e.regions)
  assert all(len([r for r in e.regions if r.hypothesis_id==h.id])<=8 for h in e.hypotheses)


def test_real_nested_ablation_and_unranked_layers():
 paths=list((OUT/'refinement').glob('*.gz'));assert len(paths)==12
 for p in paths:
  data=json.loads(gzip.decompress(p.read_bytes()))
  a,b,c=data['layers']
  assert a['stage']=='S0' and b['stage']=='S1' and c['stage']=='S2'
  assert a['area_m2']+1e-4>=b['area_m2']>=c['area_m2']-1e-4
  assert a['passed_points']>=b['passed_points']>=c['passed_points']
  assert a['actual_points']==b['actual_points']==c['actual_points']
  assert not a['ranked'] and not b['ranked'] and c['ranked']
  assert shape(c['geometry']).difference(shape(b['geometry'])).area<1e-12
  assert shape(b['geometry']).difference(shape(a['geometry'])).area<1e-12
  assert all(abs(r['area_delta'])<1 if r['area_units']=='square_metres' else abs(r['area_delta'])<1e-10 for r in data['geometry_repairs'])


def test_reference_separation_and_no_new_model_requests():
 assert list(inspect.signature(Stage52PoseSolver.solve).parameters)==['self','vision_result','map_matching_result']
 assert list(inspect.signature(build_spatial_refinement).parameters)==['vision','matching','pose','bounds']
 source=(ROOT/'scripts/run_stage52.py').read_text(encoding='utf-8')
 assert 'dataset_references' not in source and 'VisionConfig' not in source and '.analyze(' not in source
 post=(ROOT/'scripts/evaluate_stage52.py').read_text(encoding='utf-8')
 assert post.index('verify()')<post.index("refs=json.loads") and '.solve(' not in post
 ledger=json.loads((DATA/'api_requests.json').read_text(encoding='utf-8'));assert len(ledger)==17
