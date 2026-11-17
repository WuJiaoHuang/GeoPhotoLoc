import json
from geophotoloc.localization.hypotheses import generate_identity_hypotheses,assignment_valid,independent_ids
from geophotoloc.localization import PoseSearchConfig
from geophotoloc.maps import LandmarkStore,MapMatcher
from test_maps_matching import entity,vision_input
from geophotoloc.maps.regions import REGIONS


def test_beam_bounded_unknown_alternatives_and_input_unchanged(extraction,photo):
    with LandmarkStore(':memory:') as store:
        entities=[entity(i+1,name,longitude=121.49+i*.002) for i,name in enumerate(['Alpha Tower','Beta Tower','Gamma Tower','Delta Tower','Epsilon Tower','Zeta Tower'])]
        store.import_entities(entities,'shanghai',REGIONS['shanghai'],{})
        vision=vision_input(extraction,photo,['Alpha Tower','Beta Tower'])
        matches=MapMatcher(store).match(vision)
        for m in matches.matches:
            m.candidates=[matches.matches[0].candidates[0].model_copy(deep=True) for _ in range(3)]
            for i,c in enumerate(m.candidates):c.entity=entities[i];c.entity.region_ids=['shanghai']
        before=matches.model_dump_json()
        config=PoseSearchConfig(joint_identity=True)
        search,records,diag=generate_identity_hypotheses(vision,matches,config)
        assert len(records)<=12 and diag['expanded_states']<=24*4*len(vision.landmarks)
        assert any(r['unknown_image_ids'] for r in records)
        assert len({tuple(r['assignments'].values()) for r in records})==len(records)
        assert all(len(set(h.assignments.values()))==len(h.assignments) for h in search)
        assert matches.model_dump_json()==before
        assert generate_identity_hypotheses(vision,matches,config)[1]==records
        assert all(len(p)<=4 for p in diag['candidate_pools'].values())


def test_physical_equivalence_and_explicit_same_object():
    from types import SimpleNamespace
    a=SimpleNamespace(entity=entity(1,'First',wikidata='Q10'))
    b=SimpleNamespace(entity=entity(2,'Second',wikidata='Q10'))
    assert not assignment_valid([('a',a),('b',b)],PoseSearchConfig())
    config=PoseSearchConfig(same_object_groups={'a':'same','b':'same'})
    assert assignment_valid([('a',a),('b',b)],config)
    assert len(independent_ids({'a':a.entity,'b':b.entity},config))==1


def test_unknown_name_and_cross_region_rejected(extraction,photo):
    with LandmarkStore(':memory:') as store:
        store.import_entities([entity(1,'Alpha Tower')],'shanghai',REGIONS['shanghai'],{})
        store.import_entities([entity(2,'Beta Tower',latitude=39.91,longitude=116.45)],'beijing',REGIONS['beijing'],{})
        vision=vision_input(extraction,photo,['Alpha Tower','Beta Tower'])
        matches=MapMatcher(store).match(vision)
        search,records,_=generate_identity_hypotheses(vision,matches,PoseSearchConfig())
        assert all(len(h.assignments)<=1 for h in search)
        assert any(r['unknown_image_ids'] for r in records)
        vision.landmarks[0].name='Unrecognizable generic skyscraper';vision.landmarks[0].name_candidates=[]
        result=MapMatcher(store).match(vision)
        _,_,diag=generate_identity_hypotheses(vision,result,PoseSearchConfig())
        assert diag['candidate_pools'][vision.landmarks[0].id]==[{'entity_id':None,'status':'UNKNOWN','score':0.}]


def test_identical_outlines_cannot_be_counted_twice_with_different_names():
    from types import SimpleNamespace
    from shapely.geometry import box,mapping
    a=entity(10,'A');b=entity(11,'B')
    for e in (a,b):
        e.geometry=mapping(box(121.49,31.23,121.50,31.24));e.geometry_precision='complete_outline'
    assert not assignment_valid([('a',SimpleNamespace(entity=a)),('b',SimpleNamespace(entity=b))],PoseSearchConfig())
