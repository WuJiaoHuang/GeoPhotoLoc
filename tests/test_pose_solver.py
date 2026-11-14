import json
from math import tan,radians
from shapely.geometry import shape,Point,box,mapping
from geophotoloc.maps import LandmarkStore,MapMatcher
from geophotoloc.models import GeoPoint
from geophotoloc.models.maps import GeoBounds
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from geophotoloc.localization import PoseSolver,PoseSearchConfig
from geophotoloc.localization.projection import to_wgs84_geometry
from test_maps_matching import entity,vision_input


def setup_scene(extraction,photo,store,region='toy',shift=0):
    system=LocalCoordinateSystem(GeoPoint(latitude=31.24+shift,longitude=121.50))
    landmarks=[]
    for i,(x,name) in enumerate([(-200,'Alpha Tower'),(200,'Beta Tower')]):
        p=system.to_geographic((x,1000))
        landmarks.append(entity(i+1+(100 if shift else 0),name,latitude=p.latitude,longitude=p.longitude))
    bounds=GeoBounds(south=31.22+shift,north=31.26+shift,west=121.48,east=121.52)
    store.import_entities(landmarks,region,bounds,{})
    vision=vision_input(extraction,photo,['Alpha Tower','Beta Tower'])
    for item,x in zip(vision.landmarks,[-200,200]):
        item.x=.5+x/1000/(2*tan(radians(37.5)))
        from geophotoloc.models import BoundingBox
        item.bbox=BoundingBox(x_min=item.x-.05,x_max=item.x+.05,y_min=item.y-.05,y_max=item.y+.05)
    return vision,system


def config(**kwargs):
    return PoseSearchConfig(search_radius_m=1400,coarse_spacing_m=250,fine_spacing_m=125,
                            max_points_per_hypothesis=1500,max_total_points=5000,**kwargs)


