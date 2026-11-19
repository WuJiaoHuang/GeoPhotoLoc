from unittest.mock import Mock
from shapely.geometry import shape
from geophotoloc.maps import LandmarkStore,MapMatcher
from geophotoloc.localization import Stage52PoseSolver,Stage54PoseSolver
from geophotoloc.models.pose import PoseSearchConfig
from geophotoloc.app.pipeline import LocalizationPipeline
from test_pose_solver import setup_scene


def test_single_photo_only_real_match_search_and_F_cache(extraction,photo,tmp_path):
 db=tmp_path/'maps.sqlite3'
 with LandmarkStore(db) as store:v,_=setup_scene(extraction,photo,store)
 analyzer=Mock();analyzer.analyze_prepared.return_value=v
 # Fixed server config is allowed; run() accepts only the photo.
 pipeline=LocalizationPipeline(db,analyzer=analyzer,automatic_relations=True,search_config=PoseSearchConfig(max_total_points=240,max_points_per_hypothesis=120,max_joint_hypotheses=3))
 result=pipeline.run(photo);cached=pipeline.run(photo)
 assert analyzer.analyze_prepared.call_count==1 and cached.cache_hit
 assert result.localization.config.selection_strategy=='automatic_v1'
 assert result.localization.regions and result.matching.matches
 assert [l['stage'] for l in result.refinement['layers']]==['A0','A1','A2']
 a,b,c=result.refinement['layers'];assert a['geometry']==b['geometry'] and a['area_m2']==b['area_m2']
 from shapely.ops import unary_union
 assert shape(c['geometry']).equals(unary_union([shape(r.geometry) for r in result.localization.regions]))
 assert c['area_m2']==result.localization.preferred_area_m2
 assert all(len(h.selection_audit.get('decisions',[]))>=len([r for r in result.localization.regions if r.hypothesis_id==h.id]) for h in result.localization.hypotheses)


def test_same_E_F_grid_scores_identity_physical_and_bound(extraction,photo):
 with LandmarkStore(':memory:') as store:
  v,_=setup_scene(extraction,photo,store);m=MapMatcher(store).match(v)
  config=PoseSearchConfig(record_diagnostic_trace=True,max_total_points=220,max_points_per_hypothesis=110,max_joint_hypotheses=3)
  e=Stage52PoseSolver(store,config).solve(v,m);f=Stage54PoseSolver(store,config).solve(v,m)
  assert e.feasible_regions==f.feasible_regions and e.identity_hypotheses==f.identity_hypotheses
  for a,b in zip(e.hypotheses,f.hypotheses):
   assert a.assignments==b.assignments
   assert [(t['x'],t['y'],t.get('score'),t.get('components'),t['feasible']) for t in a.sample_trace]==[(t['x'],t['y'],t.get('score'),t.get('components'),t['feasible']) for t in b.sample_trace]
  assert all(r.area_m2<=f.config.preferred_tile_size_m**2+1e-4 for r in f.regions)
  assert all(sum(r.hypothesis_id==h.id for r in f.regions)<=f.config.max_regions_per_hypothesis for h in f.hypotheses)


def test_no_effective_relations_F_exact_E_fallback(extraction,photo):
 with LandmarkStore(':memory:') as store:
  v,_=setup_scene(extraction,photo,store)
  for o in v.landmarks:o.x=.5
  m=MapMatcher(store).match(v);config=PoseSearchConfig(max_total_points=150,max_points_per_hypothesis=150,record_diagnostic_trace=True)
  e=Stage52PoseSolver(store,config).solve(v,m);f=Stage54PoseSolver(store,config).solve(v,m)
  assert len(e.regions)==len(f.regions)>0
  for a,b in zip(e.regions,f.regions):
   assert a.geometry==b.geometry and a.best_location==b.best_location and a.best_score==b.best_score
   assert b.automatic_relation_score is None
  assert all(h.selection_audit.get('strategy')=='automatic_v1_E_fallback' for h in f.hypotheses if h.searched_points)
