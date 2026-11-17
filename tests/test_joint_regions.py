import json
from shapely.geometry import shape,Point,box
from geophotoloc.localization import JointPoseSolver,PoseSearchConfig
from geophotoloc.maps import LandmarkStore,MapMatcher
from geophotoloc.models.pose import PoseLocalizationResult
from geophotoloc.localization.region_selection import preferred_entries
from test_pose_solver import setup_scene
from types import SimpleNamespace


def test_low_score_geography_keeps_local_preference_and_full_feasible():
    scores={(0,0):SimpleNamespace(score=.99),(1500,0):SimpleNamespace(score=.3)}
    feasible=box(-100,-100,1600,100)
    entries=preferred_entries(scores,[],100,60,feasible,.08,750)
    assert len(entries)==2
    assert any(p.covers(Point(1500,0)) for p,_ in entries)
    assert sum(p.area for p,_ in entries)<=feasible.area


def test_joint_solver_layers_budget_and_repeat(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,system=setup_scene(extraction,photo,store)
        matching=MapMatcher(store).match(vision);before=matching.model_dump_json()
        config=PoseSearchConfig(adaptive_extent=True,robust_geometry=True,joint_identity=True,dual_regions=True,audit_hard_feasibility=True,max_total_points=400,max_points_per_hypothesis=200,max_joint_hypotheses=6)
        a=JointPoseSolver(store,config).solve(vision,matching)
        b=JointPoseSolver(store,config).solve(vision,matching)
        assert a.regions and a.feasible_regions and a.preferred_regions==a.regions
        assert a.identifiability=='AMBIGUOUS'
        assert sum(h.searched_points for h in a.hypotheses)<=400
        assert a.feasible_area_m2>=a.preferred_area_m2>0
        assert [r.model_dump(mode='json') for r in a.regions]==[r.model_dump(mode='json') for r in b.regions]
        layers={f['properties'].get('layer_type') for f in a.geojson['features']}
        assert {'feasible_region','preferred_region'}<=layers
        for preferred in a.regions:
            envelope=next(f for f in a.feasible_regions if f.hypothesis_id==preferred.hypothesis_id)
            from geophotoloc.localization.projection import to_local_geometry
            assert to_local_geometry(shape(preferred.geometry),system).difference(to_local_geometry(shape(envelope.geometry),system)).area<1.0
        assert matching.model_dump_json()==before
        assert PoseLocalizationResult.model_validate_json(a.model_dump_json()).identifiability=='AMBIGUOUS'
        vision.landmarks=vision.landmarks[:1];vision.relations=[]
        single=JointPoseSolver(store,config).solve(vision,MapMatcher(store).match(vision))
        assert single.status=='INSUFFICIENT_EVIDENCE' and single.regions==[]


def test_indexed_obstacle_union_cache_keeps_geometry_and_bounded_memory():
    from shapely.strtree import STRtree
    from geophotoloc.localization.search import SearchContext
    ctx=SearchContext.__new__(SearchContext)
    ctx.obstacles=[box(0,0,2,2),box(1,0,3,2)]+[box(i*10,0,i*10+1,1) for i in range(1,20)]
    ctx.tree=STRtree(ctx.obstacles);ctx.strtree_queries=0;ctx.enable_union_cache=True
    first=ctx.obstacle_union(box(-1,-1,4,3));second=ctx.obstacle_union(box(-1,-1,4,3))
    assert first.area==6 and second is first
    for i in range(1,20):ctx.obstacle_union(box(i*10,-1,i*10+1,2))
    assert len(ctx.obstacle_unions)<=8 and ctx.strtree_queries==21


def test_masked_area_set_algebra_is_exact_not_an_expansion():
    from shapely.ops import unary_union
    from geophotoloc.localization.region_selection import physical_union_area,tiled_union_area,sampled_cell_geometry
    from shapely.strtree import STRtree
    from geophotoloc.localization.search import SearchContext
    ctx=SearchContext.__new__(SearchContext)
    ctx.obstacles=[box(1,0,2,3),box(3,1,4,3)];ctx.tree=STRtree(ctx.obstacles);ctx.strtree_queries=0;ctx.enable_union_cache=True
    domains=[box(0,0,3,3),box(2,0,5,3)]
    expected=unary_union([g.difference(unary_union(ctx.obstacles)) for g in domains]).area
    assert physical_union_area(domains,ctx)==expected==10
    tiles=[box(0,0,1,1),box(0,0,.5,.5),box(1,0,2,1)]
    assert tiled_union_area(tiles,1)==unary_union(tiles).area==2
    cells=sampled_cell_geometry([(0,0)],[(1,0)],2,1,box(-10,-10,10,10))
    assert cells.area==4.5
