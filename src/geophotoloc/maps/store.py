"""Indexed SQLite entity/name/coverage storage; imports are transactional upserts."""

from dataclasses import dataclass
from datetime import timezone
from difflib import SequenceMatcher
import json
from pathlib import Path
import sqlite3

from shapely.geometry import shape

from geophotoloc.models.maps import GeoBounds, MapLandmark

from .names import normalize_name


@dataclass(frozen=True)
class NameHit:
    entity_id: str
    map_name: str
    similarity: float
    kind: str


class LandmarkStore:
    def __init__(self, path: str | Path = ".cache/geophotoloc/maps.sqlite3"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(path))
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS entities (
                id TEXT PRIMARY KEY, osm_type TEXT, osm_id INTEGER,
                name TEXT NOT NULL, latitude REAL NOT NULL, longitude REAL NOT NULL,
                category TEXT NOT NULL, west REAL, south REAL, east REAL, north REAL,
                fetched_epoch REAL NOT NULL, entity_json TEXT NOT NULL,
                UNIQUE(osm_type, osm_id)
            );
            CREATE TABLE IF NOT EXISTS regions (id TEXT PRIMARY KEY, bounds_json TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS memberships (
                entity_id TEXT REFERENCES entities(id), region_id TEXT REFERENCES regions(id),
                PRIMARY KEY(entity_id,region_id)
            );
            CREATE TABLE IF NOT EXISTS names (
                entity_id TEXT REFERENCES entities(id), normalized TEXT NOT NULL, original TEXT NOT NULL,
                PRIMARY KEY(entity_id,normalized,original)
            );
            CREATE TABLE IF NOT EXISTS imports (
                region_id TEXT REFERENCES regions(id), source TEXT, fetched_at TEXT,
                query_sha256 TEXT, metadata_json TEXT NOT NULL,
                PRIMARY KEY(region_id,source,fetched_at,query_sha256)
            );
            CREATE INDEX IF NOT EXISTS idx_names_normalized ON names(normalized);
            CREATE INDEX IF NOT EXISTS idx_entities_lat_lon ON entities(latitude,longitude);
            CREATE INDEX IF NOT EXISTS idx_entities_extent ON entities(west,east,south,north);
            CREATE INDEX IF NOT EXISTS idx_entities_category ON entities(category);
            CREATE INDEX IF NOT EXISTS idx_memberships_region ON memberships(region_id);
        """)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        self.connection.close()

    def import_entities(self, entities: list[MapLandmark], region_id: str, bounds: GeoBounds, metadata: dict):
        with self.connection:
            self.connection.execute("INSERT INTO regions VALUES (?,?) ON CONFLICT(id) DO UPDATE SET bounds_json=excluded.bounds_json",
                                    (region_id, bounds.model_dump_json()))
            self.connection.execute("DELETE FROM memberships WHERE region_id=?", (region_id,))
            for entity in entities:
                if entity.fetched_at.tzinfo is None:
                    raise ValueError("Map acquisition timestamp must be timezone-aware")
                epoch = entity.fetched_at.astimezone(timezone.utc).timestamp()
                existing = self.connection.execute("SELECT fetched_epoch FROM entities WHERE id=?", (entity.id,)).fetchone()
                if existing is None or existing[0] <= epoch:
                    bbox = shape(entity.geometry).bounds if entity.geometry is not None else (
                        entity.location.longitude, entity.location.latitude,
                        entity.location.longitude, entity.location.latitude,
                    )
                    self.connection.execute("""
                        INSERT INTO entities VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(id) DO UPDATE SET osm_type=excluded.osm_type,osm_id=excluded.osm_id,
                        name=excluded.name,latitude=excluded.latitude,longitude=excluded.longitude,
                        category=excluded.category,west=excluded.west,south=excluded.south,
                        east=excluded.east,north=excluded.north,fetched_epoch=excluded.fetched_epoch,
                        entity_json=excluded.entity_json
                    """, (entity.id, entity.osm_type, entity.osm_id, entity.name,
                          entity.location.latitude, entity.location.longitude, entity.category,
                          *bbox, epoch, entity.model_dump_json()))
                    self.connection.execute("DELETE FROM names WHERE entity_id=?", (entity.id,))
                    aliases = set(entity.aliases) | set(entity.names.values())
                    if not entity.name.startswith("[unnamed "):
                        aliases.add(entity.name)
                    self.connection.executemany("INSERT OR IGNORE INTO names VALUES (?,?,?)", [
                        (entity.id, normalize_name(alias), alias) for alias in aliases if normalize_name(alias)
                    ])
                self.connection.execute("INSERT OR IGNORE INTO memberships VALUES (?,?)", (entity.id, region_id))
            self.connection.execute("INSERT OR REPLACE INTO imports VALUES (?,?,?,?,?)", (
                region_id, metadata.get("source", ""), metadata.get("fetched_at", ""),
                metadata.get("query_sha256", ""), json.dumps(metadata, ensure_ascii=False),
            ))

    def coverage_regions(self) -> list[str]:
        return [row[0] for row in self.connection.execute("SELECT id FROM regions ORDER BY id")]

    def _entity(self, row):
        if row is None:
            return None
        entity = MapLandmark.model_validate_json(row["entity_json"])
        entity.region_ids = [item[0] for item in self.connection.execute(
            "SELECT region_id FROM memberships WHERE entity_id=? ORDER BY region_id", (entity.id,),
        )]
        return entity

    def get(self, entity_id: str) -> MapLandmark | None:
        return self._entity(self.connection.execute("SELECT * FROM entities WHERE id=?", (entity_id,)).fetchone())

    def get_by_osm(self, osm_type: str, osm_id: int) -> MapLandmark | None:
        return self._entity(self.connection.execute(
            "SELECT * FROM entities WHERE osm_type=? AND osm_id=?", (osm_type, osm_id),
        ).fetchone())

    def _filters(self, regions=None, category=None, bounds=None):
        sql = " EXISTS(SELECT 1 FROM memberships m WHERE m.entity_id=e.id)"
        parameters = []
        if regions is not None:
            if not regions:
                return "0", []
            sql += " AND EXISTS(SELECT 1 FROM memberships m WHERE m.entity_id=e.id AND m.region_id IN (" + ",".join("?" for _ in regions) + "))"
            parameters.extend(regions)
        if category is not None:
            sql += " AND e.category=?"
            parameters.append(category)
        if bounds is not None:
            sql += " AND e.west<=? AND e.east>=? AND e.south<=? AND e.north>=?"
            parameters.extend((bounds.east, bounds.west, bounds.north, bounds.south))
        return sql, parameters

    def list_entities(self, *, regions=None, category=None, bounds: GeoBounds | None = None):
        where, parameters = self._filters(regions, category, bounds)
        return [self._entity(row) for row in self.connection.execute(
            "SELECT e.* FROM entities e WHERE " + where + " ORDER BY e.id", parameters,
        )]

    def search_name(self, query: str, *, regions=None, limit: int = 30) -> list[NameHit]:
        normalized = normalize_name(query)
        if len(normalized) < 2:
            return []
        where, parameters = self._filters(regions)
        # Exact lookup uses the normalized-name index. Fuzzy search is bounded to
        # the finite imported demo coverage; no global gazetteer is scanned.
        exact = self.connection.execute(
            "SELECT n.* FROM names n JOIN entities e ON e.id=n.entity_id WHERE n.normalized=? AND " + where,
            [normalized, *parameters],
        ).fetchall()
        rows = self.connection.execute(
            "SELECT n.* FROM names n JOIN entities e ON e.id=n.entity_id WHERE " + where,
            parameters,
        ).fetchall()
        hits = {}
        for row in [*exact, *rows]:
            value = row["normalized"]
            if value == normalized:
                score, kind = 1.0, "exact_name_or_alias"
            elif min(len(value), len(normalized)) >= 4 and (value in normalized or normalized in value):
                ratio = min(len(value), len(normalized)) / max(len(value), len(normalized))
                if ratio < 0.5:
                    continue
                score, kind = 0.88 + 0.06 * ratio, "name_containment"
            elif min(len(value), len(normalized)) >= 4:
                score, kind = SequenceMatcher(None, normalized, value).ratio(), "fuzzy_name"
                if score < 0.72:
                    continue
            else:
                continue
            hit = NameHit(row["entity_id"], row["original"], score, kind)
            if hit.entity_id not in hits or hit.similarity > hits[hit.entity_id].similarity:
                hits[hit.entity_id] = hit
        return sorted(hits.values(), key=lambda hit: (-hit.similarity, hit.entity_id))[:limit]
