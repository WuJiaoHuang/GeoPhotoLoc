"""Strict image extraction contracts, extending the Stage 1 observations."""

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .observation import BoundingBox, ImageLandmark, RelationType, SpatialRelation


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class ImageSize(StrictModel):
    width: int = Field(gt=0)
    height: int = Field(gt=0)


class ImageMetadata(StrictModel):
    original_size: ImageSize
    oriented_size: ImageSize
    processed_size: ImageSize
    original_format: str
    encoded_format: str = "JPEG"
    original_bytes: int = Field(gt=0)
    processed_bytes: int = Field(gt=0)
    orientation_corrected: bool


class VisionLandmark(ImageLandmark):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    name_candidates: list[str]
    bbox: BoundingBox
    visual_evidence: list[str] = Field(min_length=1)
    identity_uncertain: bool
    coordinates_reliable: bool

    @field_validator("name")
    @classmethod
    def nonblank_name(cls, value):
        if not value.strip():
            raise ValueError("Name cannot be blank")
        return value

    @field_validator("name_candidates", "visual_evidence")
    @classmethod
    def nonblank_items(cls, values):
        if any(not value.strip() for value in values):
            raise ValueError("Descriptions cannot be blank")
        return values

    @model_validator(mode="after")
    def valid_center(self):
        if not (self.bbox.x_min <= self.x <= self.bbox.x_max
                and self.bbox.y_min <= self.y <= self.bbox.y_max):
            raise ValueError("Landmark center must lie inside its bounding box")
        if self.matched_landmark_id is not None:
            raise ValueError("Vision extraction cannot assign map entity IDs")
        return self


class VisionResponse(StrictModel):
    """Only this schema is requested from the remote model."""

    landmarks: list[VisionLandmark] = Field(max_length=100)
    scene_features: list[str]
    warnings: list[str]

    @model_validator(mode="after")
    def unique_ids(self):
        ids = [landmark.id for landmark in self.landmarks]
        if len(ids) != len(set(ids)):
            raise ValueError("Landmark IDs must be unique")
        return self


class VisionSpatialRelation(SpatialRelation):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class VisionExtractionResult(VisionResponse):
    image: ImageMetadata
    relations: list[VisionSpatialRelation]
    relation_min_gap: float = Field(default=0.03, gt=0, lt=1)

    @model_validator(mode="after")
    def consistent_relations(self):
        landmarks = {landmark.id: landmark for landmark in self.landmarks}
        seen = set()
        for relation in self.relations:
            a = landmarks.get(relation.subject_id)
            b = landmarks.get(relation.object_id)
            if a is None or b is None or a.id == b.id:
                raise ValueError("Relation must reference two distinct known landmarks")
            if not (a.coordinates_reliable and b.coordinates_reliable):
                raise ValueError("Relation requires reliable image coordinates")
            key = (a.id, b.id, relation.relation_type)
            if key in seen:
                raise ValueError("Duplicate relation")
            seen.add(key)
            gap = {
                RelationType.LEFT_OF: b.x - a.x,
                RelationType.RIGHT_OF: a.x - b.x,
                RelationType.ABOVE: b.y - a.y,
                RelationType.BELOW: a.y - b.y,
            }[relation.relation_type]
            if gap <= self.relation_min_gap + 1e-12:
                raise ValueError("Relation conflicts with image coordinates or minimum gap")
        return self
