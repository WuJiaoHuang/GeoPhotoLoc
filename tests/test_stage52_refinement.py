from types import SimpleNamespace
import numpy as np
from shapely.geometry import box,shape
from shapely.affinity import rotate
from geophotoloc.localization.spatial_refinement import conservative_relation_mask,build_spatial_refinement
from geophotoloc.models.pose import PoseSearchConfig
from geophotoloc.models import SpatialRelation
from geophotoloc.models.maps import GeoBounds
from geophotoloc.localization import Stage52PoseSolver
from geophotoloc.maps import LandmarkStore,MapMatcher
from test_pose_solver import setup_scene


def scene():
 observations={k:SimpleNamespace(coordinates_reliable=True,identity_uncertain=False,x=x) for k,x in [('a',.2),('b',.8)]}
 candidates={k:SimpleNamespace(query_source='primary',score_components={'name_similarity':1},entity=SimpleNamespace(complete_geometry=True,geometry_precision='complete_outline',category='building')) for k in observations}
 geoms={'a':box(-110,90,-90,110),'b':box(90,90,110,110)}
 relations=[SpatialRelation(subject_id='a',object_id='b',relation_type='LEFT_OF'),SpatialRelation(subject_id='b',object_id='a',relation_type='RIGHT_OF')]
 return observations,candidates,geoms,relations


def test_unknown_heading_order_rotates_wraps_and_inverse_is_not_double_counted():
 obs,cands,geoms,relations=scene();points=np.array([[0,0],[0,200],[0,100]])
 mask,audit=conservative_relation_mask(points,obs,cands,geoms,relations,PoseSearchConfig())
 assert mask.tolist()==[True,False,True]
 assert len(audit['relations'])==1
 assert audit['relations'][0]==dict(left='a',right='b',satisfied=1,conflicts=1,indeterminate=1)
 turned={k:rotate(g,90,origin=(0,0)) for k,g in geoms.items()}
 rotated=np.column_stack([-points[:,1],points[:,0]])
 assert conservative_relation_mask(rotated,obs,cands,turned,relations,PoseSearchConfig())[0].tolist()==mask.tolist()


def test_uncertain_identity_point_geometry_and_overlap_do_not_force_order():
 obs,cands,geoms,relations=scene();obs['a'].identity_uncertain=True
 mask,audit=conservative_relation_mask([[0,200]],obs,cands,geoms,relations,PoseSearchConfig())
 assert mask.tolist()==[True] and not audit['relations']
 obs['a'].identity_uncertain=False;cands['b'].entity.complete_geometry=False
 assert conservative_relation_mask([[0,200]],obs,cands,geoms,relations,PoseSearchConfig())[0].tolist()==[True]
 cands['b'].entity.complete_geometry=True;geoms['b']=geoms['a']
 mask,audit=conservative_relation_mask([[0,0]],obs,cands,geoms,relations,PoseSearchConfig())
 assert mask.tolist()==[True] and audit['relations'][0]['indeterminate']==1


def test_nested_layers_share_source_grid_and_unranked_semantics(extraction,photo):
 with LandmarkStore(':memory:') as store:
  vision,_=setup_scene(extraction,photo,store);matching=MapMatcher(store).match(vision)
  config=PoseSearchConfig(max_total_points=180,max_points_per_hypothesis=90,record_diagnostic_trace=True,max_joint_hypotheses=3)
  pose=Stage52PoseSolver(store,config).solve(vision,matching)
  bounds={r:GeoBounds.model_validate_json(store.connection.execute('SELECT bounds_json FROM regions WHERE id=?',(r,)).fetchone()[0]) for r in store.coverage_regions()}
  before=pose.model_dump_json();result=build_spatial_refinement(vision,matching,pose,bounds)
  a,b,c=result['layers']
  assert a['stage']=='S0' and not a['ranked'] and not b['ranked'] and c['ranked']
  assert a['area_m2']>0 and a['area_m2']==b['area_m2']>=c['area_m2']
  assert a['reliable_relations']==b['reliable_relations']==0
  assert abs(c['area_m2']-pose.preferred_area_m2)<1e-3
  assert a['actual_points']==b['actual_points']==c['actual_points']
  assert a['passed_points']>=b['passed_points']>=c['passed_points']
  assert shape(c['geometry']).difference(shape(b['geometry'])).area<1e-12
  assert pose.model_dump_json()==before


