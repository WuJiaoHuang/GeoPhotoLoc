from copy import deepcopy
from shapely.geometry import shape
from geophotoloc.localization import Stage52PoseSolver
from geophotoloc.localization.spatial_refinement import build_spatial_refinement,build_reliable_spatial_refinement
from geophotoloc.models.pose import PoseSearchConfig
from geophotoloc.models.maps import GeoBounds
from geophotoloc.maps import LandmarkStore,MapMatcher
from test_pose_solver import setup_scene


def test_new_parallel_layers_neutral_soft_and_legacy_unchanged(extraction,photo):
 with LandmarkStore(':memory:') as store:
  v,_=setup_scene(extraction,photo,store);m=MapMatcher(store).match(v)
  p=Stage52PoseSolver(store,PoseSearchConfig(max_total_points=180,max_points_per_hypothesis=90,record_diagnostic_trace=True,max_joint_hypotheses=3)).solve(v,m)
  bounds={r:GeoBounds.model_validate_json(store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(r,)).fetchone()[0]) for r in store.coverage_regions()}
  old=build_spatial_refinement(v,m,p,bounds);before=deepcopy(old);pose_before=p.model_dump_json()
  result=build_reliable_spatial_refinement(v,m,p,bounds,old)
  layers={l['stage']:l for l in result['layers']}
  assert list(layers)==['S0','S1','S1-R','S2','S2-R']
  assert old==before and p.model_dump_json()==pose_before
  for l in old['layers']:assert layers[l['stage']]==l
  assert layers['S1-R']['area_m2']==layers['S0']['area_m2']
  assert layers['S1-R']['passed_points']==layers['S0']['passed_points']
  assert layers['S1-R']['relation_counts']['HARD']==0
  assert shape(layers['S1-R']['geometry']).difference(shape(layers['S0']['geometry'])).area<1e-12
  assert shape(layers['S2-R']['geometry']).difference(shape(layers['S1-R']['geometry'])).area<1e-12
  assert result['grid_fingerprint']==old['grid_fingerprint']
  bad=deepcopy(old);bad['grid_fingerprint']='bad'
  import pytest
  with pytest.raises(ValueError,match='grid mismatch'):build_reliable_spatial_refinement(v,m,p,bounds,bad)


def test_verified_synthetic_outlines_hard_refine_and_uncertain_hypothesis_stays(extraction,photo):
 from shapely.geometry import box,mapping
 from geophotoloc.localization.projection import to_wgs84_geometry
 with LandmarkStore(':memory:') as store:
  v,system=setup_scene(extraction,photo,store)
  entities=store.list_entities(regions=['toy'])
  for e in entities:
   x,y=system.to_local(e.location);e.geometry=mapping(to_wgs84_geometry(box(x-12,y-12,x+12,y+12),system));e.complete_geometry=True;e.geometry_precision='complete_outline';e.category='building'
  bounds=GeoBounds(south=31.22,north=31.26,west=121.48,east=121.52);store.import_entities(entities,'toy',bounds,{})
  for o in v.landmarks:o.identity_uncertain=False
  m=MapMatcher(store).match(v)
  for match in m.matches:
   for c in match.candidates:c.identity_certain=True
  p=Stage52PoseSolver(store,PoseSearchConfig(max_total_points=800,max_points_per_hypothesis=800,record_diagnostic_trace=True)).solve(v,m)
  old=build_spatial_refinement(v,m,p,{'toy':bounds})
  # Explicit independent construction evidence, never supplied for real photos.
  ev={o.id:dict(identity_confirmed=True,full_outline_visible=True,source='known synthetic scene') for o in v.landmarks}
  result=build_reliable_spatial_refinement(v,m,p,{'toy':bounds},old,evidence=ev)
  layers={l['stage']:l for l in result['layers']}
  assert 0<layers['S1-R']['area_m2']<layers['S0']['area_m2']
  assert layers['S1-R']['relation_counts']['HARD']>0
  assert layers['S2-R']['area_m2']<=layers['S1-R']['area_m2']
  v.landmarks[0].identity_uncertain=True
  uncertain=build_reliable_spatial_refinement(v,m,p,{'toy':bounds},old,evidence=ev)
  assert next(l for l in uncertain['layers'] if l['stage']=='S1-R')['area_m2']>=layers['S1-R']['area_m2']
