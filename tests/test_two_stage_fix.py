import json
from shapely.geometry import box
from geophotoloc.localization import FixedPoseSolver,PoseSearchConfig
from geophotoloc.models.pose import PoseLocalizationResult
from geophotoloc.maps import LandmarkStore,MapMatcher
from geophotoloc.localization.visibility import cached_visibility
from test_pose_solver import setup_scene
from test_visibility import context


def test_bounded_cache_and_unknown():
    ctx=context(known=False);target=box(-100,1000,100,1100)
    first=cached_visibility((0,0),target,ctx,cache_size=1)
    queries=ctx.strtree_queries
    second=cached_visibility((0,0),target,ctx,cache_size=1)
    assert second is first and ctx.strtree_queries==queries
    assert first.visibility_status=='UNKNOWN' and first.quality==.5
    cached_visibility((0,-10),target,ctx,cache_size=1)
    assert len(ctx.visibility_results)==1


def test_no_rays_in_fast_stage_budget_trace_and_repeat(extraction,photo,monkeypatch):
    import geophotoloc.localization.fixed as fixed
    def forbidden(*args,**kwargs):raise AssertionError('Unexpected visibility call')
    monkeypatch.setattr(fixed,'cached_visibility',forbidden)
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        matches=MapMatcher(store).match(vision)
        config=PoseSearchConfig(viewpoint_fix=True,adaptive_extent=True,footprint_constraints=True,max_points_per_hypothesis=120,max_total_points=150,visibility_soft=False)
        solver=FixedPoseSolver(store,config)
        a=solver.solve(vision,matches);b=solver.solve(vision,matches)
        assert a.status=='SEARCH_LIMITED'
        assert sum(h.searched_points for h in a.hypotheses)<=150
        assert a.diagnostics['visibility_review_points']==0
        assert a.regions and all(r.best_scored_point and r.region_medoid for r in a.regions)
        assert [r.model_dump(mode='json') for r in a.regions]==[r.model_dump(mode='json') for r in b.regions]
        assert [h.sample_trace for h in a.hypotheses]==[h.sample_trace for h in b.hypotheses]
        assert PoseLocalizationResult.model_validate_json(a.model_dump_json()).status==a.status
        assert json.loads(json.dumps(a.geojson))['type']=='FeatureCollection'
        for h in a.hypotheses:
            assert len(h.sample_trace)==h.searched_points
            assert h.budget<=120 and 0<=h.sampling_completion_ratio<=1
            assert h.unsearched_area_m2>=0


def test_review_only_after_all_fast_searches_and_single(extraction,photo,monkeypatch):
    import geophotoloc.localization.fixed as fixed
    calls=[]
    original=fixed.cached_visibility
    def counted(*args,**kwargs):
        calls.append(args[0]);return original(*args,**kwargs)
    monkeypatch.setattr(fixed,'cached_visibility',counted)
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        matches=MapMatcher(store).match(vision)
        config=PoseSearchConfig(adaptive_extent=True,footprint_constraints=True,visibility_soft=True,max_total_points=150,max_points_per_hypothesis=150,max_visibility_points_total=2,max_visibility_points_per_hypothesis=2)
        result=FixedPoseSolver(store,config).solve(vision,matches)
        assert result.diagnostics['visibility_review_points']<=2
        assert len(calls)<=4 and all(r['score']['visibility_reviewed'] for r in result.reviewed_candidates)
        vision.landmarks=vision.landmarks[:1];vision.relations=[]
        single=FixedPoseSolver(store,config).solve(vision,MapMatcher(store).match(vision))
        assert single.status=='INSUFFICIENT_EVIDENCE' and not single.regions


def test_identity_budgets_are_fair_and_context_reused(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        matches=MapMatcher(store).match(vision)
        matches.region_hypotheses=[matches.region_hypotheses[0].model_copy(deep=True) for _ in range(6)]
        config=PoseSearchConfig(adaptive_extent=True,footprint_constraints=True,max_total_points=1800,max_points_per_hypothesis=500)
        result=FixedPoseSolver(store,config).solve(vision,matches)
        assert [h.budget for h in result.hypotheses]==[300]*6
        assert all(0<h.searched_points<=300 for h in result.hypotheses)
        assert result.diagnostics['context_loads']==1
        assert sum(h.searched_points for h in result.hypotheses)<=1800


def test_diverse_modes_keep_local_high_score_and_an_independent_area():
    from types import SimpleNamespace
    from geophotoloc.localization.fixed import diversified_regions
    shapes=[box(-100,-100,100,100),box(1000,0,1010,10),box(-1000,0,-990,10)]
    scores={(0,0):SimpleNamespace(score=.99),(1005,5):SimpleNamespace(score=.7),(-995,5):SimpleNamespace(score=.6)}
    chosen=diversified_regions(shapes,scores,2)
    assert len(chosen)==2 and shapes[0] in chosen
    assert any(p in chosen for p in shapes[1:])


def test_review_occurs_after_every_fast_geometry_call(extraction,photo,monkeypatch):
    import geophotoloc.localization.fixed as fixed
    sequence=[];fast=fixed.evaluate_partial_pose;review=fixed.cached_visibility
    def count_fast(*args,**kwargs):sequence.append('fast');return fast(*args,**kwargs)
    def count_review(*args,**kwargs):sequence.append('review');return review(*args,**kwargs)
    monkeypatch.setattr(fixed,'evaluate_partial_pose',count_fast)
    monkeypatch.setattr(fixed,'cached_visibility',count_review)
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        matches=MapMatcher(store).match(vision)
        matches.region_hypotheses=[matches.region_hypotheses[0].model_copy(deep=True) for _ in range(2)]
        config=PoseSearchConfig(adaptive_extent=True,footprint_constraints=True,visibility_soft=True,max_total_points=120,max_points_per_hypothesis=60)
        result=FixedPoseSolver(store,config).solve(vision,matches)
        assert 'review' in sequence and 'fast' in sequence
        assert max(i for i,s in enumerate(sequence) if s=='fast')<sequence.index('review')
        for r in result.reviewed_candidates:
            score=r['score'];c=score['components']
            assert abs(score['stage2_score']-(.8*c['base_score']+.15*c['footprint_consistency']+.05*c['visibility_quality']))<2e-8


def test_zero_per_hypothesis_review_limit_never_fires_rays(extraction,photo,monkeypatch):
    import geophotoloc.localization.fixed as fixed
    def forbidden(*args,**kwargs):raise AssertionError('Zero-cap ray call')
    monkeypatch.setattr(fixed,'cached_visibility',forbidden)
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        config=PoseSearchConfig(adaptive_extent=True,footprint_constraints=True,visibility_soft=True,max_visibility_points_per_hypothesis=0,max_total_points=100)
        result=FixedPoseSolver(store,config).solve(vision,MapMatcher(store).match(vision))
        assert result.diagnostics['visibility_review_points']==0 and result.reviewed_candidates==[]
