"""Stage 3 import facade, used by CLI and Python callers."""

import hashlib

from .overpass import OverpassClient
from .parsing import parse_snapshot
from .regions import REGIONS
from .store import LandmarkStore


def import_region(store: LandmarkStore, region_id: str, client: OverpassClient | None = None,
                  *, refresh=False, offline=False) -> dict:
    if region_id not in REGIONS:
        raise ValueError("Unknown map coverage region")
    snapshot = (client or OverpassClient()).fetch(REGIONS[region_id], refresh=refresh, offline=offline)
    parsed = parse_snapshot(snapshot, region_id)
    metadata = {
        "region_id": region_id, "bounds": REGIONS[region_id].model_dump(),
        "source": snapshot.source, "fetched_at": snapshot.fetched_at.isoformat(),
        "query_sha256": hashlib.sha256(snapshot.query.encode()).hexdigest(),
        "query": snapshot.query,
        "osm_base_timestamp": snapshot.payload.get("osm3s", {}).get("timestamp_osm_base"),
        "raw_elements": len(snapshot.payload["elements"]), "stored_entities": len(parsed.entities),
        "named_entities": sum(bool(entity.aliases) for entity in parsed.entities),
        "complete_outlines": sum(entity.geometry_precision == "complete_outline" for entity in parsed.entities),
        "center_only": sum(entity.geometry_precision == "representative_point" for entity in parsed.entities),
        "cache_hit": snapshot.cache_hit, "stale_cache": snapshot.stale,
        "warnings": parsed.warnings,
        "license": "OpenStreetMap contributors, ODbL 1.0; https://www.openstreetmap.org/copyright",
    }
    store.import_entities(parsed.entities, region_id, REGIONS[region_id], metadata)
    return metadata
