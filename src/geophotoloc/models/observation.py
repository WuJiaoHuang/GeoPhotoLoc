"""Image measurements and named spatial relations."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


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


class SpatialRelation(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    subject_id: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    relation_type: RelationType
    confidence: float | None = Field(default=None, ge=0, le=1)
