from pathlib import Path
import json
import pytest
from streamlit.testing.v1 import AppTest
from geophotoloc.app.refinement_demo import build_refinement_map
from test_stage52_demo import example


def automatic_example():
 result=example();result.refinement['version']='stage5.4'
 for layer,stage in zip(result.refinement['layers'],('A0','A1','A2')):layer['stage']=stage
 result.refinement['distribution']={'count':20,'min':0.,'max':1.,'mean':.5,'null_count':0}
 result.refinement['order_comparison']={'regions':[]}
 return result


def test_automatic_map_layers_and_rank_markers_reference_hidden():
 result=automatic_example();html=build_refinement_map(result).get_root().render()
 assert all(s in html for s in ('A0','A1','A2','F #1'))
 assert '独立评估参考机位' not in html and 'tile.openstreetmap.org' not in html


def test_automatic_offline_page_no_services_or_truth(monkeypatch):
 def forbidden(*a,**kw):pytest.fail('Automatic offline page accessed reference or service')
 monkeypatch.setattr('httpx.Client.send',forbidden);monkeypatch.setattr('sqlite3.connect',forbidden)
 monkeypatch.setattr('geophotoloc.app.refinement_demo.available_cases',lambda:['photo_02'])
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_refinement_case',lambda case:example())
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_automatic_refinement_case',lambda case:automatic_example())
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_reference_for_evaluation',forbidden)
 app=AppTest.from_file(str(Path(__file__).resolve().parents[1]/'src/geophotoloc/app/main.py'),default_timeout=45).run()
 app.radio(key='mode').set_value('空间精化离线').run()
 app.selectbox(key='refinement_version').set_value('Stage 5.4 自动关系 F').run()
 assert not app.exception
 table=next(t.value for t in app.dataframe if '层次' in t.value.columns)
 assert table['层次'].tolist()==['A0','A1','A2']
 assert app.checkbox(key='show_refinement_reference').value is False
 assert any('只增加连续关系评分' in item.value for item in app.caption)
