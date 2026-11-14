import base64
from pathlib import Path
from unittest.mock import Mock

import pytest
from geophotoloc.app.pipeline import LocalizationPipeline,PipelineFailure,api_error_message
from geophotoloc.maps import LandmarkStore,MapMatcher,parse_snapshot
from geophotoloc.maps.regions import REGIONS
from geophotoloc.config import VisionConfig
from geophotoloc.vision import VisionAPIError
from test_maps_matching import vision_input


def configured_db(tmp_path,snapshot):
    db=tmp_path/'maps.sqlite3'
    with LandmarkStore(db) as store:
        store.import_entities(parse_snapshot(snapshot,'shanghai').entities,'shanghai',REGIONS['shanghai'],{})
    return db


def test_pipeline_actual_stages_and_cache(extraction,photo,tmp_path,osm_snapshot):
    db=configured_db(tmp_path,osm_snapshot)
    analyzer=Mock()
    analyzer.analyze_prepared.return_value=vision_input(extraction,photo,['Alpha Tower'])
    pipeline=LocalizationPipeline(db,analyzer=analyzer)
    one=pipeline.run(photo);two=pipeline.run(photo)
    assert analyzer.analyze_prepared.call_count==1
    assert one.vision.landmarks[0].id=='lm_1'
    assert one.matching.matches[0].candidates[0].entity.id=='osm:node:1'
    assert one.localization.status=='INSUFFICIENT_EVIDENCE'
    assert two.cache_hit and one.processed_jpeg.startswith(b'\xff\xd8')
    assert 'processed_jpeg' not in one.model_dump()
    pipeline.search_config=pipeline.search_config.model_copy(update={'max_total_points':100})
    changed=pipeline.run(photo)
    assert changed.localization.config.max_total_points==100
    assert changed.vision_cache_hit and not changed.cache_hit
    assert analyzer.analyze_prepared.call_count==1


def test_pipeline_mock_http_api(mock_api,extraction,photo,tmp_path,osm_snapshot):
    db=configured_db(tmp_path,osm_snapshot)
    analyzer,requests=mock_api(extraction)
    result=LocalizationPipeline(db,analyzer=analyzer).run(photo)
    assert len(requests)==1 and len(result.vision.landmarks)==2


def test_missing_database_prevents_paid_request(photo,tmp_path):
    analyzer=Mock()
    with pytest.raises(PipelineFailure) as caught:
        LocalizationPipeline(tmp_path/'missing.sqlite3',analyzer=analyzer).run(photo)
    assert caught.value.code=='DB_MISSING' and not analyzer.analyze_prepared.called


def test_missing_key(photo,tmp_path,osm_snapshot,monkeypatch):
    db=configured_db(tmp_path,osm_snapshot)
    def missing():
        from geophotoloc.config import ConfigurationError
        raise ConfigurationError('secret-test-marker')
    monkeypatch.setattr(VisionConfig,'from_env',missing)
    with pytest.raises(PipelineFailure) as caught:
        LocalizationPipeline(db).run(photo)
    assert caught.value.code=='KEY_MISSING' and 'secret-test-marker' not in str(caught.value)


@pytest.mark.parametrize('message,code',[('request timed out','API_TIMEOUT'),('rate limit','API_LIMIT'),
    ('authentication failed','API_AUTH'),('HTTP 402','API_ACCOUNT'),('HTTP 403','API_ACCOUNT'),('cannot connect','API_NETWORK')])
def test_api_failures_safe(photo,tmp_path,osm_snapshot,message,code):
    analyzer=Mock();analyzer.analyze_prepared.side_effect=VisionAPIError(message+' secret-test-marker')
    with pytest.raises(PipelineFailure) as caught:
        LocalizationPipeline(configured_db(tmp_path,osm_snapshot),analyzer=analyzer).run(photo)
    assert caught.value.code==code and 'secret-test-marker' not in str(caught.value)


def test_invalid_image(tmp_path):
    path=tmp_path/'bad.jpg';path.write_bytes(b'not an image')
    with pytest.raises(PipelineFailure) as caught:
        LocalizationPipeline(tmp_path/'db').run(path)
    assert caught.value.stage=='image'
