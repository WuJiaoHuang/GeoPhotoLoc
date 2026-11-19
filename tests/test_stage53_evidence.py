import gzip,hashlib,json
from pathlib import Path
from shapely.geometry import shape
from geophotoloc.models.refinement import ReliableRefinementResult

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'docs/evaluation/stage5_3'
OLD=ROOT/'docs/evaluation/stage5_2'


def test_frozen_all_real_layers_legacy_equal_and_parallel_containment():
 manifest=json.loads((OUT/'inference_manifest.json').read_text(encoding='utf-8'))
 for name,digest in manifest['artifacts'].items():assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==digest
 paths=list((OUT/'refinement').glob('*.json.gz'));assert len(paths)==12
 for p in paths:
  data=ReliableRefinementResult.model_validate_json(gzip.decompress(p.read_bytes())).model_dump(mode='json')
  old=json.loads(gzip.decompress((OLD/'refinement'/p.name).read_bytes()));layers={l['stage']:l for l in data['layers']}
  for l in old['layers']:assert layers[l['stage']]==l
  assert data['grid_fingerprint']==old['grid_fingerprint']
  assert layers['S1-R']['area_m2']==layers['S0']['area_m2']
  assert layers['S1-R']['passed_points']==layers['S0']['passed_points']
  assert shape(layers['S1-R']['geometry']).difference(shape(layers['S0']['geometry'])).area<1e-12
  assert shape(layers['S2-R']['geometry']).difference(shape(layers['S1-R']['geometry'])).area<1e-12
  for h in data['hypotheses']:
   audit=h['relations'];assert all(x==0 for x in audit['hard_conflicts'])
   for i,score in enumerate(audit['soft_scores']):
    values=[(r['orders'][i]+1)/2 for r in audit['relations'] if r['classes'][i]=='SOFT']
    assert score==(sum(values)/len(values) if values else None)


def test_inference_truth_separation_and_failure_accounting():
 source=(ROOT/'scripts/run_stage53.py').read_text(encoding='utf-8')
 assert 'dataset_references' not in source and '.analyze(' not in source
 evaluator=(ROOT/'scripts/evaluate_stage53.py').read_text(encoding='utf-8')
 assert evaluator.index('verify()')<evaluator.index('refs=json.loads') and '.solve(' not in evaluator
 rows=json.loads((OUT/'evaluation/metrics.json').read_text(encoding='utf-8'));assert len(rows)==70
 assert sum(r['status']=='VISION_UNAVAILABLE' for r in rows)==10
 for row in rows:
  if row['case'] in ('photo_01','photo_03','photo_09','photo_11'):assert row['nearest_region_distance_m'] is None
  if row['stage'] in ('S0','S1','S1-R'):assert row.get('topk') is None
 ledger=json.loads((ROOT/'docs/evaluation/real_camera_diagnostics/api_requests.json').read_text(encoding='utf-8'));assert len(ledger)==17
