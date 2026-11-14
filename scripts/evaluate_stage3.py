"""Import cached coverage and run original vision results without region hints.

No vision requests or ground-truth files are read by this runner. Identity
comparison belongs to the separate offline review, after matching is saved.
"""

import argparse
import hashlib
import json
from pathlib import Path

from geophotoloc.maps import LandmarkStore, MapDataError, MapMatcher, OverpassClient, import_region
from geophotoloc.maps.regions import REGIONS
from geophotoloc.models import VisionExtractionResult

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs/evaluation/stage3"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--online", action="store_true", help="Allow sequential bounded downloads if caches are missing")
    args = parser.parse_args()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    manifests = []
    with LandmarkStore() as store:
        for region in REGIONS:
            try:
                metadata = import_region(store, region, OverpassClient(retries=1), offline=not args.online)
                manifests.append(metadata)
                print(region, "imported", metadata["stored_entities"], "entities; outlines", metadata["complete_outlines"], flush=True)
            except MapDataError as exc:
                manifests.append({"region_id": region, "error": str(exc)})
                print(region, "unavailable:", exc, flush=True)
        (OUTPUT / "imports.json").write_text(json.dumps(manifests, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        matcher = MapMatcher(store)
        for path in sorted((ROOT / "docs/evaluation/stage2_1/results").glob("*.json")):
            vision = VisionExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
            result = matcher.match(vision)  # No city, file path, sample ID or reference answers.
            output = OUTPUT / (path.stem + "_matches.json")
            output.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
            print(path.stem, result.status, [(match.image_landmark_id, [(item.entity.name, item.score)
                  for item in match.candidates]) for match in result.matches], flush=True)
        hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in (ROOT / "docs/evaluation/stage2_1/results").glob("*.json")}
        (OUTPUT / "vision_input_hashes.json").write_text(json.dumps(hashes, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
