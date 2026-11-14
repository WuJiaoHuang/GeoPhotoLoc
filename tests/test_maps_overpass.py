from datetime import datetime, timezone
import json

import httpx
import pytest

from geophotoloc.maps import MapDataError, OverpassClient
from geophotoloc.maps.overpass import build_query
from geophotoloc.maps.regions import REGIONS
from geophotoloc.models.maps import GeoBounds


def test_query_requests_geometry_not_overriding_center_and_is_bounded():
    query = build_query(REGIONS["shanghai"])
    assert "out meta geom;" in query and "geom center" not in query
    assert "31.215,121.475,31.265,121.535" in query
    assert 'relation["type"="multipolygon"]' in query
    assert '[timeout:45]' in query and '[maxsize:33554432]' in query


@pytest.mark.parametrize("bounds", [
    dict(south=1, north=0, west=0, east=1), dict(south=0, north=1, west=0, east=1),
    dict(south=0, north=0.1, west=179.9, east=-179.9),
])
def test_unbounded_or_wrapping_regions_rejected(bounds):
    with pytest.raises(ValueError):
        GeoBounds(**bounds)


def test_http_success_cache_and_offline_no_network(tmp_path, osm_snapshot):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=osm_snapshot.payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = OverpassClient(tmp_path, client=http, sleep=lambda delay: None)
        first = client.fetch(REGIONS["shanghai"])
        second = client.fetch(REGIONS["shanghai"])
        offline = client.fetch(REGIONS["shanghai"], offline=True)
    assert len(requests) == 1 and first.cache_hit is False
    assert second.cache_hit and offline.fetched_at == first.fetched_at
    assert b"out+meta+geom" in requests[0].content
    assert "GeoPhotoLoc" in requests[0].headers["user-agent"]


@pytest.mark.parametrize("status", [429, 502, 503, 504])
def test_bounded_retry(tmp_path, status, osm_snapshot):
    requests, delays = [], []
    def handler(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(status, headers={"Retry-After": "0"})
        return httpx.Response(200, json=osm_snapshot.payload)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        client = OverpassClient(tmp_path, client=http, retries=1, sleep=delays.append)
        assert len(client.fetch(REGIONS["beijing"]).payload["elements"]) == 5
    assert len(requests) == 2 and delays == [0]


@pytest.mark.parametrize("error", [httpx.ReadTimeout, httpx.ConnectError])
def test_timeout_and_network_failures_no_cache(tmp_path, error):
    requests = []
    def handler(request):
        requests.append(request)
        raise error("network detail must not escape", request=request)
    with httpx.Client(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(MapDataError, match="no usable cache"):
            OverpassClient(tmp_path, client=http, retries=1, sleep=lambda delay: None).fetch(REGIONS["beijing"])
    assert len(requests) == 2


@pytest.mark.parametrize("payload", [{}, {"elements": [], "remark": "runtime error"}, []])
def test_error_payload_not_cached(tmp_path, payload):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))) as http:
        with pytest.raises(MapDataError):
            OverpassClient(tmp_path, client=http).fetch(REGIONS["beijing"])
    assert list(tmp_path.glob("*.json")) == []


def test_stale_cache_fallback_preserves_acquisition_timestamp(tmp_path, osm_snapshot):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=osm_snapshot.payload))) as http:
        first = OverpassClient(tmp_path, client=http).fetch(REGIONS["beijing"])
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503))) as http:
        fallback = OverpassClient(tmp_path, client=http, retries=0, cache_ttl_seconds=0).fetch(REGIONS["beijing"])
    assert fallback.stale and fallback.cache_hit and fallback.fetched_at == first.fetched_at


def test_offline_empty_cache_and_corrupt_cache(tmp_path):
    with pytest.raises(MapDataError, match="No valid cached"):
        OverpassClient(tmp_path).fetch(REGIONS["beijing"], offline=True)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"elements": []}))) as http:
        client = OverpassClient(tmp_path, client=http)
        client.fetch(REGIONS["beijing"])
        cache = next(tmp_path.glob("*.json"))
        cache.write_text("bad", encoding="utf-8")
        with pytest.raises(MapDataError, match="No valid cached"):
            client.fetch(REGIONS["beijing"], offline=True)
