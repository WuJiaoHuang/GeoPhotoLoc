"""Command-line image semantic extraction; no map matching or pose search."""

import argparse
import os
from pathlib import Path
import sys
import tempfile

from geophotoloc.config import ConfigurationError, VisionConfig
from geophotoloc.vision import ImageInputError, VisionAnalyzer, VisionAPIError, VisionResponseError


def _write_json(path: Path, content: str):
    """Replace output atomically, preserving existing files on failed writes."""
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content + "\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="geophotoloc")
    commands = parser.add_subparsers(dest="command", required=True)
    analyze = commands.add_parser("analyze", help="Extract landmarks and image-space relations")
    analyze.add_argument("image", type=Path)
    analyze.add_argument("--output", help="JSON output path, or - for JSON on stdout")
    args = parser.parse_args(argv)
    try:
        if args.output and args.output != "-":
            output = Path(args.output)
            if output.resolve() == args.image.resolve() or output.suffix.lower() != ".json":
                raise ValueError("Output must be a .json file different from the input image")
        config = VisionConfig.from_env()
        result = VisionAnalyzer(config).analyze(args.image)
        content = result.model_dump_json(indent=2)
        if args.output == "-":
            print(content)
            return 0
        if args.output:
            _write_json(output, content)
        image = result.image
        print(f"Image: {image.processed_size.width}x{image.processed_size.height} "
              f"(original {image.original_size.width}x{image.original_size.height})")
        print(f"Landmarks: {len(result.landmarks)}; spatial relations: {len(result.relations)}")
        for landmark in result.landmarks:
            identity = "identity uncertain" if landmark.identity_uncertain else "model-identified"
            print(f"- {landmark.id}: {landmark.name} ({landmark.x:.3f}, {landmark.y:.3f}); {identity}")
        for warning in result.warnings:
            print(f"Warning: {warning}")
        if args.output:
            print("JSON output saved.")
        return 0
    except (ConfigurationError, ImageInputError, VisionAPIError, VisionResponseError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Error: cannot access input or write JSON output", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
