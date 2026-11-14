from types import SimpleNamespace
import json
import hashlib
from shapely.geometry import box,Point,shape,mapping
from geophotoloc.maps import LandmarkStore,MapMatcher
from geophotoloc.models.pose import PoseSearchConfig,PoseLocalizationResult
from geophotoloc.localization import PoseSolver,BaselinePoseSolver,EnhancedPoseSolver
from geophotoloc.localization.enhanced import evaluate_enhanced_pose
from geophotoloc.localization.search import SearchContext
from geophotoloc.localization.projection import to_wgs84_geometry
from geophotoloc.models.maps import GeoBounds
from test_pose_solver import setup_scene,config
from test_maps_matching import entity
from test_visibility import context


def score_scene(point,*,block=False,known=True,complete=True,relations=(),standing_filters=()):
    geometries={'a':box(-200,800,-100,1000),'b':box(100,800,200,1000)}
    entities={key:entity(i+1,key) for i,key in enumerate(geometries)}
    for e in entities.values():
        e.geometry_precision='complete_outline' if complete else 'node'
    coords={'a':(-150,900),'b':(150,900)}
    outlines={key:list(g.exterior.coords) for key,g in geometries.items()}
    observations={key:SimpleNamespace(x=x,coordinates_reliable=True) for key,x in [('a',.4),('b',.6)]}
    obstacles=[box(-400,300,400,500)] if block else []
    return evaluate_enhanced_pose(point,observations,entities,coords,outlines,[.8,.8],relations,
        PoseSearchConfig(footprint_constraints=True,visibility_soft=True),
        context(obstacles,known,entities=[entity(50,'Other Building')] if block else None),geometries,
        standing_filters=standing_filters)


def test_hard_order_beats_identity_and_soft_obstruction():
    good=score_scene((0,0))
    conflict=score_scene((0,1800))
    blocked=score_scene((0,0),block=True)
    assert good.feasible and good.satisfied==1
    assert not conflict.feasible and conflict.conflicts==1 and conflict.score==0
    assert blocked.feasible and good.score>blocked.score>0
    assert all(v['fully_blocked_2d'] for v in blocked.visibility_evidence)
    assert good.components['visibility_quality']==1
    assert blocked.components['visibility_quality']==.5
    assert good.score==round(.8*good.components['base_score']+.15*good.components['footprint_consistency']+.05,8)


def test_unknown_and_partial_geometry_no_free_score():
    missing=score_scene((0,0),known=False)
    blocked=score_scene((0,0),block=True)
    partial=score_scene((0,0),complete=False)
    assert missing.components['visibility_quality']==.5 and missing.score<=blocked.score
    assert partial.feasible and partial.satisfied==0 and partial.indeterminate==1
    assert partial.components['footprint_consistency']==.5
    assert partial.components['geometry_completeness']==0
    assert all(v['visibility_status']=='UNKNOWN' for v in partial.visibility_evidence)


def test_geometry_distance_and_common_fov_are_hard_constraints():
    close=score_scene((-205,900))
    far=score_scene((0,-6000))
    opposite=score_scene((0,900))
    assert not close.feasible and close.reasons==['outside_observation_distance_limits']
    assert not far.feasible and far.reasons==['outside_observation_distance_limits']
    assert not opposite.feasible and opposite.reasons==['no_common_full_footprint_field_of_view']
    water=score_scene((0,0),standing_filters=['water_area'])
    assert not water.feasible and water.score==0 and water.filter_reasons==['water_area']
    assert water.visibility_evidence==[]


def test_inverse_edges_count_once():
    from geophotoloc.models import SpatialRelation
    relations=[SpatialRelation(subject_id='a',object_id='b',relation_type='LEFT_OF'),
               SpatialRelation(subject_id='b',object_id='a',relation_type='RIGHT_OF')]
    result=score_scene((0,0),relations=relations)
    assert result.feasible and result.satisfied==1 and result.conflicts==0


