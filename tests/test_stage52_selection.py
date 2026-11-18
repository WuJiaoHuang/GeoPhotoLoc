from types import SimpleNamespace
import pytest
from shapely.geometry import box,Point
from shapely.ops import unary_union
from geophotoloc.localization.selection_v2 import select_quality_modes
from geophotoloc.models.pose import PoseConstraintScore,PoseSearchConfig
from geophotoloc.localization import PoseSolver,Stage52PoseSolver
from geophotoloc.maps import LandmarkStore,MapMatcher
from test_pose_solver import setup_scene


def score(value,geometry=1,reliable=3):
 return PoseConstraintScore(feasible=True,score=value,components={'geometry':geometry},reliable_landmark_count=reliable)

def mode(x,y=0):return box(x-4,y-4,x+4,y+4),[(x,y)]

def test_quality_prevents_distant_low_modes_replacing_tied_high_modes():
 entries=[mode(x) for x in (0,100,200,10000)]
 scores={p:score(.99 if p[0]<1000 else .3) for _,ps in entries for p in ps}
 kept,audit=select_quality_modes(entries,scores,3,64)
 assert {p for _,ps in kept for p in ps}=={(0,0),(100,0),(200,0)}
 assert audit['ambiguous'] and not audit['omitted_top_quality_modes']
 assert audit['decisions'][-1]['reason']=='output_budget_lower_quality'


def test_tie_over_budget_is_bounded_and_explicit_under_input_permutation():
 entries=[mode(x) for x in range(0,1000,100)];scores={p:score(.9) for _,ps in entries for p in ps}
 a,log=select_quality_modes(entries,scores,3,64)
 b,other=select_quality_modes(list(reversed(entries)),dict(reversed(list(scores.items()))),3,64)
 assert [g.wkb for g,_ in a]==[g.wkb for g,_ in b]
 assert log==other and len(a)==3 and log['omitted_top_quality_modes']==7
 assert all(d['reason']=='output_budget_tied_quality' for d in log['decisions'] if not d['retained'])
 assert unary_union([g for g,_ in a]).area<=3*64


def test_numerical_near_ties_use_geometry_evidence_before_diversity():
 entries=[mode(0),mode(1000)]
 scores={(0,0):score(.90000001,.25,2),(1000,0):score(.90000002,1,3)}
 kept,audit=select_quality_modes(entries,scores,1,64)
 assert kept[0][1]==[(1000,0)]
 assert audit['decisions'][0]['quality']==[.9,1.,3]


def test_touching_and_overlapping_modes_merge_exactly_with_area_bound():
 entries=[(box(0,0,10,10),[(5,5)]),(box(10,0,20,10),[(15,5)]),(box(50,0,60,10),[(55,5)])]
 scores={p:score(.9) for _,ps in entries for p in ps}
 kept,audit=select_quality_modes(entries,scores,2,200)
 assert audit['merged_modes']==2 and len(kept)==2
 assert unary_union([g for g,_ in kept]).equals(unary_union([g for g,_ in entries]))
 assert max(g.area for g,_ in kept)==200
 narrow,log=select_quality_modes(entries,scores,2,100)
 assert log['merged_modes']==3 and len(narrow)==2 and log['omitted_top_quality_modes']==1
 overlap=[(box(0,0,10,10),[(5,5)]),(box(5,0,15,10),[(12,5)])]
 merged,log=select_quality_modes(overlap,{(5,5):score(.9),(12,5):score(.9)},1,150)
 assert merged[0][0].area==150 and log['merged_modes']==1


def test_redundant_lower_quality_mode_does_not_use_budget():
 entries=[(box(0,0,20,20),[(5,5)]),(box(1,1,10,10),[(8,8)]),mode(100)]
 scores={(5,5):score(.99),(8,8):score(.5),(100,0):score(.4)}
 kept,log=select_quality_modes(entries,scores,2,400)
 assert len(kept)==2 and any(d['reason']=='covered_by_retained_mode' for d in log['decisions'])
 with pytest.raises(ValueError):select_quality_modes(entries,scores,0,400)


def test_strategy_is_explicit_and_keeps_D_search_scores_and_physical_domain(extraction,photo):
 with LandmarkStore(':memory:') as store:
  vision,_=setup_scene(extraction,photo,store);matches=MapMatcher(store).match(vision)
  config=PoseSearchConfig(adaptive_extent=True,viewpoint_fix=True,robust_geometry=True,joint_identity=True,dual_regions=True,audit_hard_feasibility=True,record_diagnostic_trace=True,max_total_points=220,max_points_per_hypothesis=110,max_joint_hypotheses=3)
  d=PoseSolver(store,config).solve(vision,matches)
  e=Stage52PoseSolver(store,config).solve(vision,matches)
  assert d.config.selection_strategy=='legacy' and e.config.selection_strategy=='quality_v2'
  assert d.feasible_regions==e.feasible_regions
  for hd,he in zip(d.hypotheses,e.hypotheses):
   assert [(t['x'],t['y'],t.get('score'),t['feasible']) for t in hd.sample_trace]==[(t['x'],t['y'],t.get('score'),t['feasible']) for t in he.sample_trace]
   assert he.selection_audit or not he.searched_points
  assert all(len([r for r in e.regions if r.hypothesis_id==h.id])<=config.max_regions_per_hypothesis for h in e.hypotheses)
  assert d.config.projection_weight==e.config.projection_weight==.4


def test_submicrometre_transport_does_not_change_tied_modes():
 from shapely.affinity import translate
 entries=[mode(x) for x in range(0,2000,100)]
 scores={p:score(.9) for _,ps in entries for p in ps}
 original,_=select_quality_modes(entries,scores,4,64)
 transported=[(translate(g,1e-8,-1e-8),members) for g,members in entries]
 replay,_=select_quality_modes(transported,scores,4,64)
 assert {p for _,ps in original for p in ps}=={p for _,ps in replay for p in ps}
