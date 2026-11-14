from types import SimpleNamespace
from shapely.geometry import box,Point
from shapely.strtree import STRtree
from geophotoloc.localization.visibility import potential_visibility,boundary_rays
from test_maps_matching import entity


def context(obstacles=(),known=True,entities=None):
    return SimpleNamespace(obstacles=list(obstacles),tree=STRtree(obstacles),
        obstacle_types=['building_interior']*len(obstacles),
        obstacle_entities=entities or [entity(i+1,'Blocker') for i in range(len(obstacles))],
        coverage_status=lambda g:'COMPLETE' if known else 'PARTIAL')


def test_clear_and_unknown_not_equal():
    target=box(-50,1000,50,1100)
    clear=potential_visibility((0,0),target,context())
    unknown=potential_visibility((0,0),target,context(known=False))
    assert clear.visibility_status=='CLEAR' and clear.blocked_ratio==0 and clear.quality==1
    assert unknown.visibility_status=='UNKNOWN' and unknown.quality==.5 and unknown.complete_ray_fraction==0
    assert 3<=clear.valid_rays<=12


def test_full_2d_blocker_is_soft_and_target_is_excluded():
    target=box(-50,1000,50,1100)
    blocker=box(-100,400,100,600)
    result=potential_visibility((0,0),target,context([target,blocker]))
    assert result.visibility_status=='POTENTIALLY_OCCLUDED' and result.blocked_ratio==1
    assert result.fully_blocked_2d and result.quality==.5
    assert 'height_and_pitch_unknown' in result.reason
    behind=box(-100,1050,100,1200)
    assert potential_visibility((0,0),target,context([behind])).blocked_ratio==0


def test_partial_blocker_duplicate_identity_and_bounded_front_rays():
    target=box(-100,1000,100,1100)
    blocker=box(-100,400,-10,600)
    result=potential_visibility((0,0),target,context([blocker]))
    assert 0<result.blocked_ratio<1
    same=entity(2,'Duplicate',wikidata='Q1')
    original=entity(1,'Target',wikidata='Q1')
    assert potential_visibility((0,0),target,context([blocker],entities=[same]),target_entity=original).blocked_ratio==0
    rays=boundary_rays((0,0),target,4)
    assert len(rays)==4
    assert all(Point(r.coords[-1]).distance(target.boundary)<1e-8 for r in rays)
    assert potential_visibility((0,0),Point(0,100),context()).visibility_status=='UNKNOWN'
