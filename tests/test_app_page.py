from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest

APP=Path(__file__).resolve().parents[1]/'src/geophotoloc/app/main.py'


def test_streamlit_offline_cases_render_and_rerun(monkeypatch):
    def no_network(*args,**kwargs):
        pytest.fail('Offline page must not call services')
    monkeypatch.setattr('httpx.Client.send',no_network)
    monkeypatch.setattr('sqlite3.connect',no_network)
    app=AppTest.from_file(str(APP),default_timeout=40).run()
    assert not app.exception
    assert any('离线复现实验结果' in item.value for item in app.info)
    assert len(app.get('download_button'))==3
    app.selectbox(key='case').set_value('广州天际线').run()
    assert not app.exception and any('SEARCH_LIMITED' in item.value for item in app.caption)
    app.selectbox(key='case').set_value('上海东方明珠').run()
    assert not app.exception and any('INSUFFICIENT_EVIDENCE' in item.value for item in app.caption)
    app.run()
    assert not app.exception


def test_streamlit_online_missing_key_no_request(monkeypatch):
    from geophotoloc.config import ConfigurationError
    def missing():
        raise ConfigurationError('secret-test-marker')
    monkeypatch.setattr('geophotoloc.config.VisionConfig.from_env',missing)
    app=AppTest.from_file(str(APP),default_timeout=40).run()
    app.radio(key='mode').set_value('在线定位').run()
    assert not app.exception
    assert any('尚未配置' in item.value for item in app.warning)
    assert all('secret-test-marker' not in item.value for item in app.warning)


@pytest.mark.parametrize('empty_vision',[False,True])
def test_streamlit_failure_states_without_tracebacks(monkeypatch,empty_vision):
    from geophotoloc.app.demo_data import load_case
    result=load_case('beijing_cbd')
    result.localization.regions=[]
    result.localization.geojson={'type':'FeatureCollection','features':[]}
    result.localization.status='NO_FEASIBLE_POSE'
    if empty_vision:
        result.vision.landmarks=[];result.vision.relations=[]
        result.matching.matches=[];result.matching.region_hypotheses=[]
        result.localization.status='INSUFFICIENT_EVIDENCE'
    monkeypatch.setattr('geophotoloc.app.demo_data.load_case',lambda case:result.model_copy(deep=True))
    app=AppTest.from_file(str(APP),default_timeout=40).run()
    assert not app.exception
    expected='没有提取' if empty_vision else '未找到可行采样'
    assert any(expected in item.value for item in app.warning)


def test_streamlit_setup_failure_survives_rerun(monkeypatch):
    monkeypatch.setattr('geophotoloc.app.setup.database_status',lambda path:[])
    monkeypatch.setattr('geophotoloc.app.setup.setup_demo',lambda path:[{'region':'test','status':'failed','message':'地图初始化失败，可继续离线演示。'}])
    app=AppTest.from_file(str(APP),default_timeout=40).run()
    app.radio(key='mode').set_value('在线定位').run()
    next(button for button in app.button if button.label=='初始化三个演示区域地图').click().run()
    assert not app.exception
    assert any('初始化失败' in error.value for error in app.error)
