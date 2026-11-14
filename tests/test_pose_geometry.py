from math import sin,cos,radians,tan
import pytest
from geophotoloc.models.pose import PoseSearchConfig
from geophotoloc.localization.scoring import evaluate_pose
from geophotoloc.localization.projection import angular_span
from test_maps_matching import entity,vision_input


def scene(extraction,photo,points,xs=None):
    # Up to two fixtures; explicit independent pinhole expectations.
    vision=vision_input(extraction,photo,["Alpha Tower","Beta Tower"])
    for item,x in zip(vision.landmarks,xs or [.5+points[k][0]/points[k][1]/(2*tan(radians(37.5))) for k in points]):
        item.x=x
    observations={item.id:item for item in vision.landmarks}
    entities={key:entity(i+1,"Tower") for i,key in enumerate(points)}
    return vision,observations,entities


def score(point,observations,entities,points,config=None,outlines=None,relations=()):
    return evaluate_pose(point,observations,entities,points,outlines or {},[.9]*len(entities),relations,config or PoseSearchConfig())


def test_known_pose_and_opposite_order(extraction,photo):
    points={"lm_1":(-200,1000),"lm_2":(200,1000)}
    vision,obs,entities=scene(extraction,photo,points)
    result=score((0,0),obs,entities,points,relations=vision.relations)
    assert result.feasible and result.satisfied==1 and result.conflicts==0
    assert result.heading==pytest.approx(0,abs=1e-6)
    assert result.projection_rmse==pytest.approx(0,abs=1e-8)
    assert len({item['fov_degrees'] for item in result.camera_assumptions})>1
    bad=score((0,2000),obs,entities,points)
    assert not bad.feasible and bad.conflicts==1
    swapped=score((0,0),obs,entities,{"lm_1":points['lm_2'],"lm_2":points['lm_1']})
    assert not swapped.feasible


@pytest.mark.parametrize("rotation",[0,90,180,355])
def test_rotation_and_north_wrap(extraction,photo,rotation):
    points={"lm_1":(-200,1000),"lm_2":(200,1000)}
    _,obs,entities=scene(extraction,photo,points)
    a=radians(rotation)
    rotated={key:(x*cos(a)+y*sin(a),-x*sin(a)+y*cos(a)) for key,(x,y) in points.items()}
    result=score((0,0),obs,entities,rotated)
    assert result.feasible
    assert result.heading==pytest.approx(rotation,abs=1e-6)


@pytest.mark.parametrize("points,reason",[
    ({"lm_1":(0,0),"lm_2":(100,100)},"observer_coincident_or_too_close"),
    ({"lm_1":(0,100),"lm_2":(0,-100)},"no_common_horizontal_field_of_view"),
])
def test_degenerate(extraction,photo,points,reason):
    _,obs,entities=scene(extraction,photo,points,xs=[.5,.5])
    result=score((0,0),obs,entities,points)
    assert not result.feasible and reason in result.reasons


def test_same_direction_indeterminate_and_outline_overlap(extraction,photo):
    points={"lm_1":(0,1000),"lm_2":(0,1200)}
    _,obs,entities=scene(extraction,photo,points,xs=[.3,.7])
    result=score((0,0),obs,entities,points)
    assert result.indeterminate==1 and result.satisfied==0
    points={"lm_1":(-5,1000),"lm_2":(5,1000)}
    result=score((0,0),obs,entities,points,outlines={"lm_1":[(-50,1000),(50,1000)]})
    assert result.indeterminate==1


def test_fov_and_position_residual(extraction,photo):
    points={"lm_1":(-1000,1000),"lm_2":(1000,1000)}
    _,obs,entities=scene(extraction,photo,points,xs=[.1,.9])
    bad=score((0,0),obs,entities,points,PoseSearchConfig(fov_degrees=(60,)))
    assert not bad.feasible and bad.span_deg==pytest.approx(90)
    good=score((0,0),obs,entities,points,PoseSearchConfig(fov_degrees=(110,130)))
    assert good.feasible and good.projection_rmse is not None
    assert angular_span([350,10])==20
    assert angular_span([0,120,240])==240


def test_unreliable_coordinates(extraction,photo):
    points={"lm_1":(-200,1000),"lm_2":(200,1000)}
    _,obs,entities=scene(extraction,photo,points)
    obs['lm_2'].coordinates_reliable=False
    result=score((0,0),obs,entities,points)
    assert not result.feasible and result.satisfied==0


def test_config_validation():
    for kwargs in ({'fine_spacing_m':300},{'fov_degrees':(180,)},{'principal_points':(.9,)},{'max_total_points':0}):
        with pytest.raises(ValueError):
            PoseSearchConfig(**kwargs)


def test_three_rays_global_fov_and_observation_noise(extraction,photo):
    points={'lm_1':(-200,1000),'lm_2':(200,1000)}
    _,obs,entities=scene(extraction,photo,points)
    third=obs['lm_2'].model_copy(deep=True);third.id='lm_3';third.x=.5
    obs['lm_3']=third;entities['lm_3']=entity(3,'Gamma Tower')
    points['lm_3']=(0,-1000)
    result=score((0,0),obs,entities,points)
    assert not result.feasible
    points['lm_3']=(0,1200)
    result=score((0,0),obs,entities,points)
    assert result.feasible and result.landmark_count==3 and result.satisfied==3
    obs['lm_3'].x+=.015
    noisy=score((0,0),obs,entities,points)
    assert noisy.feasible and noisy.projection_rmse>result.projection_rmse


def test_fov_all_rays_even_without_order_edges(extraction,photo):
    points={'lm_1':(0,1000),'lm_2':(866,-500)}
    _,obs,entities=scene(extraction,photo,points,xs=[.5,.5])
    third=obs['lm_2'].model_copy(deep=True);third.id='lm_3'
    obs['lm_3']=third;entities['lm_3']=entity(3,'Gamma Tower');points['lm_3']=(-866,-500)
    result=score((0,0),obs,entities,points)
    assert not result.feasible and result.span_deg>230
    assert 'no_common_horizontal_field_of_view' in result.reasons
