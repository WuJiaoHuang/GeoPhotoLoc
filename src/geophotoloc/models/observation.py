"""Image measurements and named spatial relations."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BoundingBox(BaseModel):
    """Normalized image box, origin top left, axes right/down."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    x_min: float = Field(ge=0, le=1)
    y_min: float = Field(ge=0, le=1)
    x_max: float = Field(ge=0, le=1)
    y_max: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def ordered_edges(self):
        if self.x_min >= self.x_max or self.y_min >= self.y_max:
            raise ValueError("Bounding box must have positive width and height")
        return self


class RelationType(str, Enum):
    LEFT_OF = "LEFT_OF"
    RIGHT_OF = "RIGHT_OF"
    ABOVE = "ABOVE"
    BELOW = "BELOW"


class ImageLandmark(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    name: str = Field(min_length=1)
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    matched_landmark_id: str | None = None
    # Optional additions preserve the Stage 1 construction interface.
    id: str | None = Field(default=None, min_length=1)
    name_candidates: list[str] = Field(default_factory=list)
    bbox: BoundingBox | None = None
    visual_evidence: list[str] = Field(default_factory=list)
    identity_uncertain: bool = True
    coordinates_reliable: bool = False


class SpatialRelation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    subject_id: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    relation_type: RelationType
    confidence: float | None = Field(default=None, ge=0, le=1)
