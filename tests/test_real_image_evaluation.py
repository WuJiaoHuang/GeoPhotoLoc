"""Offline evaluation must not turn uncertain candidates into confirmed identities."""

import importlib.util
import json
from pathlib import Path

import pytest

from geophotoloc.models import VisionExtractionResult
from geophotoloc.models.vision import VisionResponse
from geophotoloc.vision import prepare_image
from geophotoloc.vision.relations import extract_relations

spec = importlib.util.spec_from_file_location(
    "real_image_comparison", Path(__file__).resolve().parents[1] / "scripts/compare_real_images.py",
)
comparison = importlib.util.module_from_spec(spec)
spec.loader.exec_module(comparison)


def fixture_data(extraction, photo):
    references = [{"id": "ref_a", "name": "Alpha Tower", "aliases": [],
                   "bbox": extraction["landmarks"][0]["bbox"]},
                  {"id": "ref_b", "name": "Beta Bridge", "aliases": [],
                   "bbox": extraction["landmarks"][1]["bbox"]}]
    sample = {"id": "test", "landmarks": references, "relations": [
        {"subject_id": "ref_a", "object_id": "ref_b", "relation_type": "LEFT_OF"},
    ]}
    parsed = VisionResponse.model_validate_json(json.dumps(extraction))
    result = VisionExtractionResult(
        landmarks=parsed.landmarks, scene_features=[], warnings=[], image=prepare_image(photo).metadata,
        relations=extract_relations(parsed.landmarks),
    )
    return sample, result


def test_generic_identity_does_not_hide_correct_geometry(extraction, photo):
    extraction["landmarks"][0].update(name="Unidentified structure", name_candidates=["Alpha Tower"])
    extraction["landmarks"][1].update(name="Unknown bridge-like object", name_candidates=[])
    sample, result = fixture_data(extraction, photo)
    report = comparison.compare_sample(sample, result, {"correspondences": {"ref_a": "lm_1", "ref_b": "lm_2"}})
    assert report["targets"][0]["primary_name_match"] is False
    assert report["targets"][0]["identity_outcome"] == "correct_candidate_only"
    assert report["targets"][1]["identity_outcome"] == "generic_detection_without_identity"
    assert report["targets"][0]["box_iou"] == 1
    assert report["reference_relations"][0]["outcome"] == "correct"


def test_candidate_at_wrong_object_does_not_recover_missing_target(extraction, photo):
    extraction["landmarks"][0]["name_candidates"] = ["Beta Bridge"]
    sample, result = fixture_data(extraction, photo)
    report = comparison.compare_sample(sample, result, {"correspondences": {"ref_a": "lm_1", "ref_b": None}})
    assert report["targets"][1]["identity_outcome"] == "missed_object"
    assert report["targets"][1]["candidate_name_only_ids"] == ["lm_1"]
    assert report["reference_relations"][0]["outcome"] == "unscorable_missing_object"


@pytest.mark.parametrize("mapping", [
    {"ref_a": "lm_1", "ref_b": "lm_1"},
    {"ref_a": "missing", "ref_b": "lm_2"},
    {"ref_a": "lm_1"},
])
def test_invalid_manual_correspondences(extraction, photo, mapping):
    sample, result = fixture_data(extraction, photo)
    with pytest.raises(ValueError):
        comparison.compare_sample(sample, result, {"correspondences": mapping})
