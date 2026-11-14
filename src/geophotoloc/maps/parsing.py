"""OSM geometry parsing; incomplete outlines never masquerade as footprints."""

from dataclasses import dataclass
import re

from shapely import make_valid
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, LineString, Point, Polygon, mapping
from shapely.ops import polygonize_full, unary_union

from geophotoloc.models import GeoPoint
from geophotoloc.models.maps import MapLandmark

from .overpass import OverpassSnapshot, validate_payload


@dataclass
class ParseResult:
    entities: list[MapLandmark]
    warnings: list[str]


def category_from_tags(tags):
    if (tags.get("public_transport") or tags.get("railway")
            or tags.get("building") in {"train_station", "station", "transportation", "railway_station", "trn"}
            or tags.get("amenity") == "bus_station"):
        return "transport"
    if tags.get("bridge") not in (None, "no") or tags.get("man_made") == "bridge":
        return "bridge"
    if tags.get("man_made") in {"tower", "communications_tower", "water_tower"}:
        return "tower"
    if tags.get("waterway") or tags.get("natural") == "water":
        return "water"
    if tags.get("highway"):
        return "road"
    if tags.get("place") in {"island", "islet"}:
        return "island"
    if tags.get("building") and tags["building"] != "no":
        return "building"
    if tags.get("shop"):
        return "shop"
    if tags.get("historic"):
        return "historic"
    if tags.get("tourism"):
        return {"hotel": "hotel", "motel": "hotel", "viewpoint": "viewpoint", "information": "service"}.get(tags["tourism"], "attraction")
    if tags.get("leisure"):
        return "leisure"
    return "other"


def extract_names(tags):
    prefixes = {"name", "alt_name", "official_name", "short_name", "loc_name", "old_name", "int_name"}
    keys = {key: value.strip() for key, value in tags.items()
            if (key in prefixes or any(key.startswith(prefix + ":") for prefix in prefixes)) and value.strip()}
    for key, value in tags.items():
        if key == "wikipedia" or key.startswith("wikipedia:"):
            title = value.split(":", 1)[-1] if key == "wikipedia" else value
            if title.strip() and "://" not in value:
                keys["osm_" + key + "_title"] = title.replace("_", " ").strip()
    aliases = sorted({piece.strip() for value in keys.values()
                      for piece in re.split(r"[;；]", value) if piece.strip()})
    name = keys.get("name") or keys.get("name:zh") or keys.get("name:en") or next(iter(aliases), None)
    return name, keys, aliases


def _coordinate(raw):
    if not isinstance(raw, dict) or isinstance(raw.get("lat"), bool) or isinstance(raw.get("lon"), bool):
        raise ValueError("Invalid coordinate")
    point = GeoPoint(latitude=raw["lat"], longitude=raw["lon"])
    return (point.longitude, point.latitude)


def _way_geometry(raw, lookup):
    coords = raw.get("geometry")
    if coords is None:
        coords = [lookup.get(("node", node_id)) for node_id in raw.get("nodes", [])]
    if not isinstance(coords, list):
        raise ValueError("Invalid way geometry")
    runs, run, incomplete = [], [], False
    for coordinate in coords:
        try:
            run.append(_coordinate(coordinate))
        except (KeyError, TypeError, ValueError):
            incomplete = True
            if run:
                runs.append(run)
                run = []
    if run:
        runs.append(run)
    geometries = []
    closed = False
    for run in runs:
        if len(run) == 1:
            geometries.append(Point(run[0]))
        elif len(run) >= 4 and run[0] == run[-1] and not incomplete:
            # An OSM closed way can be a line (e.g. a roundabout); area=no,
            # highways and non-area waterways stay linear.
            tags = raw.get("tags", {})
            is_area = tags.get("area") != "no" and (
                tags.get("building") not in (None, "no") or tags.get("building:part") not in (None, "no")
                or tags.get("man_made") in {"tower", "communications_tower", "water_tower"} or tags.get("area") == "yes"
                or tags.get("natural") in {"water", "wood"} or tags.get("landuse")
                or tags.get("leisure") or tags.get("place") in {"island", "islet"}
            )
            geometries.append(Polygon(run) if is_area else LineString(run))
            closed = bool(is_area)
        else:
            geometries.append(LineString(run))
    if not geometries:
        return None, False, "partial_geometry"
    geom = geometries[0] if len(geometries) == 1 else GeometryCollection(geometries)
    complete = not incomplete and (closed or raw.get("tags", {}).get("building") in (None, "no"))
    precision = "complete_outline" if complete and closed else ("complete_geometry" if complete else "partial_geometry")
    return geom, complete, precision


def _member_lines(member, lookup):
    raw = dict(lookup.get((member.get("type"), member.get("ref")), {}))
    raw.update(member)
    if member.get("type") == "node":
        try:
            return Point(_coordinate(raw)), True
        except (KeyError, TypeError, ValueError):
            return None, False
    if member.get("type") != "way":
        return None, False
    # Multipolygon member rings are assembled by role, regardless of way tags.
    raw["tags"] = {"area": "no"}
    geom, complete, _ = _way_geometry(raw, lookup)
    return geom, complete


