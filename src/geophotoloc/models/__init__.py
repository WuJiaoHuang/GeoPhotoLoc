"""Validated interfaces shared by subsequent stages."""

from .landmark import GeoPoint, Landmark
from .localization import CandidatePose, LocalizationResult, LocalizationStatus
from .observation import BoundingBox, ImageLandmark, RelationType, SpatialRelation
from .vision import ImageMetadata, ImageSize, VisionExtractionResult, VisionLandmark

__all__ = [
    "GeoPoint", "Landmark", "ImageLandmark", "RelationType", "SpatialRelation",
    "CandidatePose", "LocalizationResult", "LocalizationStatus",
    "BoundingBox", "ImageMetadata", "ImageSize", "VisionExtractionResult", "VisionLandmark",
]
