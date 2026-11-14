"""Validated interfaces shared by subsequent stages."""

from .landmark import GeoPoint, Landmark
from .localization import CandidatePose, LocalizationResult, LocalizationStatus
from .observation import BoundingBox, ImageLandmark, RelationType, SpatialRelation
from .vision import ImageMetadata, ImageSize, VisionExtractionResult, VisionLandmark
from .maps import OSMEntity, MapLandmark, LandmarkMatch, MapMatchCandidate, MapMatchingResult
from .pose import PoseSearchConfig, PoseHypothesis, PoseConstraintScore, CandidateRegion, PoseLocalizationResult

__all__ = [
    "GeoPoint", "Landmark", "ImageLandmark", "RelationType", "SpatialRelation",
    "CandidatePose", "LocalizationResult", "LocalizationStatus",
    "BoundingBox", "ImageMetadata", "ImageSize", "VisionExtractionResult", "VisionLandmark",
    "OSMEntity", "MapLandmark", "LandmarkMatch", "MapMatchCandidate", "MapMatchingResult",
    "PoseSearchConfig", "PoseHypothesis", "PoseConstraintScore", "CandidateRegion", "PoseLocalizationResult",
]