def test_empty_and_surrounding_observers_are_indeterminate():
 obs,cands,geoms,relations=scene()
 mask,audit=conservative_relation_mask([],obs,cands,geoms,relations,PoseSearchConfig())
 assert not mask.size and audit['relations'][0]['conflicts']==0
 mask,audit=conservative_relation_mask([[-100,100]],obs,cands,geoms,relations,PoseSearchConfig())
 assert mask.tolist()==[True] and audit['relations'][0]['indeterminate']==1


def test_invalid_transform_slivers_repaired_without_area_growth():
 import pytest
 from shapely.geometry import Polygon
 from geophotoloc.localization.spatial_refinement import polygonal_valid
 repairs=[]
 g=Polygon([(0,0),(4,0),(4,4),(2,4),(2,5),(2,4),(0,4),(0,0)])
 assert not g.is_valid
 valid=polygonal_valid(g,repairs,'zero-area spike')
 assert valid.is_valid and valid.area==16 and repairs[0]['area_delta']==0
 with pytest.raises(ValueError,match='Substantial'):
  polygonal_valid(Polygon([(0,0),(2,2),(0,2),(2,0),(0,0)]),[], 'bowtie')


def test_component_repair_unions_overlaps_instead_of_even_odd_erasure():
 from shapely.geometry import MultiPolygon
 from geophotoloc.localization.spatial_refinement import polygonal_valid
 # Microscopic overlap from numeric transport, not genuine broad duplicate area.
 g=MultiPolygon([box(0,0,10,10),box(10-1e-12,0,20,10)])
 repairs=[];fixed=polygonal_valid(g,repairs,'transport sliver')
 assert fixed.is_valid and abs(fixed.area-200)<1e-8
 assert repairs and repairs[0]['area_delta']<1e-8


def test_two_verified_outlines_relation_strictly_refines_semantic_envelope(extraction,photo):
 from geophotoloc.localization.projection import to_wgs84_geometry
 from shapely.geometry import mapping,Point
 with LandmarkStore(':memory:') as store:
  vision,system=setup_scene(extraction,photo,store)
  entities=store.list_entities(regions=['toy'])
  for e in entities:
   x,y=system.to_local(e.location)
   e.geometry=mapping(to_wgs84_geometry(box(x-12,y-12,x+12,y+12),system))
   e.complete_geometry=True;e.geometry_precision='complete_outline';e.category='building'
  bounds=GeoBounds(south=31.22,north=31.26,west=121.48,east=121.52)
  store.import_entities(entities,'toy',bounds,{})
  for o in vision.landmarks:o.identity_uncertain=False
  matching=MapMatcher(store).match(vision)
  pose=Stage52PoseSolver(store,PoseSearchConfig(max_total_points=800,max_points_per_hypothesis=800,record_diagnostic_trace=True)).solve(vision,matching)
  result=build_spatial_refinement(vision,matching,pose,{'toy':bounds})
  a,b,c=result['layers']
  assert 0<b['area_m2']<.8*a['area_m2']
  assert b['reliable_relations']==1 and b['passed_points']<a['passed_points']
  near=min((t for h in pose.hypotheses for t in h.sample_trace if t['feasible']),key=lambda t:t['x']**2+t['y']**2)
  q=system.to_geographic((near['x'],near['y']))
  assert shape(b['geometry']).covers(Point(q.longitude,q.latitude))
