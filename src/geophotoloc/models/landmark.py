"""Map entities in WGS84 (decimal degrees)."""

from pydantic import BaseModel, ConfigDict, Field


class GeoPoint(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class Landmark(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    location: GeoPoint
    osm_id: str | int | None = None
    aliases: list[str] = Field(default_factory=list)
