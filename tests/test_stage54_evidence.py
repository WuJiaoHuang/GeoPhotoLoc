import gzip,hashlib,json
from pathlib import Path
import numpy as np
from shapely.geometry import shape
from shapely.ops import unary_union
from geophotoloc.models import PoseLocalizationResult

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'docs/evaluation/stage5_4'


def test_frozen_F_same_scores_grid_and_actual_A2():
 manifest=json.loads((OUT/'inference_manifest.json').read_text(encoding='utf-8'))
 for name,digest in manifest['artifacts'].items():assert hashlib.sha256((OUT/name).read_bytes()).hexdigest()==digest
 checks=json.loads((OUT/'inference_checks.json').read_text(encoding='utf-8'))
 assert len(checks)==14 and sum(r.get('same_grid_scores_and_physical',False) for r in checks)==12
 for path in (OUT/'refinement').glob('*.json.gz'):
  a=json.loads(gzip.decompress(path.read_bytes()));a0,a1,a2=a['layers']
  assert a0['geometry']==a1['geometry'] and a0['area_m2']==a1['area_m2']
  pose=PoseLocalizationResult.model_validate_json(gzip.decompress((OUT/'poses'/f'F_{path.stem}.gz').read_bytes()))
  assert shape(a2['geometry']).equals(unary_union([shape(r.geometry) for r in pose.regions]))
  assert a2['area_m2']==pose.preferred_area_m2
  for h in pose.hypotheses:
   audit=h.automatic_relation_audit
   if not audit:continue
   assert audit['points']==[[t['x'],t['y']] for t in h.sample_trace if 'outside_exact_distance_domain' not in t.get('reasons',[])]
   weights=[r['visual_weight'] for r in audit['relations']]
   if sum(weights):
    expected=sum((r['visual_weight']*np.asarray(r['consistency']) for r in audit['relations']),np.zeros(len(audit['scores'])))/sum(weights)
    assert np.allclose(audit['scores'],expected,atol=1e-12,rtol=0)
   else:assert all(v is None for v in audit['scores'])
   assert sum(r.hypothesis_id==h.id for r in pose.regions)<=pose.config.max_regions_per_hypothesis


def test_automatic_inference_separation_and_failure_accounting():
 source=(ROOT/'scripts/run_stage54.py').read_text(encoding='utf-8')
 assert 'dataset_references' not in source and '.analyze(' not in source
 scoring=(ROOT/'src/geophotoloc/localization/automatic_relation_scoring.py').read_text(encoding='utf-8')
 assert 'identity_confirmed' not in scoring and 'filename' not in scoring and 'reference' not in scoring
 ev=(ROOT/'scripts/evaluate_stage54.py').read_text(encoding='utf-8');assert ev.index('verify()')<ev.index('refs=json.loads')
 rows=json.loads((OUT/'evaluation/comparison.json').read_text(encoding='utf-8'));assert len(rows)==42
 for row in rows:
  if row['case'] in ('photo_01','photo_03','photo_09','photo_11'):assert row.get('top1_point_distance_m') is None
