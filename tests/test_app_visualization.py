import json
from io import BytesIO
from pathlib import Path
from PIL import Image
import pytest
from geophotoloc.app.demo_data import load_case,CASES
from geophotoloc.app.visualization import annotate_image,build_map,download_payloads
from geophotoloc.models import VisionExtractionResult
from geophotoloc.vision import prepare_image


@pytest.mark.parametrize('case',list(CASES.values()))
def test_offline_case_without_network_or_database(case,monkeypatch):
    def no_network(*args,**kwargs):
        pytest.fail('Offline mode attempted network/database')
    monkeypatch.setattr('socket.create_connection',no_network)
    monkeypatch.setattr('sqlite3.connect',no_network)
    result=load_case(case)
    html=build_map(result,offline=True,sightlines=True).get_root().render()
    assert 'OpenStreetMap contributors' in html
    assert 'src="https://' not in html and 'href="https://cdn' not in html
    assert 'tile.openstreetmap.org' not in html
    assert len(result.localization.regions)=={'beijing_cbd':2,'guangzhou_skyline':8,'oriental_pearl':0}[case]
    if case=='oriental_pearl':
        assert '搜索代表点' not in html
    else:
        assert result.localization.regions[-1].id in html
    payloads=download_payloads(result)
    assert json.loads(payloads['geojson'])==result.localization.geojson
    assert json.loads(payloads['json'])['mode']=='offline'
    with Image.open(BytesIO(payloads['annotated_png'])) as image:
        assert image.size==(result.vision.image.processed_size.width,result.vision.image.processed_size.height)


def test_annotation_exif_alignment(tmp_path):
    import base64
    image=Image.new('RGB',(120,60),'white');exif=Image.Exif();exif[274]=6
    path=tmp_path/'rotated.jpg';image.save(path,exif=exif)
    prepared=prepare_image(path)
    data=base64.b64decode(prepared.data_url.split(',',1)[1])
    result=load_case('oriental_pearl')
    result.vision.image=prepared.metadata
    landmark=result.vision.landmarks[0]
    landmark.x=.5;landmark.y=.5
    landmark.bbox=landmark.bbox.model_copy(update={'x_min':.2,'x_max':.8,'y_min':.4,'y_max':.8})
    output=annotate_image(data,result.vision)
    with Image.open(BytesIO(output)) as rendered:
        assert rendered.size==(60,120)
        assert rendered.getpixel((12,70))!=(255,255,255)


def test_map_names_are_escaped():
    result=load_case('oriental_pearl')
    result.matching.matches[0].candidates[0].entity.name='<script>evil_marker()</script>'
    html=build_map(result).get_root().render()
    assert '<script>evil_marker()</script>' not in html


def test_annotation_size_mismatch():
    result=load_case('oriental_pearl')
    result.vision.image.processed_size.width+=1
    with pytest.raises(ValueError):
        annotate_image(result.processed_jpeg,result.vision)