def _relation_geometry(raw, lookup):
    outer, inner, all_geoms, incomplete = [], [], [], False
    members = raw.get("members", [])
    for member in members:
        geom, complete = _member_lines(member, lookup)
        incomplete |= not complete
        if geom is None:
            continue
        all_geoms.append(geom)
        if geom.geom_type == "LineString":
            (inner if member.get("role") == "inner" else outer).append(geom)
        elif raw.get("tags", {}).get("type") == "multipolygon":
            incomplete = True
    if not all_geoms:
        return None, False, "partial_geometry"
    if raw.get("tags", {}).get("type") in {"multipolygon", "boundary"} and outer:
        shells, cuts, dangles, invalid = polygonize_full(unary_union(outer))
        holes, hcuts, hdangles, hinvalid = polygonize_full(unary_union(inner)) if inner else (GeometryCollection(),) * 4
        incomplete |= any(not geom.is_empty for geom in (cuts, dangles, invalid, hcuts, hdangles, hinvalid))
        polygons, used_holes = [], set()
        for shell in shells.geoms:
            interiors = []
            for index, hole in enumerate(holes.geoms):
                if shell.covers(hole):
                    interiors.append(hole.exterior.coords)
                    used_holes.add(index)
            polygons.append(make_valid(Polygon(shell.exterior.coords, interiors)))
        incomplete |= len(used_holes) != len(holes.geoms)
        if polygons and not incomplete:
            geom = unary_union(polygons)
            return geom, True, "complete_outline"
    if raw.get("tags", {}).get("type") in {"multipolygon", "boundary"}:
        incomplete = True
    return GeometryCollection(all_geoms), not incomplete, ("partial_geometry" if incomplete else "complete_geometry")


def parse_snapshot(snapshot: OverpassSnapshot, region_id: str) -> ParseResult:
    validate_payload(snapshot.payload)
    lookup = {}
    warnings = []
    for raw in snapshot.payload["elements"]:
        if isinstance(raw, dict) and raw.get("type") in {"node", "way", "relation"}:
            if isinstance(raw.get("id"), int) and not isinstance(raw["id"], bool) and raw["id"] > 0:
                key = (raw["type"], raw["id"])
                # More complete repeated records win; missing tags do not erase them.
                raw = dict(raw)
                tags = raw.get("tags")
                if not isinstance(tags, dict):
                    tags = {}
                tags = {key: value for key, value in tags.items() if isinstance(key, str) and isinstance(value, str)}
                existing = lookup.get(key, {})
                raw = {field: value for field, value in raw.items() if value is not None}
                for field in ("geometry", "nodes", "members"):
                    if isinstance(existing.get(field), list) and isinstance(raw.get(field), list):
                        if len(existing[field]) > len(raw[field]):
                            raw[field] = existing[field]
                lookup[key] = {**existing, **raw, "tags": {**existing.get("tags", {}), **tags}}
            else:
                warnings.append("Skipped invalid OSM ID")
        else:
            warnings.append("Skipped malformed/unsupported OSM element")
    entities = []
    for (kind, osm_id), raw in lookup.items():
        try:
            tags = {key: value for key, value in (raw.get("tags") or {}).items()
                    if isinstance(key, str) and isinstance(value, str)}
            raw = dict(raw, tags=tags)
            notes = []
            if kind == "node":
                geom, complete, precision = Point(_coordinate(raw)), True, "node"
                meaning = "actual_osm_node; not a photographer position"
            elif kind == "way":
                geom, complete, precision = _way_geometry(raw, lookup)
                meaning = "computed_point_on_geometry; not an entrance or photographer position"
            else:
                geom, complete, precision = _relation_geometry(raw, lookup)
                meaning = "computed_point_on_geometry; not an entrance or photographer position"
            if geom is None or geom.is_empty:
                geom = Point(_coordinate(raw["center"]))
                complete, precision = False, "representative_point"
                meaning = "overpass_bbox_center_only; outline unavailable; not an entrance or photographer position"
                notes.append("Only an Overpass center is available; no true footprint")
            if not geom.is_valid:
                geom = make_valid(geom)
                complete, precision = False, "partial_geometry"
                notes.append("Invalid source geometry repaired with Shapely make_valid")
            if not complete:
                notes.append("Incomplete geographic geometry")
            representative = geom.representative_point()
            name, names, aliases = extract_names(tags)
            entities.append(MapLandmark(
                id=f"osm:{kind}:{osm_id}", osm_type=kind, osm_id=osm_id,
                name=name or f"[unnamed {kind} {osm_id}]", names=names, aliases=aliases,
                location=GeoPoint(latitude=representative.y, longitude=representative.x),
                category=category_from_tags(tags), geometry=mapping(geom),
                geometry_precision=precision, complete_geometry=complete,
                coordinate_meaning=meaning, tags=tags, source=snapshot.source,
                fetched_at=snapshot.fetched_at, osm_updated_at=raw.get("timestamp"),
                region_ids=[region_id], warnings=notes,
            ))
        except (KeyError, TypeError, ValueError, AttributeError, GEOSException):
            warnings.append(f"Skipped {kind}/{osm_id}: invalid or absent coordinates/geometry/tags")
    return ParseResult(entities, warnings)
