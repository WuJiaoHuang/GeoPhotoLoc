from types import SimpleNamespace
import pytest
from shapely.geometry import box,Point,Polygon
from geophotoloc.localization.footprints import angular_footprint,visible_footprint
from geophotoloc.localization.partial import evaluate_partial_pose
from geophotoloc.models.pose import PoseSearchConfig
from test_maps_matching import entity
from test_visibility import context


@pytest.mark.parametrize('heading,fov,status,fraction',[(0,60,'FULL',1),(20,20,'PARTIAL',.25),(180,30,'OUTSIDE',0),(360,60,'FULL',1)])
def test_full_partial_outside_wrap(heading,fov,status,fraction):
    from geophotoloc.localization.footprints import AngularFootprint
    fp=AngularFootprint(0,340,20,40,100,'COMPLETE_OUTLINE',True)
    v=visible_footprint(fp,heading,fov)
    assert v['status']==status and v['fraction']==pytest.approx(fraction)
    assert v['sufficient']==(status!='OUTSIDE')


def scene(point=(0,0),invalid=False):
    geometries={'a':box(-1200,800,-100,1000),'b':box(100,800,200,1000)}
    entities={k:entity(i+1,k) for i,k in enumerate(geometries)}
    for e in entities.values():e.geometry_precision='complete_outline'
    if invalid:geometries['a']=Polygon([(0,1),(1,0),(0,0),(1,1)])
    coords={'a':(-650,900),'b':(150,900)}
    observations={'a':SimpleNamespace(x=.1,coordinates_reliable=True),'b':SimpleNamespace(x=.65,coordinates_reliable=True)}
    return evaluate_partial_pose(point,observations,entities,coords,geometries,[.8,.8],[],PoseSearchConfig(viewpoint_fix=True,footprint_constraints=True,fov_degrees=(60,),principal_points=(.5,)),context())


def test_clipped_building_not_forced_to_geometry_center():
    result=scene()
    assert result.feasible and result.satisfied==1 and result.conflicts==0
    assert any(v['status']=='PARTIAL' for v in result.partial_visibility_evidence)
    assert result.projection_rmse<=.06
    assert result.stage1_score==result.score and result.stage2_score is None
    assert result.visibility_evidence==[] and not result.visibility_reviewed


def test_reverse_order_hard_and_invalid_outline_downgraded():
    result=scene((0,1800))
    assert not result.feasible
    assert 'horizontal_order_conflict' in result.reasons or 'no_common_partial_frame_observation_consistency' in result.reasons
    invalid=scene(invalid=True)
    assert all(f['geometry_quality']!='INVALID_GEOMETRY' for f in invalid.footprint_evidence)


def test_overlap_unknown_and_tiny_interval():
    fp=angular_footprint((0,0),box(-1,10000,1,10001))
    assert visible_footprint(fp,0,60)['sufficient']
    assert visible_footprint(angular_footprint((0,0),Point(0,100)),0,60)['fraction'] is None
    assert visible_footprint(angular_footprint((0,0),None),0,60)['status']=='UNKNOWN'


def test_five_objects_follow_one_camera_without_center_equality():
    from math import tan,radians
    geometries={};entities={};observations={};coordinates={}
    for i,angle in enumerate([-20,-10,0,10,20]):
        key=str(i);x=1000*tan(radians(angle))
        geometries[key]=box(x-15,980,x+15,1020)
        entities[key]=entity(i+10,key);entities[key].geometry_precision='complete_outline'
        coordinates[key]=(x,1000)
        observations[key]=SimpleNamespace(x=.5+tan(radians(angle))/(2*tan(radians(30)))+.02,coordinates_reliable=True)
    result=evaluate_partial_pose((0,0),observations,entities,coordinates,geometries,[.8]*5,[],PoseSearchConfig(fov_degrees=(60,),principal_points=(.5,)),context())
    assert result.feasible and result.satisfied==10 and result.conflicts==0
    assert result.projection_rmse<=.06


def test_point_approximate_order_is_not_a_full_outline_hard_conflict():
    observations={'a':SimpleNamespace(x=.8,coordinates_reliable=True),'b':SimpleNamespace(x=.2,coordinates_reliable=True)}
    entities={'a':entity(1,'A'),'b':entity(2,'B')}
    coordinates={'a':(-100,1000),'b':(100,1000)}
    result=evaluate_partial_pose((0,0),observations,entities,coordinates,{k:None for k in entities},[.8,.8],[],PoseSearchConfig(),context())
    assert result.feasible and result.satisfied==0 and result.indeterminate==1
    assert result.components['footprint_consistency']==.5
