"""Command-line image semantic extraction; no map matching or pose search."""

import argparse
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

from geophotoloc.config import ConfigurationError, VisionConfig
from geophotoloc.vision import ImageInputError, VisionAnalyzer, VisionAPIError, VisionResponseError
from geophotoloc.maps import LandmarkStore, MapDataError, MapMatcher, MatchConfig, OverpassClient, import_region
from geophotoloc.maps.regions import REGIONS
from geophotoloc.models import VisionExtractionResult


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
    demo_setup = commands.add_parser('demo-setup',help='Initialize/reuse finite Demo OSM coverage')
    demo_setup.add_argument('--db',type=Path,default=Path('.cache/geophotoloc/maps.sqlite3'))
    demo_setup.add_argument('--offline',action='store_true')
    analyze = commands.add_parser("analyze", help="Extract landmarks and image-space relations")
    analyze.add_argument("image", type=Path)
    analyze.add_argument("--output", help="JSON output path, or - for JSON on stdout")
    map_import = commands.add_parser("map-import", help="Import bounded OSM map coverage")
    map_import.add_argument("--region", choices=REGIONS, required=True)
    map_import.add_argument("--db", type=Path, default=Path(".cache/geophotoloc/maps.sqlite3"))
    map_import.add_argument("--cache-dir", type=Path, default=Path(".cache/geophotoloc/overpass"))
    map_import.add_argument("--offline", action="store_true")
    map_import.add_argument("--refresh", action="store_true")
    map_import.add_argument("--output")
    map_match = commands.add_parser("map-match", help="Match saved vision JSON without a vision API call")
    map_match.add_argument("input", type=Path)
    map_match.add_argument("--region", choices=REGIONS, action="append", help="Optional coverage restriction; omit to infer among loaded regions")
    map_match.add_argument("--db", type=Path, default=Path(".cache/geophotoloc/maps.sqlite3"))
    map_match.add_argument("--top-k", type=int, default=5)
    map_match.add_argument("--output")
    localize = commands.add_parser("localize", help="Search viewpoint regions from saved vision JSON, without a vision API")
    localize.add_argument("input", type=Path)
    localize.add_argument("--db", type=Path, default=Path(".cache/geophotoloc/maps.sqlite3"))
    localize.add_argument("--output")
    localize.add_argument("--geojson", type=Path)
    localize.add_argument("--radius", type=float, default=2200)
    localize.add_argument("--coarse-spacing", type=float, default=180)
    localize.add_argument("--fine-spacing", type=float, default=60)
    localize.add_argument("--max-points", type=int, default=24000)
    localize.add_argument("--bounds", nargs=4,type=float,metavar=("SOUTH","WEST","NORTH","EAST"))
    localize.add_argument("--fov", nargs="+",type=float,help="Horizontal FOV hypotheses in degrees")
    args = parser.parse_args(argv)
    try:
        if args.command == 'demo-setup':
            from geophotoloc.app.setup import setup_demo
            result=setup_demo(args.db,offline=args.offline)
            for item in result:
                print(f"{item['region']}: {item['status']} " + item.get('message',''))
            return int(any(item['status']=='failed' for item in result))
        if args.command == "localize":
            return _localize_command(args)
        if args.command in {"map-import", "map-match"}:
            return _map_command(args)
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
    except (ConfigurationError, ImageInputError, VisionAPIError, VisionResponseError, MapDataError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Error: cannot access input or write JSON output", file=sys.stderr)
        return 1
    except sqlite3.Error:
        print("Error: cannot read or update map database", file=sys.stderr)
        return 1


def _localize_command(args):
    import json
    from geophotoloc.localization import PoseSolver, PoseSearchConfig
    paths = [Path(value).resolve() for value in (args.output,args.geojson) if value and str(value)!="-"]
    if len(paths)!=len(set(paths)) or any(path in {args.input.resolve(),args.db.resolve()} for path in paths):
        raise ValueError("Localization outputs must differ from input, database and each other")
    if args.output and args.output!="-" and Path(args.output).suffix.lower()!=".json":
        raise ValueError("Localization result needs a .json output path")
    if args.geojson and args.geojson.suffix.lower() not in {'.geojson','.json'}:
        raise ValueError("GeoJSON needs a .geojson or .json output path")
    vision = VisionExtractionResult.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
    options = {}
    if args.bounds:
        from geophotoloc.models.maps import GeoBounds
        options['search_bounds'] = GeoBounds(**dict(zip(('south','west','north','east'),args.bounds)))
    if args.fov:
        options['fov_degrees'] = tuple(args.fov)
    config = PoseSearchConfig(search_radius_m=args.radius,coarse_spacing_m=args.coarse_spacing,
                              fine_spacing_m=args.fine_spacing,max_total_points=args.max_points,**options)
    with LandmarkStore(args.db) as store:
        matched = MapMatcher(store).match(vision)
        result = PoseSolver(store,config).solve(vision,matched)
    if args.geojson:
        _write_json(args.geojson,json.dumps(result.geojson,ensure_ascii=False,indent=2))
    if args.output=="-":
        print(result.model_dump_json(indent=2))
    else:
        if args.output:
            _write_json(Path(args.output),result.model_dump_json(indent=2))
        print(f"Status: {result.status}; candidate regions: {len(result.regions)}; elapsed: {result.elapsed_seconds:.3f}s")
        for region in result.regions[:5]:
            print(f"- {region.id}: {region.best_location.model_dump()}; heading={region.heading:.2f}; "
                  f"score={region.best_score.score:.4f}; satisfied={region.best_score.satisfied}; "
                  f"conflicts={region.best_score.conflicts}; assignments={region.assignments}")
        for warning in result.warnings:
            print("Warning:",warning)
    return 0


def _map_command(args):
    import json

    if args.output and args.output != "-":
        output = Path(args.output)
        inputs = [args.db]
        if args.command == "map-match":
            inputs.append(args.input)
        if output.suffix.lower() != ".json" or any(output.resolve() == path.resolve() for path in inputs):
            raise ValueError("Map output must be a .json file different from input and database")
    with LandmarkStore(args.db) as store:
        if args.command == "map-import":
            result = import_region(store, args.region, OverpassClient(args.cache_dir),
                                   refresh=args.refresh, offline=args.offline)
            content = json.dumps(result, ensure_ascii=False, indent=2)
            summary = (f"Region: {args.region}; entities: {result['stored_entities']}; "
                       f"outlines: {result['complete_outlines']}; "
                       f"cache: {result['cache_hit']}; stale: {result['stale_cache']}")
        else:
            try:
                vision = VisionExtractionResult.model_validate_json(args.input.read_text(encoding="utf-8-sig"))
            except ValueError:
                raise ValueError("Input is not a valid Stage 2 VisionExtractionResult JSON") from None
            result = MapMatcher(store, MatchConfig(top_k=args.top_k)).match(vision, regions=args.region)
            content = result.model_dump_json(indent=2)
            summary = (f"Status: {result.status}; image objects: {len(result.matches)}; "
                       f"map candidates: {sum(len(match.candidates) for match in result.matches)}; "
                       f"geographic hypotheses: {len(result.region_hypotheses)}")
    if args.output == "-":
        print(content)
    else:
        if args.output:
            _write_json(Path(args.output), content)
        print(summary)
        if args.command == "map-match":
            for match in result.matches:
                print(f"- {match.image_landmark_id}: {match.status}; "
                      + (", ".join(f"{item.entity.id} {item.entity.name} ({item.score:.3f})" for item in match.candidates)
                         or match.unmatched_reason))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    raise SystemExit(main())
