import pytest
from pydantic import ValidationError

from geophotoloc.config import GeometryConfig
from geophotoloc.models import (
    CandidatePose, GeoPoint, ImageLandmark, Landmark, LocalizationResult,
    LocalizationStatus, RelationType, SpatialRelation,
)


@pytest.mark.parametrize("kwargs", [
    {"latitude": 91, "longitude": 0}, {"latitude": -91, "longitude": 0},
    {"latitude": 0, "longitude": 181}, {"latitude": 0, "longitude": -181},
    {"latitude": float("nan"), "longitude": 0},
    {"latitude": 0, "longitude": float("inf")},
])
def test_invalid_geopoint(kwargs):
    with pytest.raises(ValidationError):
        GeoPoint(**kwargs)


@pytest.mark.parametrize("latitude,longitude", [(90, 180), (-90, -180), (0, 0)])
def test_coordinate_boundaries(latitude, longitude):
    assert GeoPoint(latitude=latitude, longitude=longitude).model_dump() == {
        "latitude": latitude, "longitude": longitude,
    }


@pytest.mark.parametrize("field,value", [
    ("x", -0.1), ("x", 1.1), ("y", -0.1), ("y", 1.1),
    ("confidence", -0.1), ("confidence", 1.1), ("x", float("nan")),
])
def test_invalid_image_measurements(field, value):
    data = {"name": "Tower", "x": 0, "y": 1, field: value}
    with pytest.raises(ValidationError):
        ImageLandmark(**data)


@pytest.mark.parametrize("field,value", [
    ("heading", -1), ("heading", 360), ("score", float("inf")),
    ("matched_constraints", -1), ("matched_constraints", 1.5),
])
def test_invalid_pose(field, value):
    data = dict(location=GeoPoint(latitude=0, longitude=0), score=1, matched_constraints=1)
    data[field] = value
    with pytest.raises(ValidationError):
        CandidatePose(**data)


def test_model_defaults_and_json_round_trip():
    point = GeoPoint(latitude=31.23, longitude=121.47)
    first = Landmark(id="a", name="Tower", location=point)
    second = Landmark(id="b", name="Bridge", location=point, osm_id=123)
    first.aliases.append("Old Tower")
    assert second.aliases == []
    observation = ImageLandmark(name="Tower", x=0, y=1)
    assert observation.confidence is None
    assert observation.matched_landmark_id is None
    relation = SpatialRelation(subject_id="a", object_id="b", relation_type="LEFT_OF")
    assert relation.relation_type is RelationType.LEFT_OF
    pose = CandidatePose(location=point, score=0.8, matched_constraints=2)
    assert pose.heading is None
    result = LocalizationResult(candidates=[pose], status="AMBIGUOUS", explanation="Order only")
    assert LocalizationResult.model_validate_json(result.model_dump_json()) == result
    assert result.status is LocalizationStatus.AMBIGUOUS


@pytest.mark.parametrize("status", list(LocalizationStatus))
def test_result_statuses(status):
    assert LocalizationResult(status=status, explanation="Stage 1").candidates == []


def test_invalid_enums_and_relation_confidence():
    with pytest.raises(ValidationError):
        LocalizationResult(status="UNKNOWN", explanation="")
    with pytest.raises(ValidationError):
        SpatialRelation(subject_id="a", object_id="b", relation_type="UNKNOWN")
    with pytest.raises(ValidationError):
        SpatialRelation(subject_id="a", object_id="b", relation_type="LEFT_OF", confidence=2)


@pytest.mark.parametrize("kwargs", [
    {"distance_tolerance_m": 0}, {"angular_tolerance_deg": 90},
    {"angular_tolerance_deg": float("nan")},
])
def test_invalid_tolerances(kwargs):
    with pytest.raises(ValidationError):
        GeometryConfig(**kwargs)
