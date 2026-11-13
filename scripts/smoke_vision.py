"""Explicit live smoke test: two synthetic images, two requests, zero retries.

Not collected by pytest. Run from the repository root with uv run python
scripts/smoke_vision.py. This checks integration/schema, not landmark accuracy.
"""

from pathlib import Path
import tempfile

from PIL import Image, ImageDraw

from geophotoloc.config import ConfigurationError, VisionConfig
from geophotoloc.vision import ImageInputError, VisionAnalyzer, VisionAPIError, VisionResponseError


def main() -> int:
    try:
        config = VisionConfig.from_env()
    except ConfigurationError as exc:
        print(f"Configuration error: {exc}")
        return 1
    if (config.model != "qwen3.8-flash" or config.base_url.rstrip("/")
            != "https://dashscope.aliyuncs.com/compatible-mode/v1"):
        print("No requests sent: configuration differs from the specified model/endpoint.")
        return 1
    analyzer = VisionAnalyzer(config.model_copy(update={"max_retries": 0}))
    failures = 0
    with tempfile.TemporaryDirectory(prefix="geophotoloc-smoke-") as directory:
        scene = Image.new("RGB", (640, 400), "skyblue")
        draw = ImageDraw.Draw(scene)
        draw.rectangle((0, 260, 640, 400), fill="steelblue")
        draw.rectangle((80, 100, 150, 290), fill="gray")
        draw.polygon([(70, 100), (115, 55), (160, 100)], fill="dimgray")
        draw.rectangle((200, 235, 620, 265), fill="darkgray")
        for x in (230, 370, 510, 600):
            draw.rectangle((x, 260, x + 15, 350), fill="gray")
        scene.save(Path(directory) / "synthetic_scene.png")
        Image.new("RGB", (640, 400), "white").save(Path(directory) / "blank.png")
        for filename in ("synthetic_scene.png", "blank.png"):
            try:
                result = analyzer.analyze(Path(directory) / filename)
                print(f"{filename}: PASS; landmarks={len(result.landmarks)}, "
                      f"relations={len(result.relations)}, "
                      f"uncertain_identities={sum(item.identity_uncertain for item in result.landmarks)}")
            except (ImageInputError, VisionAPIError, VisionResponseError) as exc:
                failures += 1
                print(f"{filename}: FAIL; {exc}")
    print(f"Live requests: 2; failures: {failures}; SDK retries: 0")
    return int(failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
