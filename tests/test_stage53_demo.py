from pathlib import Path
import json
import pytest
from streamlit.testing.v1 import AppTest
from geophotoloc.app.refinement_demo import build_refinement_map
from test_stage52_demo import example


def new_example():
 result=example();result.refinement['version']='stage5.3'
 layers=result.refinement['layers'];new=[]
 for l in layers:
  new.append(l)
  if l['stage'] in ('S1','S2'):
   n=dict(l,stage=l['stage']+'-R',relation_counts={'HARD':0,'SOFT':20,'UNKNOWN':5});new.append(n)
 result.refinement['layers']=new
 return result


def test_all_five_map_layers_no_reference_or_network():
 html=build_refinement_map(new_example()).get_root().render()
 for label in ('S0','S1-R','S2-R','并列对照','从 S1-R'):
  assert label in html or json.dumps(label,ensure_ascii=True)[1:-1] in html
 assert '独立评估参考机位' not in html and 'tile.openstreetmap.org' not in html


def test_stage53_parallel_demo_integration(monkeypatch):
 def forbidden(*a,**kw):pytest.fail('Default offline page accessed reference or service')
 monkeypatch.setattr('httpx.Client.send',forbidden);monkeypatch.setattr('sqlite3.connect',forbidden)
 monkeypatch.setattr('geophotoloc.app.refinement_demo.available_cases',lambda:['photo_02'])
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_refinement_case',lambda case:example())
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_reliable_refinement_case',lambda case:new_example())
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_reference_for_evaluation',forbidden)
 app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'src/geophotoloc/app/main.py'),default_timeout=45).run()
 app.radio(key='mode').set_value('空间精化离线').run()
 app.selectbox(key='refinement_version').set_value('Stage 5.3 可靠性分级').run()
 assert not app.exception
 assert app.dataframe[-1].value['层次'].tolist()==['S0','S1','S1-R','S2','S2-R']
 assert app.checkbox(key='show_refinement_reference').value is False
 column=app.dataframe[-1].value['HARD/SOFT/UNKNOWN 点关系计数']
 assert column.isna().tolist()==[True,True,False,True,False]
 assert column.dropna().tolist()==['0/20/5','0/20/5']