def test_baseline_replay_determinism_and_serialization(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        matches=MapMatcher(store).match(vision)
        original=PoseSolver(store,config()).solve(vision,matches)
        explicit=BaselinePoseSolver(store,config()).solve(vision,matches)
        assert [r.model_dump() for r in original.regions]==[r.model_dump() for r in explicit.regions]
        assert [(h.searched_points,h.feasible_points) for h in original.hypotheses]==[(h.searched_points,h.feasible_points) for h in explicit.hypotheses]
        enhanced=EnhancedPoseSolver(store,config(adaptive_extent=True,footprint_constraints=True,visibility_soft=True,
                                                max_observation_distance_m=2000))
        first=enhanced.solve(vision,matches)
        second=enhanced.solve(vision,matches)
        assert [r.model_dump() for r in first.regions]==[r.model_dump() for r in second.regions]
        restored=PoseLocalizationResult.model_validate_json(first.model_dump_json())
        assert [r.model_dump(mode='json') for r in restored.regions]==[r.model_dump(mode='json') for r in first.regions]
        assert json.loads(json.dumps(first.geojson))['type']=='FeatureCollection'


def test_original_default_snapshot_from_stage5_commit(extraction,photo):
    # Captured by executing solver.py from 451ed058, before this enhancement.
    # Excludes timing and newly added diagnostic fields, includes exact geometry.
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        result=PoseSolver(store).solve(vision,MapMatcher(store).match(vision))
        stable=[dict(geometry=r.geometry,best_location=r.best_location.model_dump(),score=r.best_score.score,
                     area=r.area_m2,count=r.candidate_point_count,assignments=r.assignments) for r in result.regions]
        digest=hashlib.sha256(json.dumps(stable,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        assert digest=='3240350480d41e224d0328261bd612cfc0dc28fce6ae3d0d69e4fb0afdb12317'
        assert [(h.searched_points,h.feasible_points) for h in result.hypotheses]==[(2352,2140)]


def test_adaptive_search_outside_import_and_single_landmark(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,system=setup_scene(extraction,photo,store)
        matches=MapMatcher(store).match(vision)
        old=PoseSolver(store,config()).solve(vision,matches)
        new=PoseSolver(store,config(adaptive_extent=True,max_observation_distance_m=4000)).solve(vision,matches)
        assert shape(new.hypotheses[0].search_geometry).area>shape(old.hypotheses[0].search_geometry).area*2
        bounds=GeoBounds(south=31.22,north=31.26,west=121.48,east=121.52)
        ctx=SearchContext(store,'toy',bounds)
        outside=(4000,0)
        assert 'outside_map_coverage' in ctx.filter_reasons(outside,[])
        assert ctx.filter_reasons(outside,[],allow_uncovered=True)==[]
        assert ctx.coverage_status(Point(outside))=='UNKNOWN'
        assert any(r.map_coverage_status=='UNKNOWN' for r in new.regions)
        assert all(h.searched_points<=1500 for h in new.hypotheses)
        assert sum(h.distance_filtered_points for h in new.hypotheses)>0
        for region in new.regions:
            for entity_id in region.assignments.values():
                target=ctx.system.to_local(store.get(entity_id).location)
                observer=ctx.system.to_local(region.best_location)
                assert 5<Point(target).distance(Point(observer))<=4000+1e-6
        vision.landmarks=vision.landmarks[:1];vision.relations=[]
        single=EnhancedPoseSolver(store).solve(vision,MapMatcher(store).match(vision))
        assert single.status=='INSUFFICIENT_EVIDENCE' and single.regions==[]


def test_coverage_provenance_and_known_obstacles(extraction,photo):
    with LandmarkStore(':memory:') as store:
        _,system=setup_scene(extraction,photo,store)
        bounds=GeoBounds(south=31.22,north=31.26,west=121.48,east=121.52)
        entities=store.list_entities()
        blocker=entity(50,'Building',category='building')
        blocker.geometry=mapping(to_wgs84_geometry(box(-100,-100,100,100),system))
        blocker.geometry_precision='complete_outline';blocker.tags={'building':'yes'}
        entities.append(blocker)
        metadata=dict(source='fixture',fetched_at='2026-11-14',query_sha256='fixture',stored_entities=len(entities),
                      query='way["building"];out meta geom;',bounds=bounds.model_dump(),warnings=[])
        store.import_entities(entities,'toy',bounds,metadata)
        ctx=SearchContext(store,'toy',bounds)
        origin=ctx.system.to_local(system.to_geographic((0,0)))
        assert ctx.coverage_status(Point(origin))=='COMPLETE'
        assert ctx.coverage_status(ctx.coverage.buffer(100))=='PARTIAL'
        assert ctx.coverage_status(Point(1e6,1e6))=='UNKNOWN'
        assert 'building_interior' in ctx.filter_reasons(origin,[],allow_uncovered=True)
        partial=entity(51,'Incomplete Building',category='building')
        partial.geometry=blocker.geometry
        partial.geometry_precision='partial_geometry';partial.complete_geometry=False
        partial.tags={'building':'yes'}
        entities.append(partial);metadata['stored_entities']=len(entities)
        store.import_entities(entities,'toy',bounds,metadata)
        incomplete=SearchContext(store,'toy',bounds)
        assert incomplete.coverage_status(Point(origin))=='PARTIAL'
        assert incomplete.coverage_status(Point(500,500))=='COMPLETE'
        node=entity(52,'Point-only Building',category='building');node.tags={'building':'yes'}
        entities.append(node);metadata['stored_entities']=len(entities)
        store.import_entities(entities,'toy',bounds,metadata)
        uncertain=SearchContext(store,'toy',bounds)
        assert uncertain.coverage_status(Point(500,500))=='PARTIAL'
