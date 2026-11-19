from copy import deepcopy
from types import SimpleNamespace as NS
import numpy as np
import pytest
from shapely.geometry import box,Point
from shapely.affinity import rotate,translate
from geophotoloc.models import ImageLandmark,SpatialRelation
from geophotoloc.models.pose import PoseSearchConfig
from geophotoloc.localization.relation_reliability import classify_relations


def scene():
 obs={k:ImageLandmark(id=k,name=k,x=x,y=.5,coordinates_reliable=True,identity_uncertain=False,
       bbox=dict(x_min=x-.05,x_max=x+.05,y_min=.2,y_max=.8)) for k,x in [('a',.2),('b',.8)]}
 candidates={k:NS(entity=NS(id=k,name=k,aliases=[],identity_key=k,complete_geometry=True,geometry_precision='complete_outline',category='building',geometry=None,tags={}),
      identity_certain=True,equivalent_entity_ids=[],query_source='primary',score_components={'name_similarity':1}) for k in obs}
 geoms={'a':box(-110,90,-90,110),'b':box(90,90,110,110)}
 rel=[SpatialRelation(subject_id='a',object_id='b',relation_type='LEFT_OF')]
 evidence={k:dict(identity_confirmed=True,full_outline_visible=True,source='independent synthetic construction') for k in obs}
 return obs,candidates,geoms,rel,evidence


def run(points,obs,cands,g,r,e):return classify_relations(points,obs,cands,g,r,PoseSearchConfig(),e)


def test_hard_is_point_dependent_and_wraps_north():
 args=scene();mask,a=run([[0,0],[0,200],[0,100],[-100,100]],*args)
 assert mask.tolist()==[True,False,True,True]
 assert a['relations'][0]['classes']==['HARD','HARD','UNKNOWN','UNKNOWN']
 assert a['relations'][0]['orders']==[1,-1,0,0]
 assert a['hard_conflicts']==[0,1,0,0] and a['soft_scores']==[None]*4


def test_rotation_and_small_perturbation_preserve_classification():
 obs,c,g,r,e=scene();baseline=run([[0,0],[0,200]],obs,c,g,r,e)
 for angle in (90,179,270):
  theta=np.deg2rad(angle);p=np.array([[0,0],[-200*np.sin(theta),200*np.cos(theta)]])
  out=run(p,obs,c,{k:rotate(v,angle,origin=(0,0)) for k,v in g.items()},r,e)
  assert out[0].tolist()==baseline[0].tolist() and out[1]['relations'][0]['classes']==['HARD','HARD']
 for eps in (-1e-8,1e-8):
  out=run([[eps,eps],[eps,200+eps]],obs,c,{k:translate(v,eps,eps) for k,v in g.items()},r,e)
  assert out[0].tolist()==baseline[0].tolist()


@pytest.mark.parametrize('uncertainty',['identity','partial','incomplete','bbox','name','candidate'])
def test_unconfirmed_evidence_never_hard_excludes(uncertainty):
 obs,c,g,r,e=scene()
 if uncertainty=='identity':e['a']['identity_confirmed']=False
 if uncertainty=='partial':e['a']['full_outline_visible']=False
 if uncertainty=='incomplete':c['a'].entity.complete_geometry=False
 if uncertainty=='bbox':obs['a'].bbox=None
 if uncertainty=='name':c['a'].score_components['name_similarity']=.99
 if uncertainty=='candidate':c['a'].identity_certain=False
 mask,a=run([[0,0],[0,200]],obs,c,g,r,e)
 assert mask.tolist()==[True,True] and a['relations'][0]['classes']==['SOFT','SOFT']
 assert a['soft_scores']==[1.,0.]


def test_missing_evidence_defaults_soft_not_verified():
 obs,c,g,r,_=scene();mask,a=run([[0,200]],obs,c,g,r,None)
 assert mask.tolist()==[True] and a['soft_scores']==[0.]


def test_overlapping_angles_large_outline_and_center_not_used():
 obs,c,g,r,e=scene();g['a']=box(-150,80,120,120)
 mask,a=run([[0,0]],obs,c,g,r,e)
 assert mask.tolist()==[True] and a['relations'][0]['classes']==['SOFT'] and a['soft_scores']==[.5]


def test_angular_tolerance_band_cannot_flip_hard_conflict():
 obs,c,g,r,e=scene();g={'a':box(-.01,100,.01,100.1),'b':box(.02,100,.04,100.1)}
 for eps in (-1e-8,0,1e-8):
  mask,a=run([[eps,0]],obs,c,g,r,e)
  assert mask.tolist()==[True] and a['relations'][0]['classes']==['SOFT'] and a['soft_scores']==[.5]


def test_duplicate_inverse_and_contradictions():
 obs,c,g,r,e=scene();r+=r+[SpatialRelation(subject_id='b',object_id='a',relation_type='RIGHT_OF')]
 assert len(run([[0,0]],obs,c,g,r,e)[1]['relations'])==1
 r.append(SpatialRelation(subject_id='b',object_id='a',relation_type='LEFT_OF'))
 mask,a=run([[0,200]],obs,c,g,r,e)
 assert mask.tolist()==[True] and all(x['classes']==['UNKNOWN'] for x in a['relations']) and a['soft_scores']==[None]


def test_same_physical_entity_missing_candidate_and_unreliable_x():
 for variant in ('same','missing','coordinate','group'):
  obs,c,g,r,e=scene();config=PoseSearchConfig()
  if variant=='same':c['b'].entity.identity_key=c['a'].entity.identity_key;c['b'].entity.id='a'
  if variant=='missing':c.pop('b')
  if variant=='coordinate':obs['a'].coordinates_reliable=False
  if variant=='group':config.same_object_groups={'a':'same','b':'same'}
  mask,a=classify_relations([[0,200]],obs,c,g,r,config,e)
  assert mask.tolist()==[True] and a['relations'][0]['classes']==['UNKNOWN'] and a['soft_scores']==[None]


def test_point_downgrade_no_geometry_and_empty_population():
 obs,c,g,r,e=scene();g['a']=Point(-100,100);c['a'].entity.complete_geometry=False
 assert run([[0,200]],obs,c,g,r,e)[1]['relations'][0]['classes']==['SOFT']
 g['a']=None;assert run([[0,200]],obs,c,g,r,e)[1]['relations'][0]['classes']==['UNKNOWN']
 assert run([],obs,c,g,r,e)[1]['soft_scores']==[]


def test_evidence_requires_provenance_and_finite_points():
 obs,c,g,r,e=scene();e['a']['source']=None
 with pytest.raises(ValueError,match='source'):run([[0,0]],obs,c,g,r,e)
 with pytest.raises(ValueError,match='finite'):run([[float('nan'),0]],*scene())


def test_partial_image_box_overlap_and_multiple_soft_mean():
 obs,c,g,r,e=scene();obs['a'].bbox=obs['b'].bbox
 mask,a=run([[0,200]],obs,c,g,r,e)
 assert mask.tolist()==[True] and a['soft_scores']==[0.]
 obs['c']=obs['b'].model_copy(update={'id':'c','x':.95});c['c']=deepcopy(c['b']);c['c'].entity.id='c';c['c'].entity.name='c';c['c'].entity.identity_key='c';g['c']=Point(-100,100)
 r.append(SpatialRelation(subject_id='a',object_id='c',relation_type='LEFT_OF'))
 a=run([[0,200]],obs,c,g,r,None)[1]
 assert a['soft_scores']==[.5]  # image-x also supplies b/c: (0 + .5 + 1) / 3
