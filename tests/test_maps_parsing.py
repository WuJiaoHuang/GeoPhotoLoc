from datetime import datetime, timezone
import json
from pathlib import Path

import pytest
from shapely.geometry import Point, shape

from geophotoloc.maps.overpass import OverpassSnapshot
from geophotoloc.maps.parsing import parse_snapshot


@pytest.fixture
def osm_payload():
    return json.loads((Path(__file__).parent / "fixtures/osm_sample.json").read_text(encoding="utf-8"))


def snapshot(payload):
    return OverpassSnapshot(payload, "https://example.test/overpass", datetime(2026, 11, 1, tzinfo=timezone.utc), "fixture", False)


def test_nodes_names_tags_and_real_axes(osm_payload):
    result = parse_snapshot(snapshot(osm_payload), "test")
    node = result.entities[0]
    assert node.osm_id == 1 and node.osm_type == "node"
    assert node.location.latitude == 31.24 and node.location.longitude == 121.50
    assert node.geometry == {"type": "Point", "coordinates": (121.50, 31.24)}
    assert node.geometry_precision == "node" and node.complete_geometry
    assert {"测试甲塔", "Alpha Tower", "Alpha Spire", "Alpha Official Tower", "Alpha"} <= set(node.aliases)
    assert node.names["name:en"] == "Alpha Tower"
    assert node.tags["wikidata"] == "Q100001" and node.tags["height"] == "300"
    assert node.category == "tower"
    assert node.osm_updated_at == "2026-10-01T00:00:00Z"


def test_footprint_and_representative_point(osm_payload):
    entity = parse_snapshot(snapshot(osm_payload), "test").entities[1]
    polygon = shape(entity.geometry)
    assert polygon.geom_type == "Polygon" and polygon.area == pytest.approx(0.000001)
    assert polygon.covers(Point(entity.location.longitude, entity.location.latitude))
    assert entity.geometry_precision == "complete_outline" and entity.complete_geometry
    assert "not an entrance" in entity.coordinate_meaning


def test_multipolygon_with_joined_outer_and_inner_hole(osm_payload):
    entity = parse_snapshot(snapshot(osm_payload), "test").entities[2]
    polygon = shape(entity.geometry)
    assert polygon.geom_type == "Polygon"
    assert len(polygon.interiors) == 1
    assert polygon.area == pytest.approx(0.000003)
    assert not polygon.covers(Point(121.504, 31.244))
    assert polygon.covers(Point(entity.location.longitude, entity.location.latitude))
    assert entity.complete_geometry and entity.geometry_precision == "complete_outline"


def test_missing_name_and_center_only_precision(osm_payload):
    entities = parse_snapshot(snapshot(osm_payload), "test").entities
    assert entities[3].name == "Center Only Building"
    assert entities[3].geometry_precision == "representative_point"
    assert entities[3].complete_geometry is False
    assert "overpass_bbox_center_only" in entities[3].coordinate_meaning
    assert entities[4].aliases == [] and entities[4].name == "[unnamed node 5]"


def test_duplicate_osm_id_and_missing_coordinates(osm_payload):
    osm_payload["elements"].extend([
        {"type": "node", "id": 1, "tags": {"short_name": "A Tower"}},
        {"type": "node", "id": 90}, {"type": "way", "id": True},
    ])
    parsed = parse_snapshot(snapshot(osm_payload), "test")
    assert len(parsed.entities) == 5
    assert parsed.entities[0].names["short_name"] == "A Tower"
    assert len(parsed.warnings) == 2


def test_incomplete_building_does_not_bridge_missing_geometry():
    raw = {"elements": [{"type": "way", "id": 10, "tags": {"building": "yes"},
                         "geometry": [{"lat": 1, "lon": 2}, {"lat": 1, "lon": 3}, None,
                                      {"lat": 2, "lon": 3}, {"lat": 2, "lon": 2}]}]}
    entity = parse_snapshot(snapshot(raw), "test").entities[0]
    assert entity.geometry_precision == "partial_geometry" and not entity.complete_geometry
    assert len(shape(entity.geometry).geoms) == 2


def test_way_node_references_and_linear_closed_road():
    raw = {"elements": [
        {"type": "node", "id": 11, "lat": 1, "lon": 2},
        {"type": "node", "id": 12, "lat": 1, "lon": 3},
        {"type": "node", "id": 13, "lat": 2, "lon": 3},
        {"type": "way", "id": 14, "nodes": [11, 12, 13, 11], "tags": {"highway": "residential"}},
    ]}
    entity = parse_snapshot(snapshot(raw), "test").entities[-1]
    assert shape(entity.geometry).geom_type == "LineString" and entity.category == "road"


@pytest.mark.parametrize("coordinate", [{"lat": 91, "lon": 0}, {"lat": 1, "lon": 181}, {"lat": True, "lon": 1}])
def test_invalid_geographic_coordinates(coordinate):
    parsed = parse_snapshot(snapshot({"elements": [{"type": "node", "id": 1, **coordinate}]}), "test")
    assert parsed.entities == []
    assert len(parsed.warnings) == 1


def test_transport_category_and_wikipedia_title_alias():
    raw = {"elements": [{"type": "node", "id": 8, "lat": 31, "lon": 121,
                         "tags": {"name": "测试塔", "railway": "station", "wikipedia": "en:Test_Tower_station"}}]}
    entity = parse_snapshot(snapshot(raw), "test").entities[0]
    assert entity.category == "transport"
    assert "Test Tower station" in entity.aliases


def test_invalid_tag_fields_and_partial_duplicate_do_not_crash_or_erase_geometry(osm_payload):
    osm_payload["elements"].append({"type": "node", "id": 20, "lat": 31, "lon": 121, "tags": ["bad"]})
    osm_payload["elements"].append({"type": "way", "id": 2, "geometry": [], "tags": {"name:en": None}})
    parsed = parse_snapshot(snapshot(osm_payload), "test")
    assert len(parsed.entities) == 6
    assert parsed.entities[1].geometry_precision == "complete_outline"
    assert parsed.entities[-1].aliases == []
