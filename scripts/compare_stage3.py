"""Independent offline review of already-saved results, never an inference input."""

import hashlib
import json
from pathlib import Path

from geophotoloc.models import VisionExtractionResult
from geophotoloc.models.maps import MapLandmark, MapMatchingResult

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "docs/evaluation/stage3"


def same_identity(actual, expected):
    return actual.id == expected.id or (
        actual.tags.get("wikidata") and actual.tags.get("wikidata") == expected.tags.get("wikidata")
    )


def main():
    review = json.loads((ROOT / "docs/evaluation/stage2_1/manual_review.json").read_text(encoding="utf-8"))
    references = json.loads((DATA / "reference_entities.json").read_text(encoding="utf-8"))["entities"]
    input_hashes = json.loads((DATA / "vision_input_hashes.json").read_text(encoding="utf-8"))
    records = []
    missing_visual_objects = []
    for sample_id, sample in review["samples"].items():
        input_path = ROOT / f"docs/evaluation/stage2_1/results/{sample_id}.json"
        assert hashlib.sha256(input_path.read_bytes()).hexdigest() == input_hashes[input_path.name]
        vision = VisionExtractionResult.model_validate_json(input_path.read_text(encoding="utf-8"))
        images = {item.id: item for item in vision.landmarks}
        result = MapMatchingResult.model_validate_json((DATA / f"{sample_id}_matches.json").read_text(encoding="utf-8"))
        matches = {item.image_landmark_id: item for item in result.matches}
        for reference_id, image_id in sample["correspondences"].items():
            if image_id is None:
                missing_visual_objects.append({"sample_id": sample_id, "reference_id": reference_id})
                continue
            expected = MapLandmark.model_validate(references[reference_id])
            candidates = matches[image_id].candidates
            correct_ranks = [rank for rank, candidate in enumerate(candidates, start=1)
                             if same_identity(candidate.entity, expected)]
            records.append({
                "sample_id": sample_id, "reference_id": reference_id, "image_id": image_id,
                "visual_name": images[image_id].name, "visual_candidates": images[image_id].name_candidates,
                "expected_entity_id": expected.id, "expected_name": expected.name,
                "top1_entity_id": candidates[0].entity.id if candidates else None,
                "top1_name": candidates[0].entity.name if candidates else None,
                "correct_candidate_ranks": correct_ranks,
                "outcome": ("top1_correct" if 1 in correct_ranks else "top1_wrong_correct_in_topk"
                            if correct_ranks else "unmatched" if not candidates else "no_correct_candidate"),
                "identity_certain": any(candidate.identity_certain for candidate in candidates),
                "additional_wrong_candidate_ids": [candidate.entity.id for candidate in candidates
                                                   if not same_identity(candidate.entity, expected)],
            })
    summary = {
        "reference_targets": len(references), "targets_present_in_vision": len(records),
        "targets_missing_from_vision": len(missing_visual_objects),
        "top1_correct": sum(record["outcome"] == "top1_correct" for record in records),
        "top1_wrong_correct_in_topk": sum(record["outcome"] == "top1_wrong_correct_in_topk" for record in records),
        "unmatched": sum(record["outcome"] == "unmatched" for record in records),
        "correct_in_topk": sum(bool(record["correct_candidate_ranks"]) for record in records),
        "confirmed_identities": sum(record["identity_certain"] for record in records),
    }
    report = {"method": "Separate offline identity review using preexisting photo references and real OSM identities. Inputs were not edited. Region hypotheses are coverage hypotheses, not camera locations. Only the fixed targets are scored; extra candidate errors are listed explicitly.",
              "summary": summary, "records": records, "missing_visual_objects": missing_visual_objects}
    (DATA / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
