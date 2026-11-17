from math import radians,tan
from types import SimpleNamespace
import numpy as np
import pytest
from shapely.geometry import box,Point
from geophotoloc.localization.robust_scoring import huber_loss,angular_interval_distance,normalized_angular_error,evaluate_robust_pose,order_constraints
from geophotoloc.localization import PoseSearchConfig
from geophotoloc.models import SpatialRelation
from test_maps_matching import entity
from test_visibility import context


@pytest.mark.parametrize('e,expected',[(0,0),(.5,.125),(1,.5),(2,1.5),(-3,2.5)])
def test_huber_values(e,expected):
    assert float(huber_loss(e))==pytest.approx(expected)


def test_wrap_and_fov_normalization():
    assert angular_interval_distance(359,1,4)==0
    assert angular_interval_distance(350,1,4)==9
    for fov in (40,60,100):
        scale=2*tan(radians(fov/2))
        sigma=np.degrees(np.arctan(.06*scale))
        error,normalized,tolerance=normalized_angular_error(.5,0,fov,.5,sigma,0)
        assert normalized==pytest.approx(1)
        assert error==pytest.approx(tolerance)


def scene(xs=None,angles=(-20,0,20),relations=(),point=(0,0),unknown=False,config=None):
    config=config or PoseSearchConfig()
    ids=[str(i) for i in range(len(angles))]
    coordinates={k:(1000*tan(radians(a)),1000) for k,a in zip(ids,angles)}
    entities={k:entity(i+1,f'Name {i}') for i,k in enumerate(ids)}
    geometries={k:box(x-5,y-5,x+5,y+5) for k,(x,y) in coordinates.items()}
    for e in entities.values():e.geometry_precision='complete_outline'
    if xs is None:xs=[.5+tan(radians(a))/(2*tan(radians(30))) for a in angles]
    observations={k:SimpleNamespace(x=x,coordinates_reliable=True) for k,x in zip(ids,xs)}
    if unknown:observations['unknown']=SimpleNamespace(x=.1,coordinates_reliable=True)
    result=evaluate_robust_pose(point,observations,entities,coordinates,geometries,[.9]*len(ids),relations,config,context())
    return result


def test_correct_projection_and_exact_joint_components():
    result=scene(config=PoseSearchConfig(fov_degrees=(60,),principal_points=(.5,)))
    assert result.feasible and result.reliable_landmark_count==3
    assert max(e['normalized_error'] for e in result.projection_evidence)<1e-10
    c=result.components
    assert result.score==pytest.approx(.4*c['projection']+.2*c['order']+.25*c['identity']+.15*c['geometry'],abs=1e-8)
    assert result.outlier_image_ids==[]


def test_wrong_order_and_bbox_are_soft_not_pose_deletion():
    correct=scene(angles=(-10,10))
    wrong=scene(xs=(.9,.1),angles=(-10,10))
    assert wrong.feasible and correct.feasible
    assert wrong.conflicts>0 or any(e['normalized_error']>1 for e in wrong.projection_evidence)
    assert wrong.score<correct.score
    assert wrong.outlier_image_ids==[] and wrong.reliable_landmark_count==2
    assert wrong.identifiability=='AMBIGUOUS_TWO_LANDMARKS'


def test_visual_internal_contradiction_is_downweighted_and_inverse_deduped():
    observations={'a':SimpleNamespace(x=.1,coordinates_reliable=True),'b':SimpleNamespace(x=.9,coordinates_reliable=True)}
    relations=[SpatialRelation(subject_id='a',object_id='b',relation_type='RIGHT_OF'),SpatialRelation(subject_id='b',object_id='a',relation_type='LEFT_OF')]
    edges=order_constraints(observations,relations,PoseSearchConfig())
    assert len(edges)==2
    bad=next(e for e in edges if e['left']=='b')
    assert bad['weight']==.25 and bad['downweight_reasons']
    good=next(e for e in edges if e['left']=='a')
    assert good['weight']==1


def test_unknown_is_not_a_reward_and_physical_distance_is_hard():
    known=scene();missing=scene(unknown=True)
    assert known.feasible and missing.feasible and missing.score<known.score
    assert missing.unknown_image_ids==['unknown']
    assert not scene(point=(0,-6000)).feasible
    assert not scene(point=(-363.97,1000)).feasible


def test_one_bad_observation_compared_and_exclusion_limited():
    angles=(-20,-10,0,10,20)
    xs=[.5+tan(radians(a))/(2*tan(radians(30))) for a in angles]
    xs[-1]=.02
    result=scene(xs=xs,angles=angles,config=PoseSearchConfig(fov_degrees=(60,),principal_points=(.5,)))
    assert result.feasible and len(result.outlier_image_ids)==1
    assert result.reliable_landmark_count>=2
    assert result.outlier_comparisons
    selected=next(c for c in result.outlier_comparisons if c['image_landmark_id']==result.outlier_image_ids[0])
    assert selected['eligible'] and selected['exclude_score']>selected['keep_score']
    assert selected['keep_loss']-selected['exclude_loss']>=1


def test_complete_camera_cache_does_not_change_score_or_diagnostics():
    ids=['a','b','c'];angles=[-20,0,20]
    coordinates={k:(1000*tan(radians(a)),1000) for k,a in zip(ids,angles)}
    entities={k:entity(i+1,k) for i,k in enumerate(ids)}
    for e in entities.values():e.geometry_precision='complete_outline'
    geoms={k:box(x-5,y-5,x+5,y+5) for k,(x,y) in coordinates.items()}
    obs={k:SimpleNamespace(x=.5+tan(radians(a))/(2*tan(radians(30))),coordinates_reliable=True) for k,a in zip(ids,angles)}
    ctx=context();config=PoseSearchConfig()
    args=((0,0),obs,entities,coordinates,geoms,[.9]*3,[],config,ctx)
    fast=evaluate_robust_pose(*args,detailed=False);complete=evaluate_robust_pose(*args)
    assert fast.score==complete.score and fast.components==complete.components
    assert (fast.satisfied,fast.conflicts,fast.indeterminate)==(complete.satisfied,complete.conflicts,complete.indeterminate)
    assert len(ctx.robust_camera_cache)==1 and len(ctx.robust_order_cache)==1
    assert len(complete.projection_evidence)==3
    assert all(e['huber_loss']==pytest.approx(float(huber_loss(e['normalized_error']))) for e in complete.projection_evidence)


def test_geometry_can_prefer_lower_name_score_without_overriding_input():
    ids=['a','b','c'];angles=[-20,0,20]
    entities={k:entity(i+1,k) for i,k in enumerate(ids)}
    for e in entities.values():e.geometry_precision='complete_outline'
    obs={k:SimpleNamespace(x=.5+tan(radians(a))/(2*tan(radians(30))),coordinates_reliable=True) for k,a in zip(ids,angles)}
    def evaluate(last_angle,last_score):
        actual=[-20,0,last_angle]
        coords={k:(1000*tan(radians(a)),1000) for k,a in zip(ids,actual)}
        geoms={k:box(x-5,y-5,x+5,y+5) for k,(x,y) in coords.items()}
        return evaluate_robust_pose((0,0),obs,entities,coords,geoms,[.9,.9,last_score],[],PoseSearchConfig(max_outliers=0),context())
    good=evaluate(20,.7);bad=evaluate(-60,.99)
    assert good.feasible and bad.feasible and good.score>bad.score
    assert good.components['identity']<bad.components['identity']
