"""Offline diagnostics against pre-recorded references; never calls a model.

Correspondences come from explicit manual inspection, not name-only matching.
Only explicit reference pairs are scored; inverse edges are not double counted.
"""

import hashlib
import json
from math import hypot
from pathlib import Path
import unicodedata

from geophotoloc.models import VisionExtractionResult

ROOT = Path(__file__).resolve().parents[1] / "docs/evaluation/stage2_1"


def normalized(text):
    return "".join(character for character in unicodedata.normalize("NFKC", text).casefold()
                   if character.isalnum())


def name_matches(name, reference):
    actual = normalized(name)
    return any(normalized(alias) in actual for alias in [reference["name"], *reference["aliases"]])


def box_iou(a, b):
    intersection = (max(0, min(a["x_max"], b["x_max"]) - max(a["x_min"], b["x_min"]))
                    * max(0, min(a["y_max"], b["y_max"]) - max(a["y_min"], b["y_min"])))
    area_a = (a["x_max"] - a["x_min"]) * (a["y_max"] - a["y_min"])
    area_b = (b["x_max"] - b["x_min"]) * (b["y_max"] - b["y_min"])
    return intersection / (area_a + area_b - intersection)


def compare_sample(sample, result, review):
    targets = []
    matched = {}
    by_id = {item.id: item for item in result.landmarks}
    correspondences = review["correspondences"]
    if set(correspondences) != {reference["id"] for reference in sample["landmarks"]}:
        raise ValueError("Review must cover exactly the pre-recorded reference targets")
    assigned = [identifier for identifier in correspondences.values() if identifier is not None]
    if len(assigned) != len(set(assigned)) or any(identifier not in by_id for identifier in assigned):
        raise ValueError("Review correspondences must be one-to-one and refer to existing model IDs")
    for reference in sample["landmarks"]:
        model_id = correspondences[reference["id"]]
        prediction = by_id.get(model_id)
        target = {"reference_id": reference["id"], "reference_name": reference["name"],
                  "primary_name_match": bool(prediction and name_matches(prediction.name, reference))}
        if prediction is not None:
            matched[reference["id"]] = prediction.id
            candidate_matches = [name for name in prediction.name_candidates if name_matches(name, reference)]
            if target["primary_name_match"]:
                target["identity_outcome"] = "correct_primary_name"
            elif candidate_matches:
                target["identity_outcome"] = ("correct_candidate_with_alternatives"
                                              if len(candidate_matches) < len(prediction.name_candidates)
                                              else "correct_candidate_only")
            else:
                target["identity_outcome"] = "generic_detection_without_identity"
            target["matching_candidates"] = candidate_matches
            bbox = reference["bbox"]
            cx, cy = (bbox["x_min"] + bbox["x_max"]) / 2, (bbox["y_min"] + bbox["y_max"]) / 2
            target.update(
                model_id=prediction.id, model_name=prediction.name,
                model_identity_uncertain=prediction.identity_uncertain,
                model_coordinates_reliable=prediction.coordinates_reliable,
                center={"x": prediction.x, "y": prediction.y},
                model_bbox=prediction.bbox.model_dump(),
                reference_bbox=bbox,
                box_iou=round(box_iou(bbox, prediction.bbox.model_dump()), 4),
                center_error=round(hypot(prediction.x - cx, prediction.y - cy), 4),
                center_in_reference_box=(bbox["x_min"] <= prediction.x <= bbox["x_max"]
                                         and bbox["y_min"] <= prediction.y <= bbox["y_max"]),
            )
        else:
            target["identity_outcome"] = "missed_object"
            target["candidate_name_only_ids"] = [item.id for item in result.landmarks
                                                 if any(name_matches(name, reference)
                                                        for name in item.name_candidates)]
        targets.append(target)
    actual = {(item.subject_id, item.object_id, item.relation_type.value) for item in result.relations}
    inverses = {"LEFT_OF": "RIGHT_OF", "RIGHT_OF": "LEFT_OF", "ABOVE": "BELOW", "BELOW": "ABOVE"}
    relations = []
    for expected in sample["relations"]:
        entry = dict(expected)
        subject, obj = matched.get(expected["subject_id"]), matched.get(expected["object_id"])
        if subject is None or obj is None:
            entry["outcome"] = "unscorable_missing_object"
        else:
            kind = expected["relation_type"]
            if (subject, obj, kind) in actual:
                entry["outcome"] = "correct"
            elif (subject, obj, inverses[kind]) in actual:
                entry["outcome"] = "opposite"
            else:
                entry["outcome"] = "not_emitted"
            entry["model_subject_id"], entry["model_object_id"] = subject, obj
        relations.append(entry)
    return dict(
        sample_id=sample["id"], model_landmarks=len(result.landmarks),
        model_directed_relations=len(result.relations), targets=targets,
        reference_relations=relations,
        unscored_model_ids=[item.id for item in result.landmarks if item.id not in matched.values()],
    )


def main():
    truth_path = ROOT / "ground_truth.json"
    truth = json.loads(truth_path.read_text(encoding="utf-8"))
    review = json.loads((ROOT / "manual_review.json").read_text(encoding="utf-8"))
    samples = []
    missing = []
    for sample in truth["samples"]:
        result_path = ROOT / "results" / f"{sample['id']}.json"
        if not result_path.exists():
            missing.append(sample["id"])
            continue
        result = VisionExtractionResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        samples.append(compare_sample(sample, result, review["samples"][sample["id"]]))
    targets = [target for sample in samples for target in sample["targets"]]
    pairs = [pair for sample in samples for pair in sample["reference_relations"]]
    summary = dict(
        reference_samples=len(truth["samples"]), completed_samples=len(samples),
        missing_results=missing,
        reference_targets=sum(len(sample["landmarks"]) for sample in truth["samples"]),
        primary_name_matches=sum(target["primary_name_match"] for target in targets),
        correct_candidate_only=sum(target["identity_outcome"] == "correct_candidate_only" for target in targets),
        correct_candidate_with_alternatives=sum(target["identity_outcome"] == "correct_candidate_with_alternatives" for target in targets),
        generic_detection_without_identity=sum(target["identity_outcome"] == "generic_detection_without_identity" for target in targets),
        missed_objects=sum(target["identity_outcome"] == "missed_object" for target in targets),
        localized_reference_objects=sum("model_id" in target for target in targets),
        localized_at_iou_0_5=sum(target.get("box_iou", 0) >= 0.5 for target in targets),
        centers_in_reference_box=sum(target.get("center_in_reference_box", False) for target in targets),
        reference_pairs=sum(len(sample["relations"]) for sample in truth["samples"]),
        correct_pairs=sum(pair["outcome"] == "correct" for pair in pairs),
        opposite_pairs=sum(pair["outcome"] == "opposite" for pair in pairs),
        not_emitted_pairs=sum(pair["outcome"] == "not_emitted" for pair in pairs),
        unscorable_pairs=sum(pair["outcome"] == "unscorable_missing_object" for pair in pairs),
    )
    report = dict(
        notes="Small-sample diagnostics only. Correspondences use explicit manual visual review against pre-recorded reference boxes. Generic detections and tentative candidates are not confirmed identities. Additional model objects and unlisted relations are not included in reference semantic scores.",
        ground_truth_sha256=hashlib.sha256(truth_path.read_bytes()).hexdigest(),
        summary=summary, samples=samples,
    )
    (ROOT / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
