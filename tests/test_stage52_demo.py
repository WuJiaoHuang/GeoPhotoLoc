from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from geophotoloc.models import GeoPoint
from geophotoloc.app.demo_data import load_case
from geophotoloc.app.refinement_demo import build_refinement_map


def example():
 result=load_case('beijing_cbd')
 geometry=result.localization.regions[0].geometry
 result.refinement={'layers':[dict(stage=s,geometry=geometry,area_m2=a,reduction_from_previous=red,actual_points=20,passed_points=n,reliable_relations=rel,constraints=['independent synthetic presentation fixture']) for s,a,red,n,rel in [('S0',1e6,None,20,0),('S1',5e5,.5,10,1),('S2',1e5,.8,2,1)]], 'warnings':['not an accuracy claim']}
 result.refinement['geojson']={'type':'FeatureCollection','features':[]}
 return result


def test_map_layers_and_explicit_reference_separation():
 result=example();plain=build_refinement_map(result).get_root().render()
 import json
 assert all(s in plain or json.dumps(s,ensure_ascii=True)[1:-1] in plain for s in ['S0','S1','S2','E 物理可行层（非精确位置）','E 启发式优选（未额外硬筛 S1）'])
 assert '独立评估参考机位' not in plain
 assert '独立评估参考机位' in build_refinement_map(result,reference=GeoPoint(latitude=31,longitude=121)).get_root().render()
 assert 'tile.openstreetmap.org' not in plain


def test_offline_refinement_page_isolated_from_services_and_reference(monkeypatch):
 def forbidden(*args,**kwargs):pytest.fail('Offline default must not access services or reference file')
 monkeypatch.setattr('httpx.Client.send',forbidden);monkeypatch.setattr('sqlite3.connect',forbidden)
 monkeypatch.setattr('geophotoloc.app.refinement_demo.available_cases',lambda:['synthetic'])
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_refinement_case',lambda case:example())
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_reference_for_evaluation',forbidden)
 path=Path(__file__).resolve().parents[1]/'src/geophotoloc/app/main.py'
 app=AppTest.from_file(str(path),default_timeout=45).run()
 app.radio(key='mode').set_value('空间精化离线').run()
 assert not app.exception
 # Stage area/point counts, rather than only function invocation.
 table=app.dataframe[-1].value
 assert table['层次'].tolist()==['S0','S1','S2']
 assert table['面积 km²'].tolist()==[1.,.5,.1]
 assert table['通过点'].tolist()==[20,10,2]
 assert app.checkbox(key='show_refinement_reference').value is False
 monkeypatch.setattr('geophotoloc.app.refinement_demo.load_reference_for_evaluation',lambda case:GeoPoint(latitude=31,longitude=121))
 app.checkbox(key='show_refinement_reference').check().run()
 assert not app.exception and any('只读评估' in c.value for c in app.caption)


def test_online_pipeline_refinement_uses_one_mock_request_and_shared_cache(extraction,photo,tmp_path):
 from geophotoloc.app.pipeline import LocalizationPipeline
 from geophotoloc.localization import Stage52PoseSolver
 from geophotoloc.models.pose import PoseSearchConfig
 from geophotoloc.maps import LandmarkStore
 from test_pose_solver import setup_scene
 from unittest.mock import Mock
 db=tmp_path/'maps.sqlite3'
 with LandmarkStore(db) as store:vision,_=setup_scene(extraction,photo,store)
 analyzer=Mock();analyzer.analyze_prepared.return_value=vision
 config=Stage52PoseSolver(None,PoseSearchConfig(max_total_points=120,max_points_per_hypothesis=120,record_diagnostic_trace=True)).config
 pipeline=LocalizationPipeline(db,analyzer=analyzer,search_config=config)
 first=pipeline.run(photo);again=pipeline.run(photo)
 assert analyzer.analyze_prepared.call_count==1 and again.cache_hit
 assert [s['stage'] for s in first.refinement['layers']]==['S0','S1','S2']
 assert first.refinement['layers'][0]['area_m2']>=first.refinement['layers'][2]['area_m2']>0
 assert 'reference' not in first.model_dump_json().lower()
