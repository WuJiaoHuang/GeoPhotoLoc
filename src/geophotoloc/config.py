"""Explicit geometry tolerances; no secrets or external service configuration."""

from pydantic import BaseModel, ConfigDict, Field


class GeometryConfig(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    distance_tolerance_m: float = Field(default=1e-6, gt=0)
    angular_tolerance_deg: float = Field(default=0.1, gt=0, lt=90)
