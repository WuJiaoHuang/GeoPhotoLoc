import numpy as np
import pytest
from shapely.geometry import Point,box
from shapely.affinity import rotate,translate
from geophotoloc.localization.automatic_relation_scoring import automatic_relation_scores,visual_relation_weight,automatic_quality
from geophotoloc.localization.selection_v2 import select_quality_modes
from geophotoloc.models.pose import PoseSearchConfig
from geophotoloc.models import SpatialRelation
from test_stage53_relations import scene as historical_scene
from test_stage52_selection import score,mode


def scene():
 args=historical_scene()
 for c in args[1].values():c.score=.9
 return args


def run(points,args):
 o,c,g,r,_=args
 return automatic_relation_scores(points,o,c,g,r,PoseSearchConfig())


def test_visual_continuous_gap_overlap_missing_and_deadband():
 o,_,_,_,_=scene();a,b=o.values();config=PoseSearchConfig()
 separate=visual_relation_weight(a,b,config);assert .8<separate<1
 a.bbox=None;missing=visual_relation_weight(a,b,config);assert missing==pytest.approx(.285) and missing<separate
 a.bbox=b.bbox.model_copy(update={'x_min':.1,'x_max':.8})
 overlap=visual_relation_weight(a,b,config);assert 0<overlap<separate
 a.coordinates_reliable=False;assert visual_relation_weight(a,b,config)==0
 a.coordinates_reliable=True;b.x=a.x+.02;assert visual_relation_weight(a,b,config)==0


def test_complete_outline_order_wrap_inside_and_antipodal():
 args=scene();audit=run([[0,0],[0,200],[0,100],[-100,100]],args)
 assert audit['scores']==[1.,0.,.5,.5]
 assert audit['relations'][0]['consistency']==[1.,0.,.5,.5]
 assert audit['usable_relations']==1 and audit['relations'][0]['conflicts']==1


def test_geometry_rotates_and_perturbation_stays_neutral_in_band():
 o,c,g,r,e=scene()
 rotated={k:rotate(v,90,origin=(0,0)) for k,v in g.items()}
 assert run([[0,0],[-200,0]],(o,c,rotated,r,e))['scores']==[1.,0.]
 g={'a':box(-.01,100,.01,100.1),'b':box(.02,100,.04,100.1)}
 for eps in (-1e-8,0,1e-8):assert run([[eps,0]],(o,c,g,r,e))['scores']==[.5]


@pytest.mark.parametrize('variant',['point','partial','missing','overlap','wide'])
def test_neutral_geometry_no_representative_point_certainty(variant):
 o,c,g,r,e=scene()
 if variant=='point':g['a']=Point(-100,100);c['a'].entity.complete_geometry=False
 if variant=='partial':c['a'].entity.complete_geometry=False
 if variant=='missing':g.pop('a')
 if variant=='overlap':g['a']=box(-150,80,120,120)
 if variant=='wide':g['a']=box(-150,-150,150,150)
 result=run([[0,0]],(o,c,g,r,e));assert result['scores']==[.5]


def test_inverse_duplicates_and_explicit_contradiction():
 o,c,g,r,e=scene();r+=r+[SpatialRelation(subject_id='b',object_id='a',relation_type='RIGHT_OF')]
 assert len(run([[0,0]],(o,c,g,r,e))['relations'])==1
 r.append(SpatialRelation(subject_id='b',object_id='a',relation_type='LEFT_OF'))
 a=run([[0,0]],(o,c,g,r,e));assert a['scores']==[None] and a['weight_sum']==0


def test_same_object_or_no_reliable_coords_null():
 o,c,g,r,e=scene();c['b'].entity.id='a';c['b'].entity.identity_key='a'
 assert run([[0,0]],(o,c,g,r,e))['scores']==[None]
 o,c,g,r,e=scene();o['a'].coordinates_reliable=False
 assert run([[0,0]],(o,c,g,r,e))['scores']==[None]


def test_identity_evidence_not_probability_or_relation_weight():
 args=scene();a=run([[0,0]],args);args[0]['a'].identity_uncertain=True;args[1]['a'].score_components['name_similarity']=.4
 b=run([[0,0]],args)
 assert a['scores']==b['scores']==[1.] and a['weight_sum']==b['weight_sum']
 assert b['relations'][0]['identity_evidence']['a']['model_identity_uncertain'] is True
 assert b['relations'][0]['identity_evidence']['a']['name_similarity']==.4


def test_quality_first_relation_second_and_reliable_third_with_budget():
 entries=[mode(x) for x in (0,100,200,1000)];scores={(0,0):score(.9,1,8),(100,0):score(.9,1,2),(200,0):score(.9,1,3),(1000,0):score(.8,1,20)}
 rel={(0,0):0.,(100,0):1.,(200,0):1.,(1000,0):1.}
 qualities={p:automatic_quality(s,rel[p]) for p,s in scores.items()}
 selected,audit=select_quality_modes(entries,scores,2,64,quality_by_point=qualities)
 assert [ps for _,ps in selected]==[[(200,0)],[(100,0)]]
 assert audit['output_modes']==2 and audit['decisions'][-1]['quality'][0]==.8
 assert audit['decisions'][-1]['retained'] is False
 assert sum(g.area for g,_ in selected)<=128


def test_null_fallback_and_numerical_bins():
 entries=[mode(x) for x in (0,100,200)];scores={p:score(.9) for _,ps in entries for p in ps}
 a,aa=select_quality_modes(entries,scores,2,64);b,bb=select_quality_modes(entries,scores,2,64,quality_by_point=None)
 assert aa==bb and [g.wkb for g,_ in a]==[g.wkb for g,_ in b]
 assert automatic_quality(score(.90000001),1.)[0]==automatic_quality(score(.90000002),0.)[0]
 assert automatic_quality(score(.9),None)[2]==.5


def test_F_keeps_E_exact_merge_generation_with_different_relation_scores():
 entries=[(box(0,0,10,10),[(5,5)]),(box(10,0,20,10),[(15,5)])];scores={(5,5):score(.9),(15,5):score(.9)}
 e,ea=select_quality_modes(entries,scores,1,200)
 f,fa=select_quality_modes(entries,scores,1,200,quality_by_point={p:automatic_quality(s,0 if p==(5,5) else 1) for p,s in scores.items()})
 assert ea['merged_modes']==fa['merged_modes']==1 and e[0][0].equals(f[0][0])
 assert fa['decisions'][0]['best_xy']==[15,5]
