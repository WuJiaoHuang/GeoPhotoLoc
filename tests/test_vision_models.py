import copy
import json

from pydantic import ValidationError
import pytest

from geophotoloc.models import ImageLandmark, VisionExtractionResult
from geophotoloc.models.vision import VisionResponse
from geophotoloc.vision import VisionResponseError, prepare_image
from geophotoloc.vision.client import parse_response
from geophotoloc.vision.relations import extract_relations


def test_strict_response_and_backward_compatibility(extraction):
    parsed = parse_response(json.dumps(extraction))
    assert isinstance(parsed.landmarks[0], ImageLandmark)
    assert parsed.landmarks[0].id == "lm_1"
    assert parsed.landmarks[0].bbox.x_max == pytest.approx(0.3)
    assert parsed.landmarks[0].identity_uncertain is True
    assert ImageLandmark(name="Legacy", x=0.2, y=0.3).id is None


@pytest.mark.parametrize("content", [
    "", "not json", '{"landmarks":', "[]", "null",
    '{"landmarks":[],"landmarks":[],"scene_features":[],"warnings":[]}',
    '{"landmarks":[],"scene_features":[],"warnings":[],"extra":NaN}',
])
def test_bad_json(content):
    with pytest.raises(VisionResponseError):
        parse_response(content)


def test_json_fence(extraction):
    assert len(parse_response("```json\n" + json.dumps(extraction) + "\n```").landmarks) == 2


@pytest.mark.parametrize("field,value", [
    ("id", ""), ("id", "contains spaces"), ("x", -0.1), ("y", 1.1),
    ("x", "0.2"), ("x", True), ("confidence", 2), ("name", " "),
    ("coordinates_reliable", "true"), ("visual_evidence", []),
    ("name_candidates", [""]), ("matched_landmark_id", "osm-123"),
])
def test_landmark_validation(extraction, field, value):
    extraction["landmarks"][0][field] = value
    with pytest.raises(VisionResponseError):
        parse_response(json.dumps(extraction))


@pytest.mark.parametrize("box", [
    dict(x_min=0.5, y_min=0.2, x_max=0.1, y_max=0.5),
    dict(x_min=0.1, y_min=0.2, x_max=0.1, y_max=0.5),
    dict(x_min=-0.1, y_min=0.2, x_max=0.3, y_max=0.5),
    dict(x_min=0.4, y_min=0.4, x_max=0.5, y_max=0.5),
    dict(x_min=0.1, y_min=0.2, x_max=0.3, y_max=1.1),
])
def test_invalid_boxes(extraction, box):
    extraction["landmarks"][0]["bbox"] = box
    with pytest.raises(VisionResponseError):
        parse_response(json.dumps(extraction))


def test_duplicate_ids_and_extra_fields(extraction):
    duplicate = copy.deepcopy(extraction)
    duplicate["landmarks"][1]["id"] = duplicate["landmarks"][0]["id"]
    with pytest.raises(VisionResponseError):
        parse_response(json.dumps(duplicate))
    extraction["invented_location"] = "somewhere"
    with pytest.raises(VisionResponseError):
        parse_response(json.dumps(extraction))


def test_relations_and_reciprocity(extraction):
    landmarks = parse_response(json.dumps(extraction)).landmarks
    relations = extract_relations(landmarks)
    actual = {(r.subject_id, r.object_id, r.relation_type.value) for r in relations}
    assert actual == {
        ("lm_1", "lm_2", "LEFT_OF"), ("lm_2", "lm_1", "RIGHT_OF"),
        ("lm_1", "lm_2", "ABOVE"), ("lm_2", "lm_1", "BELOW"),
    }
    assert all(r.confidence is None for r in relations)


@pytest.mark.parametrize("gap", [0, 0.01, 0.03])
@pytest.mark.parametrize("offset", [0, 0.2])
def test_nearby_centers_no_relation(extraction, gap, offset):
    # Valid boxes covering both centers; identity and apparent size are irrelevant.
    for index, item in enumerate(extraction["landmarks"]):
        item.update(x=offset + index * gap, y=0.5,
                    bbox=dict(x_min=0., y_min=0., x_max=1., y_max=1.))
    assert extract_relations(parse_response(json.dumps(extraction)).landmarks) == []


def test_unreliable_coordinates_excluded(extraction):
    extraction["landmarks"][0]["coordinates_reliable"] = False
    assert extract_relations(parse_response(json.dumps(extraction)).landmarks) == []


@pytest.mark.parametrize("gap", [-1, 0, 1, float("nan")])
def test_invalid_relation_threshold(extraction, gap):
    with pytest.raises(ValueError):
        extract_relations(parse_response(json.dumps(extraction)).landmarks, gap)


@pytest.mark.parametrize("relation", [
    dict(subject_id="unknown", object_id="lm_2", relation_type="LEFT_OF"),
    dict(subject_id="lm_1", object_id="lm_1", relation_type="LEFT_OF"),
    dict(subject_id="lm_1", object_id="lm_2", relation_type="RIGHT_OF"),
    dict(subject_id="lm_1", object_id="lm_2", relation_type="BELOW"),
])
def test_invalid_relation_references_or_direction(extraction, photo, relation):
    data = dict(extraction, image=prepare_image(photo).metadata.model_dump(), relations=[relation])
    with pytest.raises(ValidationError):
        VisionExtractionResult.model_validate_json(json.dumps(data))


def test_result_roundtrip_and_duplicate_relation(extraction, photo):
    response = VisionResponse.model_validate_json(json.dumps(extraction))
    result = VisionExtractionResult(
        **response.model_dump(exclude={"landmarks"}), landmarks=response.landmarks,
        image=prepare_image(photo).metadata, relations=extract_relations(response.landmarks),
    )
    assert VisionExtractionResult.model_validate_json(result.model_dump_json()) == result
    data = json.loads(result.model_dump_json())
    data["relations"].append(data["relations"][0])
    with pytest.raises(ValidationError, match="Duplicate relation"):
        VisionExtractionResult.model_validate_json(json.dumps(data))
