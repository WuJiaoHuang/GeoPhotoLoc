"""Stage 2.1 evidence runner; offline rendering by default, live API opt-in.

The application receives only image bytes and the unchanged Stage 2 prompt.
Source names, reference identities and reference boxes are never sent to it.
The append-only request ledger bounds this evaluation to five attempts.
"""

import argparse
import base64
from datetime import datetime, timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path

import httpx
from openai import OpenAI
from PIL import Image, ImageDraw

from geophotoloc.config import VisionConfig
from geophotoloc.models import VisionExtractionResult
from geophotoloc.vision import VisionAnalyzer, VisionAPIError, VisionResponseError, prepare_image

ROOT = Path(__file__).resolve().parents[1] / "docs/evaluation/stage2_1"


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run_api(samples):
    config = VisionConfig.from_env()
    if (config.model != "qwen3.8-flash" or config.base_url.rstrip("/")
            != "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        raise ValueError("Configured model/endpoint differs from the authorized evaluation")
    ledger_path = ROOT / "requests.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else []
    env_path = Path(".env")
    original_env = env_path.read_bytes() if env_path.exists() else None
    failures = 0
    for sample in samples:
        result_path = ROOT / "results" / f"{sample['id']}.json"
        if result_path.exists():
            print(f"{sample['id']}: saved result exists; no request", flush=True)
            continue
        if len(ledger) >= 5:
            raise ValueError("Five-request evaluation budget exhausted")
        prepared = prepare_image(ROOT / sample["file"])
        entry = None

        def on_request(request):
            nonlocal entry
            if len(ledger) >= 5:
                raise ValueError("Five-request evaluation budget exhausted")
            entry = {
                "attempt": len(ledger) + 1, "sample_id": sample["id"],
                "started_at_utc": datetime.now(timezone.utc).isoformat(),
                "model": config.model, "base_url": config.base_url,
                "sdk_max_retries": 0, "timeout_seconds": config.timeout,
                "input_sha256": sha256(ROOT / sample["file"]),
                "ground_truth_sha256": sha256(ROOT / "ground_truth.json"),
                "status": "attempt_started",
            }
            ledger.append(entry)
            save_json(ledger_path, ledger)

        try:
            with httpx.Client(event_hooks={"request": [on_request]}) as transport:
                with OpenAI(
                    api_key=config.api_key.get_secret_value(), base_url=config.base_url,
                    timeout=config.timeout, max_retries=0, http_client=transport,
                ) as client:
                    result = VisionAnalyzer(config, client).analyze_prepared(prepared)
            result_path.parent.mkdir(parents=True, exist_ok=True)
            result_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
            entry.update(status="success", result_sha256=sha256(result_path))
            print(f"{sample['id']}: success; landmarks={len(result.landmarks)}, "
                  f"relations={len(result.relations)}", flush=True)
        except (VisionAPIError, VisionResponseError) as exc:
            failures += 1
            entry.update(status="failed", error=str(exc))
            print(f"{sample['id']}: failed; {exc}", flush=True)
        finally:
            if entry is not None:
                entry["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
                save_json(ledger_path, ledger)
            if (env_path.read_bytes() if env_path.exists() else None) != original_env:
                raise ValueError("Existing .env changed during evaluation")
    print(f"Recorded live HTTP attempts: {len(ledger)}; retries disabled; failures this run: {failures}")
    return failures


def draw_box(draw, size, box, label, color, center=None):
    width, height = size
    points = (box["x_min"] * width, box["y_min"] * height,
              box["x_max"] * width, box["y_max"] * height)
    draw.rectangle(points, outline=color, width=3)
    x = min(max(0, points[0]), width - 130)
    y = min(max(18, points[1]), height - 18)
    draw.text((x, y - 17), label, fill=color, stroke_width=1, stroke_fill="black")
    if center is not None:
        cx, cy = center[0] * width, center[1] * height
        draw.line((cx - 6, cy, cx + 6, cy), fill=color, width=2)
        draw.line((cx, cy - 6, cx, cy + 6), fill=color, width=2)


def render(samples):
    for sample in samples:
        path = ROOT / "results" / f"{sample['id']}.json"
        if not path.exists():
            continue
        result = VisionExtractionResult.model_validate_json(path.read_text(encoding="utf-8"))
        prepared = prepare_image(ROOT / sample["file"])
        data = base64.b64decode(prepared.data_url.split(",", 1)[1])
        with Image.open(BytesIO(data)) as source:
            for kind in ("reference", "model"):
                image = source.copy()
                draw = ImageDraw.Draw(image)
                if kind == "reference":
                    for reference in sample["landmarks"]:
                        draw_box(draw, image.size, reference["bbox"], reference["id"], "lime")
                else:
                    for landmark in result.landmarks:
                        draw_box(draw, image.size, landmark.bbox.model_dump(), landmark.id,
                                 "yellow", (landmark.x, landmark.y))
                draw.text((10, image.height - 20),
                          f"{sample['id']} / {kind} / CC BY-SA 4.0; see ATTRIBUTION.md",
                          fill="white", stroke_width=1, stroke_fill="black")
                output = ROOT / "annotations" / f"{sample['id']}_{kind}.jpg"
                output.parent.mkdir(exist_ok=True)
                image.save(output, quality=88)
        print(f"{sample['id']}: offline annotations rendered")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-api", action="store_true", help="Opt in to at most five total recorded requests")
    args = parser.parse_args()
    truth = json.loads((ROOT / "ground_truth.json").read_text(encoding="utf-8"))
    failures = run_api(truth["samples"]) if args.run_api else 0
    render(truth["samples"])
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
