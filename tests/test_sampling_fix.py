import numpy as np
import pytest
from shapely.geometry import Point,box,MultiPolygon
from geophotoloc.localization.extent import distance_feasible_domain,within_observation_distance
from geophotoloc.localization.sampling import allocate_budget,plan_samples,spatial_order,feasible_medoid


def test_conservative_buffer_intersection_and_boundary():
    domain=distance_feasible_domain([Point(-100,0),Point(100,0)],1000)
    assert domain.area<np.pi*1001**2
    assert domain.covers(Point(0,900))
    assert within_observation_distance([(0,900),(0,1000)],[Point(-100,0),Point(100,0)],1000).tolist()==[True,False]
    for angle in np.linspace(0,2*np.pi,100):
        assert distance_feasible_domain([Point(0,0)],1000).covers(Point(1000*np.cos(angle),1000*np.sin(angle)))
    assert distance_feasible_domain([Point(0,0),Point(3000,0)],1000).is_empty


def test_narrow_component_and_all_components_get_budget():
    geometry=MultiPolygon([box(0,0,10000,.01),box(15000,0,15100,100),box(20000,0,20001,1)])
    plan=plan_samples(geometry,60)
    assert len(plan.points)<=60 and set(plan.component_ids)=={0,1,2}
    narrow=[p for p,c in zip(plan.points,plan.component_ids) if plan.components[c].bounds[2]==10000]
    assert narrow and all(geometry.covers(Point(p)) for p in plan.points)
    assert plan.points==plan_samples(geometry,60).points
    assert plan.limited


def test_sampling_does_not_prefer_one_coordinate_half():
    p=plan_samples(box(-5000,-5000,5000,5000),80)
    assert len(p.points)==80
    for sx,sy in [(1,1),(-1,1),(1,-1),(-1,-1)]:
        assert sum(x*sx>0 and y*sy>0 for x,y in p.points)>=10
    assert spatial_order(p.points)==spatial_order(list(reversed(p.points)))
    assert 180<=p.spacing<=600
    assert plan_samples(box(0,0,1e6,1e6),1).spacing==600
    assert plan_samples(box(0,0,10,10),20).spacing==180


@pytest.mark.parametrize('total',[0,1,2,10,100])
def test_allocation_caps_and_fairness(total):
    values=allocate_budget([100,1,1],total,20)
    assert sum(values)<=total and max(values)<=20
    if total>=3:assert min(values)>0
    if 10<=total<60:assert values[0]>values[1]
    if total>=60:assert values==[20,20,20]


def test_feasible_medoid_is_a_real_sample():
    assert feasible_medoid([(0,0),(0,1),(0,2),(100,100)]) in {(0.,1.),(0.,2.)}


def test_supplemental_strata_do_not_revisit_exhausted_coarse_lattice():
    geometry=box(-500,-500,500,500)
    coarse=plan_samples(geometry,100,180,180)
    supplemental=plan_samples(geometry,20,180,180,exclude=coarse.points,supplemental=True)
    assert len(supplemental.points)==20
    assert not set(coarse.points)&set(supplemental.points)
    assert all(geometry.covers(Point(p)) for p in supplemental.points)


def test_zero_cap_and_positive_cap_inference_compatibility():
    assert allocate_budget([1,1,1],100,cap=0)==[0,0,0]
    from pathlib import Path
    import types
    path=Path(__file__).resolve().parents[1]/'docs/evaluation/stage5_1a_fix/sampling_at_inference.py'
    namespace={'__name__':'sampling_at_inference','__package__':'geophotoloc.localization'}
    # Evaluate only the captured allocator, avoiding dataclass module machinery.
    import ast
    tree=ast.parse(path.read_text(encoding='utf-8'))
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='allocate_budget')
    exec(compile(ast.Module(body=[function],type_ignores=[]),str(path),'exec'),namespace)
    for weights in ([1,1,1],[100,1,2],[1]):
        for cap in (None,1,20,4500):
            for total in (0,1,10,100,24000):
                assert allocate_budget(weights,total,cap)==namespace['allocate_budget'](weights,total,cap)
