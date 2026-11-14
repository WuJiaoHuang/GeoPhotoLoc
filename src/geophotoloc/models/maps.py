"""Map retrieval/matching contracts. Scores are heuristics, not probabilities."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from shapely.geometry import shape

from .landmark import GeoPoint
from .observation import SpatialRelation


class MapModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class GeoBounds(MapModel):
    south: float = Field(ge=-90, le=90)
    west: float = Field(ge=-180, le=180)
    north: float = Field(ge=-90, le=90)
    east: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def ordered(self):
        if not (0 < self.north - self.south <= 0.2 and 0 < self.east - self.west <= 0.2):
            raise ValueError("Bounds must be ordered, non-wrapping and at most 0.2 degrees per axis")
        return self


class OSMEntity(MapModel):
    osm_type: Literal["node", "way", "relation"] | None = None
    osm_id: int | None = Field(default=None, gt=0, strict=True)
    tags: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def osm_identity(self):
        if (self.osm_type is None) != (self.osm_id is None):
            raise ValueError("OSM type and ID must be supplied together")
        return self


class MapLandmark(OSMEntity):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    names: dict[str, str] = Field(default_factory=dict)
    aliases: list[str] = Field(default_factory=list)
    location: GeoPoint
    category: str
    geometry: dict | None = None
    geometry_precision: Literal["node", "complete_outline", "complete_geometry", "partial_geometry", "representative_point"]
    complete_geometry: bool
    coordinate_meaning: str
    source: str
    source_type: Literal["osm", "manual"] = "osm"
    is_manual: bool = False
    fetched_at: datetime
    osm_updated_at: str | None = None
    region_ids: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_geometry_source(self):
        if self.source_type == "osm" and (self.osm_id is None or self.is_manual):
            raise ValueError("OSM records need OSM identity and cannot be manual")
        if self.source_type == "manual" and not self.is_manual:
            raise ValueError("Supplementary records must be marked manual")
        if self.geometry is not None:
            geom = shape(self.geometry)
            if geom.is_empty or not geom.is_valid:
                raise ValueError("Stored geometry must be valid and nonempty")
            if geom.has_z:
                raise ValueError("Map geometry must be two dimensional")
            west, south, east, north = geom.bounds
            if not (-180 <= west <= east <= 180 and -90 <= south <= north <= 90):
                raise ValueError("Geometry must use WGS84 longitude/latitude")
        if self.complete_geometry and self.geometry is None:
            raise ValueError("Complete geometry cannot be absent")
        if self.geometry_precision == "representative_point" and self.complete_geometry:
            raise ValueError("A fallback representative point is not complete geometry")
        return self

    @property
    def identity_key(self) -> str:
        wikidata = self.tags.get("wikidata", "")
        if wikidata.startswith("Q") and wikidata[1:].isdigit():
            return "wikidata:" + wikidata
        return self.id


class MapMatchCandidate(MapModel):
    entity: MapLandmark
    score: float = Field(ge=0, le=1)
    score_components: dict[str, float]
    reasons: list[str]
    matched_query: str
    matched_map_name: str
    query_source: Literal["primary", "candidate"]
    identity_certain: bool = False
    equivalent_entity_ids: list[str] = Field(default_factory=list)


class LandmarkMatch(MapModel):
    image_landmark_id: str
    image_name: str
    candidates: list[MapMatchCandidate]
    status: Literal["UNMATCHED", "TENTATIVE", "AMBIGUOUS"]
    unmatched_reason: str | None = None


class RegionHypothesis(MapModel):
    region_id: str
    assignments: dict[str, str]
    score: float = Field(ge=0, le=1)
    matched_objects: int = Field(ge=1)
    max_pair_distance_m: float = Field(ge=0)
    geographically_consistent: bool = True
    identity_certain: bool = False
    reasons: list[str]


class MapMatchingResult(MapModel):
    status: Literal["NO_MATCH", "INSUFFICIENT_EVIDENCE", "TENTATIVE", "AMBIGUOUS"]
    matches: list[LandmarkMatch]
    region_hypotheses: list[RegionHypothesis]
    distinct_image_relations: list[SpatialRelation]
    consistency_checks: dict[str, int]
    warnings: list[str]
    coverage_regions: list[str]
    scoring_version: str = "stage3-heuristic-v1"
