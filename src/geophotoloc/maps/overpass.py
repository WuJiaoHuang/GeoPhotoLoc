"""Bounded, sequential Overpass requests with durable successful-response caching."""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

import httpx

from geophotoloc.models.maps import GeoBounds


class MapDataError(RuntimeError):
    pass


@dataclass
class OverpassSnapshot:
    payload: dict
    source: str
    fetched_at: datetime
    query: str
    cache_hit: bool
    stale: bool = False


def build_query(bounds: GeoBounds) -> str:
    bbox = f"{bounds.south},{bounds.west},{bounds.north},{bounds.east}"
    # Named features in any language plus building footprints; full geometries,
    # not bbox-clipped outlines or silently truncated out-counts.
    return (
        '[out:json][timeout:45][maxsize:33554432];('
        f'node[~"^(name(:.*)?|alt_name|official_name|short_name)$"~"."]({bbox});'
        f'way[~"^(name(:.*)?|alt_name|official_name|short_name)$"~"."]({bbox});'
        f'relation["type"="multipolygon"][~"^(name(:.*)?|alt_name|official_name|short_name)$"~"."]({bbox});'
        f'way["building"]({bbox});relation["building"]({bbox});'
        f'nwr["man_made"~"^(tower|communications_tower|water_tower)$"]({bbox});'
        ');out meta geom;'
    )


def validate_payload(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("elements"), list):
        raise MapDataError("Overpass response lacks an elements list")
    if payload.get("remark"):
        raise MapDataError("Overpass returned an incomplete/error response")
    if len(payload["elements"]) > 30000:
        raise MapDataError("Overpass element limit exceeded")


class OverpassClient:
    def __init__(
        self, cache_dir: str | Path = ".cache/geophotoloc/overpass", *,
        endpoint: str = "https://overpass-api.de/api/interpreter",
        client: httpx.Client | None = None, timeout: float = 90,
        retries: int = 2, cache_ttl_seconds: float = 7 * 86400, sleep=time.sleep,
    ):
        if not 0 <= retries <= 3 or not 0 < timeout <= 300 or cache_ttl_seconds < 0:
            raise ValueError("Invalid Overpass timeout, retries or cache TTL")
        self.cache_dir, self.endpoint = Path(cache_dir), endpoint
        self.client, self.timeout, self.retries = client, timeout, retries
        self.cache_ttl_seconds, self.sleep = cache_ttl_seconds, sleep

    def fetch(self, bounds: GeoBounds, *, refresh=False, offline=False) -> OverpassSnapshot:
        query = build_query(bounds)
        key = hashlib.sha256((self.endpoint + "\n" + query).encode()).hexdigest()
        path = self.cache_dir / (key + ".json")
        cached = None
        if path.exists():
            try:
                envelope = json.loads(path.read_text(encoding="utf-8"))
                validate_payload(envelope["payload"])
                fetched = datetime.fromisoformat(envelope["fetched_at"])
                if fetched.tzinfo is None or envelope["query"] != query or envelope["source"] != self.endpoint:
                    raise ValueError("Invalid cache provenance")
                age = (datetime.now(timezone.utc) - fetched).total_seconds()
                cached = OverpassSnapshot(envelope["payload"], self.endpoint, fetched, query, True,
                                          stale=age > self.cache_ttl_seconds)
            except (ValueError, KeyError, TypeError, MapDataError):
                cached = None
        if offline:
            if cached is None:
                raise MapDataError("No valid cached Overpass response for this region/endpoint")
            return cached
        if cached is not None and not refresh and not cached.stale:
            return cached
        last_error = "Overpass request failed"
        for attempt in range(self.retries + 1):
            retry_delay = min(2 ** attempt, 8)
            owned = self.client is None
            client = self.client or httpx.Client(follow_redirects=False)
            try:
                with client.stream(
                    "POST", self.endpoint, data={"data": query}, timeout=self.timeout,
                    headers={"User-Agent": "GeoPhotoLoc/0.1 (bounded academic demo; github.com/WuJiaoHuang/GeoPhotoLoc)",
                             "Accept": "application/json"},
                ) as response:
                    if response.status_code in {429, 502, 503, 504}:
                        last_error = f"Overpass HTTP {response.status_code}"
                        try:
                            retry_delay = min(max(float(response.headers.get("Retry-After", retry_delay)), 0), 10)
                        except ValueError:
                            pass
                    elif response.status_code != 200:
                        raise MapDataError(f"Overpass HTTP {response.status_code}")
                    else:
                        content = bytearray()
                        for chunk in response.iter_bytes():
                            content.extend(chunk)
                            if len(content) > 32 * 1024 * 1024:
                                raise MapDataError("Overpass response byte limit exceeded")
                        try:
                            payload = json.loads(content)
                        except (ValueError, UnicodeError):
                            raise MapDataError("Overpass returned invalid JSON") from None
                        validate_payload(payload)
                        snapshot = OverpassSnapshot(payload, self.endpoint, datetime.now(timezone.utc), query, False)
                        self.cache_dir.mkdir(parents=True, exist_ok=True)
                        temporary = path.with_suffix(".tmp")
                        temporary.write_text(json.dumps({
                            "payload": payload, "source": self.endpoint,
                            "fetched_at": snapshot.fetched_at.isoformat(), "query": query,
                        }, ensure_ascii=False), encoding="utf-8")
                        temporary.replace(path)
                        return snapshot
            except httpx.TimeoutException:
                last_error = "Overpass request timed out"
            except httpx.RequestError:
                last_error = "Cannot connect to Overpass"
            finally:
                if owned:
                    client.close()
            if attempt < self.retries:
                self.sleep(retry_delay)
        if cached is not None:
            cached.stale = True
            return cached
        raise MapDataError(last_error + "; no usable cache")
