"""Stage 4 sampled feasible regions; scores and areas are not confidence bounds."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from .landmark import GeoPoint
from .maps import GeoBounds


class PoseSearchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    search_radius_m: float = Field(default=2200, gt=0, le=10000)
    search_bounds: GeoBounds | None = None
    coarse_spacing_m: float = Field(default=180, gt=0)
    fine_spacing_m: float = Field(default=60, gt=0)
    max_points_per_hypothesis: int = Field(default=4500, ge=1, le=100000)
    max_total_points: int = Field(default=24000, ge=1, le=500000)
    max_hypotheses: int = Field(default=10, ge=1, le=100)
    max_refine_components: int = Field(default=6, ge=1, le=50)
    refinement_levels: int = Field(default=1, ge=0, le=1)
    max_regions_per_hypothesis: int = Field(default=8, ge=1, le=50)
    fov_degrees: tuple[float, ...] = (60, 75, 90, 110, 130)
    principal_points: tuple[float, ...] = (0.47, 0.5, 0.53)
    angular_tolerance_deg: float = Field(default=0.5, gt=0, lt=10)
    x_tolerance: float = Field(default=0.03, gt=0, lt=0.3)
    minimum_distance_m: float = Field(default=5, gt=0)
    score_window: float = Field(default=0.08, ge=0, le=1)

    @model_validator(mode="after")
    def valid_search(self):
        if self.fine_spacing_m > self.coarse_spacing_m:
            raise ValueError("Fine spacing cannot exceed coarse spacing")
        if not self.fov_degrees or any(not 1 < x < 170 for x in self.fov_degrees):
            raise ValueError("FOV hypotheses must lie in (1,170) degrees")
        if not self.principal_points or any(not 0.3 <= x <= 0.7 for x in self.principal_points):
            raise ValueError("Principal point assumptions must lie in [0.3,0.7]")
        return self


class PoseConstraintScore(BaseModel):
    feasible: bool
    score: float = Field(ge=0, le=1)
    satisfied: int = 0
    conflicts: int = 0
    indeterminate: int = 0
    landmark_count: int = 0
    components: dict[str, float] = Field(default_factory=dict)
    heading: float | None = None
    fov_degrees: float | None = None
    principal_point_x: float | None = None
    projection_rmse: float | None = None
    span_deg: float | None = None
    camera_assumptions: list[dict[str, float]] = Field(default_factory=list)
    bearings_deg: dict[str, float] = Field(default_factory=dict)
    distances_m: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    filter_reasons: list[str] = Field(default_factory=list)


class PoseHypothesis(BaseModel):
    id: str
    region_id: str
    assignments: dict[str, str]
    searched_points: int = 0
    coarse_points: int = 0
    fine_points: int = 0
    feasible_points: int = 0
    filtered_points: int = 0
    elapsed_seconds: float = 0
    search_geometry: dict | None = None
    limited: bool = False
    reasons: list[str] = Field(default_factory=list)
    filtered_examples: list[dict] = Field(default_factory=list)


class CandidateRegion(BaseModel):
    id: str
    hypothesis_id: str
    region_id: str
    geometry: dict
    best_location: GeoPoint
    best_score: PoseConstraintScore
    area_m2: float
    bounds_wgs84: tuple[float, float, float, float]
    candidate_point_count: int
    assignments: dict[str, str]
    heading: float | None
    refined: bool
    touches_search_boundary: bool
    uncertainty: list[str]


class PoseLocalizationResult(BaseModel):
    status: Literal["SUCCESS", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE", "NO_FEASIBLE_POSE", "SEARCH_LIMITED"]
    regions: list[CandidateRegion]
    hypotheses: list[PoseHypothesis]
    config: PoseSearchConfig
    warnings: list[str]
    matched_landmarks: list[dict] = Field(default_factory=list)
    elapsed_seconds: float = 0
    geojson: dict