def test_known_pose_region_geojson_and_reproducibility(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,system=setup_scene(extraction,photo,store)
        matches=MapMatcher(store).match(vision)
        solver=PoseSolver(store,config())
        result=solver.solve(vision,matches)
        assert result.regions and result.status in {'AMBIGUOUS','SEARCH_LIMITED'}
        truth=system.to_geographic((0,0))
        assert any(shape(region.geometry).covers(Point(truth.longitude,truth.latitude)) for region in result.regions)
        assert all(region.area_m2>0 and shape(region.geometry).is_valid for region in result.regions)
        assert all(region.best_score.conflicts==0 for region in result.regions)
        points=[f for f in result.geojson['features'] if f['geometry']['type']=='Point']
        assert points[0]['geometry']['coordinates'][0]>100 and points[0]['geometry']['coordinates'][1]<40
        repeated=solver.solve(vision,matches)
        assert [r.model_dump() for r in result.regions]==[r.model_dump() for r in repeated.regions]


def test_single_landmark_and_empty(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        vision.landmarks=vision.landmarks[:1];vision.relations=[]
        result=PoseSolver(store,config()).solve(vision,MapMatcher(store).match(vision))
        assert result.status=='INSUFFICIENT_EVIDENCE' and not result.regions
        vision.landmarks=[]
        assert PoseSolver(store,config()).solve(vision,MapMatcher(store).match(vision)).status=='INSUFFICIENT_EVIDENCE'


def test_obstacle_filter_and_partial_budget(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,system=setup_scene(extraction,photo,store)
        obstacle=entity(20,'Test Building',category='building')
        obstacle.geometry=mapping(to_wgs84_geometry(box(-100,-100,100,100),system))
        obstacle.geometry_precision='complete_outline';obstacle.tags={'building':'yes'}
        existing=store.list_entities(regions=['toy'])
        bounds=GeoBounds(south=31.22,north=31.26,west=121.48,east=121.52)
        store.import_entities(existing+[obstacle],'toy',bounds,{})
        result=PoseSolver(store,config()).solve(vision,MapMatcher(store).match(vision))
        origin=system.to_geographic((0,0))
        assert not any(shape(r.geometry).covers(Point(origin.longitude,origin.latitude)) for r in result.regions)
        assert any(h.filtered_points>0 for h in result.hypotheses)
        limited=PoseSolver(store,PoseSearchConfig(max_total_points=5,max_points_per_hypothesis=5)).solve(vision,MapMatcher(store).match(vision))
        assert limited.status=='SEARCH_LIMITED' and sum(h.searched_points for h in limited.hypotheses)<=5


def test_multiple_regions(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        setup_scene(extraction,photo,store,region='other',shift=1)
        result=PoseSolver(store,config()).solve(vision,MapMatcher(store).match(vision))
        assert {r.region_id for r in result.regions}=={'toy','other'}


def test_empty_database(extraction,photo):
    import pytest
    with LandmarkStore(':memory:') as store:
        vision=vision_input(extraction,photo,['Alpha Tower'])
        from geophotoloc.models.maps import MapMatchingResult
        match=MapMatchingResult(status='NO_MATCH',matches=[],region_hypotheses=[],distinct_image_relations=[],consistency_checks={},warnings=[],coverage_regions=[])
        with pytest.raises(ValueError,match='empty'):
            PoseSolver(store).solve(vision,match)


def test_water_filter_and_map_boundary(extraction,photo):
    from geophotoloc.localization.search import SearchContext
    with LandmarkStore(':memory:') as store:
        vision,system=setup_scene(extraction,photo,store)
        water=entity(30,'Water',category='water')
        water.geometry=mapping(to_wgs84_geometry(box(-100,-100,100,100),system))
        water.geometry_precision='complete_outline';water.tags={'natural':'water'}
        bounds=GeoBounds(south=31.22,north=31.26,west=121.48,east=121.52)
        store.import_entities(store.list_entities()+[water],'toy',bounds,{})
        context=SearchContext(store,'toy',bounds)
        origin=context.system.to_local(system.to_geographic((0,0)))
        assert 'water_area' in context.filter_reasons(origin,[])
        assert 'outside_map_coverage' in context.filter_reasons((1e7,1e7),[])
        result=PoseSolver(store,config()).solve(vision,MapMatcher(store).match(vision))
        assert any('search_extent_clipped' in reason for h in result.hypotheses for reason in h.reasons)


def test_cli_localize_and_invalid_outputs(extraction,photo,tmp_path,capsys):
    from geophotoloc.cli import main
    db=tmp_path/'maps.sqlite3'
    with LandmarkStore(db) as store:
        vision,_=setup_scene(extraction,photo,store)
    path=tmp_path/'renamed.json';path.write_text(vision.model_dump_json(),encoding='utf-8')
    output=tmp_path/'poses.json';geojson=tmp_path/'areas.geojson'
    assert main(['localize',str(path),'--db',str(db),'--output',str(output),'--geojson',str(geojson),
                 '--coarse-spacing','300','--fine-spacing','150','--max-points','2000'])==0
    assert json.loads(output.read_text(encoding='utf-8'))['regions']
    assert json.loads(geojson.read_text(encoding='utf-8'))['type']=='FeatureCollection'
    assert main(['localize',str(path),'--db',str(db),'--output',str(path)])==1
    bad=tmp_path/'bad.json';bad.write_text('{}',encoding='utf-8')
    assert main(['localize',str(bad),'--db',str(db)])==1


def test_duplicate_physical_assignments_rejected(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        matched=MapMatcher(store).match(vision)
        candidate=matched.matches[0].candidates[0]
        matched.matches[1].candidates=[candidate]
        matched.region_hypotheses[0].assignments['lm_2']=candidate.entity.id
        result=PoseSolver(store,config()).solve(vision,matched)
        assert not result.regions
        assert 'duplicate_physical_entity_assignment_rejected' in result.hypotheses[0].reasons


def test_all_water_has_no_feasible_pose(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,system=setup_scene(extraction,photo,store)
        water=entity(40,'Water',category='water')
        bounds=GeoBounds(south=31.22,north=31.26,west=121.48,east=121.52)
        water.geometry=mapping(box(bounds.west,bounds.south,bounds.east,bounds.north))
        water.geometry_precision='complete_outline';water.tags={'natural':'water'}
        store.import_entities(store.list_entities()+[water],'toy',bounds,{})
        result=PoseSolver(store,config()).solve(vision,MapMatcher(store).match(vision))
        assert result.status=='NO_FEASIBLE_POSE' and not result.regions
        assert result.hypotheses[0].filtered_points>0


def test_geometrically_equivalent_identity_combinations_remain(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        items=store.list_entities()
        duplicate=items[1].model_copy(deep=True);duplicate.id='osm:node:50';duplicate.osm_id=50
        store.import_entities(items+[duplicate],'toy',GeoBounds(south=31.22,north=31.26,west=121.48,east=121.52),{})
        result=PoseSolver(store,config()).solve(vision,MapMatcher(store).match(vision))
        assert len({r.hypothesis_id for r in result.regions})>=2
        assert result.status in {'AMBIGUOUS','SEARCH_LIMITED'}


def test_multipolygon_projection_area_roundtrip():
    from shapely.geometry import MultiPolygon
    from geophotoloc.localization.projection import to_local_geometry
    system=LocalCoordinateSystem(GeoPoint(latitude=31.24,longitude=121.5))
    original=MultiPolygon([box(0,0,100,100),box(200,0,300,100)])
    geographic=to_wgs84_geometry(original,system)
    restored=to_local_geometry(geographic,system)
    import pytest
    assert geographic.is_valid and restored.geom_type=='MultiPolygon'
    assert restored.area==pytest.approx(20000,abs=.01)


def test_configurable_coarse_only_search(extraction,photo):
    with LandmarkStore(':memory:') as store:
        vision,_=setup_scene(extraction,photo,store)
        result=PoseSolver(store,config(refinement_levels=0)).solve(vision,MapMatcher(store).match(vision))
        assert result.regions and all(h.fine_points==0 for h in result.hypotheses)
        assert all(not r.refined for r in result.regions)
