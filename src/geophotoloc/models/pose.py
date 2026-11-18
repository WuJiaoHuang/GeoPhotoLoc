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
    adaptive_extent: bool = False
    footprint_constraints: bool = False
    visibility_soft: bool = False
    max_observation_distance_m: float = Field(default=5000, gt=5, le=10000)
    visibility_max_rays: int = Field(default=12, ge=1, le=12)
    viewpoint_fix: bool = False
    record_sample_trace: bool = False
    record_diagnostic_trace: bool = False
    selection_strategy: Literal['legacy', 'quality_v2'] = 'legacy'
    coarse_budget_fraction: float = Field(default=.6,gt=0,lt=1)
    fine_budget_fraction: float = Field(default=.3,ge=0,lt=1)
    minimum_coarse_spacing_m: float = Field(default=180,gt=0)
    maximum_coarse_spacing_m: float = Field(default=600,gt=0)
    minimum_visible_fraction: float = Field(default=.05,gt=0,le=1)
    minimum_visible_angle_deg: float = Field(default=.02,gt=0,lt=1)
    observation_x_tolerance: float = Field(default=.06,gt=0,le=.2)
    max_visibility_points_per_hypothesis: int = Field(default=20,ge=0,le=100)
    max_visibility_points_total: int = Field(default=100,ge=0,le=500)
    visibility_cache_size: int = Field(default=2048,ge=1,le=10000)
    robust_geometry: bool = False
    joint_identity: bool = False
    dual_regions: bool = False
    audit_hard_feasibility: bool = False
    max_identity_candidates: int = Field(default=3,ge=1,le=10)
    identity_beam_width: int = Field(default=24,ge=1,le=100)
    max_joint_hypotheses: int = Field(default=12,ge=1,le=50)
    same_object_groups: dict[str,str] = Field(default_factory=dict)
    huber_delta: float = Field(default=1.,gt=0,le=10)
    point_geometry_uncertainty_deg: float = Field(default=2.,ge=0,le=15)
    max_outliers: int = Field(default=1,ge=0,le=1)
    outlier_residual_threshold: float = Field(default=2.5,gt=1)
    outlier_loss_improvement: float = Field(default=1.,ge=0)
    outlier_identity_penalty: float = Field(default=.08,ge=0,le=1)
    contradictory_relation_weight: float = Field(default=.25,ge=0,le=1)
    unknown_projection_score: float = Field(default=.25,ge=0,le=.5)
    projection_weight: float = Field(default=.40,ge=0,le=1)
    order_weight: float = Field(default=.20,ge=0,le=1)
    identity_weight: float = Field(default=.25,ge=0,le=1)
    geometry_weight: float = Field(default=.15,ge=0,le=1)
    preferred_tile_size_m: float = Field(default=750,ge=180,le=3000)

    @model_validator(mode="before")
    @classmethod
    def enhanced_grid_default(cls, values):
        if isinstance(values,dict) and any(values.get(k) for k in ('adaptive_extent','footprint_constraints','visibility_soft')):
            values=dict(values)
            values.setdefault('coarse_spacing_m',250)
        return values

    @model_validator(mode="after")
    def valid_search(self):
        if self.selection_strategy=='quality_v2' and not (self.viewpoint_fix and self.robust_geometry and self.dual_regions):
            raise ValueError('quality_v2 requires fixed robust dual-region search')
        if abs(self.projection_weight+self.order_weight+self.identity_weight+self.geometry_weight-1)>1e-8:
            raise ValueError('Joint score weights must sum to one')
        if self.coarse_budget_fraction+self.fine_budget_fraction>1:
            raise ValueError('Coarse and fine budget fractions exceed one')
        if self.minimum_coarse_spacing_m>self.maximum_coarse_spacing_m:
            raise ValueError('Invalid dynamic spacing bounds')
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
    map_coverage_status: Literal['COMPLETE','PARTIAL','UNKNOWN'] = 'UNKNOWN'
    footprint_evidence: list[dict] = Field(default_factory=list)
    visibility_evidence: list[dict] = Field(default_factory=list)
    stage1_score: float | None = None
    stage2_score: float | None = None
    visibility_reviewed: bool = False
    partial_visibility_evidence: list[dict] = Field(default_factory=list)
    projection_evidence: list[dict] = Field(default_factory=list)
    order_evidence: list[dict] = Field(default_factory=list)
    outlier_image_ids: list[str] = Field(default_factory=list)
    outlier_comparisons: list[dict] = Field(default_factory=list)
    unknown_image_ids: list[str] = Field(default_factory=list)
    reliable_landmark_count: int = 0
    identifiability: str | None = None


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
    search_area_m2: float = 0
    distance_filtered_points: int = 0
    confirmed_order_conflicts: int = 0
    potentially_occluded_targets: int = 0
    map_coverage_status: Literal['COMPLETE','PARTIAL','UNKNOWN'] = 'UNKNOWN'
    budget: int = 0
    budget_allocation: dict = Field(default_factory=dict)
    component_sampling: list[dict] = Field(default_factory=list)
    sampled_geometry: dict | None = None
    unsearched_area_m2: float = 0
    sampling_completion_ratio: float = 0
    coarse_spacing_m: float | None = None
    timings: dict[str,float] = Field(default_factory=dict)
    sample_trace: list[dict] = Field(default_factory=list)
    visibility_review_points: int = 0
    strtree_queries: int = 0
    unknown_image_ids: list[str] = Field(default_factory=list)
    selection_audit: dict = Field(default_factory=dict)


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
    map_coverage_status: Literal['COMPLETE','PARTIAL','UNKNOWN'] = 'UNKNOWN'
    best_scored_point: GeoPoint | None = None
    region_medoid: GeoPoint | None = None


class FeasibleRegion(BaseModel):
    """Unexcluded sampled envelope, explicitly not a high-confidence prediction."""
    id: str
    hypothesis_id: str
    region_id: str
    geometry: dict
    area_m2: float = Field(ge=0)
    candidate_point_count: int
    component_count: int
    assignments: dict[str,str]
    map_coverage_status: Literal['COMPLETE','PARTIAL','UNKNOWN'] = 'UNKNOWN'
    priority: Literal['LOW_UNRANKED'] = 'LOW_UNRANKED'
    explanation: str = 'Not excluded by physical constraints; sampled cells are approximate, not high-confidence locations'


class PoseLocalizationResult(BaseModel):
    status: Literal["SUCCESS", "AMBIGUOUS", "INSUFFICIENT_EVIDENCE", "NO_FEASIBLE_POSE", "SEARCH_LIMITED"]
    regions: list[CandidateRegion]
    hypotheses: list[PoseHypothesis]
    config: PoseSearchConfig
    warnings: list[str]
    matched_landmarks: list[dict] = Field(default_factory=list)
    elapsed_seconds: float = 0
    geojson: dict
    diagnostics: dict = Field(default_factory=dict)
    reviewed_candidates: list[dict] = Field(default_factory=list)
    feasible_regions: list[FeasibleRegion] = Field(default_factory=list)
    preferred_regions: list[CandidateRegion] = Field(default_factory=list)
    feasible_area_m2: float = 0
    preferred_area_m2: float = 0
    identity_hypotheses: list[dict] = Field(default_factory=list)
    identifiability: str | None = None
