import inspect
import json
from pathlib import Path
from unittest.mock import Mock

import httpx
import pytest
from shapely.geometry import box,mapping
from geophotoloc.app.setup import setup_demo,database_status
from geophotoloc.app.evaluation import evaluate_camera_location
from geophotoloc.app.demo_data import load_case
from geophotoloc.app.pipeline import LocalizationPipeline,validate_upload,PipelineFailure
from geophotoloc.maps import LandmarkStore,OverpassClient
from geophotoloc.models import GeoPoint,PoseConstraintScore,CandidateRegion
from geophotoloc.geometry.coordinates import LocalCoordinateSystem
from geophotoloc.localization.projection import to_wgs84_geometry


def test_setup_repeat_uses_existing_regions(tmp_path,osm_snapshot):
    requests=[]
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json=osm_snapshot.payload)
    path=tmp_path/'maps.sqlite3'
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client=OverpassClient(tmp_path/'cache',client=http)
        first=setup_demo(path,client=client)
        before=path.read_bytes()
        second=setup_demo(path,client=client)
    assert [x['status'] for x in first]==['imported']*3
    assert [x['status'] for x in second]==['reused']*3
    assert len(requests)==3 and path.read_bytes()==before
    assert set(database_status(path))=={'shanghai','beijing','guangzhou'}


def test_setup_overpass_failure_keeps_offline_usable(tmp_path):
    with httpx.Client(transport=httpx.MockTransport(lambda request:httpx.Response(503))) as http:
        result=setup_demo(tmp_path/'db.sqlite3',client=OverpassClient(tmp_path/'cache',client=http,retries=0))
    assert all(x['status']=='failed' for x in result)
    assert load_case('beijing_cbd').localization.regions


def test_corrupt_database_not_overwritten(tmp_path):
    path=tmp_path/'bad.sqlite3';path.write_bytes(b'not sqlite data')
    result=setup_demo(path)
    assert result[0]['status']=='failed' and path.read_bytes()==b'not sqlite data'


def test_camera_metrics_known_square():
    origin=GeoPoint(latitude=31.24,longitude=121.5)
    system=LocalCoordinateSystem(origin)
    geometry=mapping(to_wgs84_geometry(box(-50,-50,50,50),system))
    result=load_case('oriental_pearl').localization
    result.regions=[CandidateRegion(id='test',hypothesis_id='h',region_id='test',geometry=geometry,
                     best_location=origin,best_score=PoseConstraintScore(feasible=True,score=.5),
                     area_m2=10000,bounds_wgs84=(121.,31.,122.,32.),candidate_point_count=1,
                     assignments={'a':'osm:node:1','b':'osm:node:2'},heading=0,refined=True,
                     touches_search_boundary=False,uncertainty=['synthetic unit fixture'])]
    inside=evaluate_camera_location(result,origin)
    assert inside['truth_inside_any'] and inside['containing_ranks']==[1]
    assert inside['top1_point_distance_m']==0 and inside['nearest_region_distance_m']==0
    assert inside['top1_area_m2']==10000
    outside=evaluate_camera_location(result,system.to_geographic((100,0)))
    assert not outside['truth_inside_any']
    assert outside['top1_point_distance_m']==pytest.approx(100,abs=.05)
    assert outside['nearest_region_distance_m']==pytest.approx(50,abs=.05)


def test_empty_pose_no_fabricated_distances():
    metrics=evaluate_camera_location(load_case('oriental_pearl').localization,GeoPoint(latitude=31,longitude=121))
    assert metrics['candidate_regions']==0 and metrics['top1_point_distance_m'] is None
    assert metrics['nearest_region_distance_m'] is None


def test_truth_not_an_inference_argument():
    from geophotoloc.localization import PoseSolver
    assert set(inspect.signature(LocalizationPipeline.run).parameters)=={'self','image_path'}
    assert set(inspect.signature(PoseSolver.solve).parameters)=={'self','vision_result','map_matching_result'}
    from geophotoloc.app import pipeline
    assert 'camera_truth' not in inspect.getsource(pipeline)


def test_upload_validation_safe(photo):
    assert validate_upload(photo.read_bytes(),'anything.jpg').metadata.processed_size.width==120
    with pytest.raises(PipelineFailure):
        validate_upload(b'broken','anything.jpg')
    with pytest.raises(PipelineFailure,match='20 MiB'):
        validate_upload(b'a'*(20*1024*1024+1),'anything.jpg')


def test_demo_setup_cli(tmp_path,monkeypatch,capsys):
    from geophotoloc.cli import main
    monkeypatch.setattr('geophotoloc.app.setup.setup_demo',lambda *args,**kwargs:[{'region':'test','status':'reused'}])
    assert main(['demo-setup','--db',str(tmp_path/'db.sqlite3')])==0
    assert 'reused' in capsys.readouterr().out
