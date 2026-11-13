"""Localization output contracts; no search is implemented in Stage 1."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

from .landmark import GeoPoint


class LocalizationStatus(str, Enum):
    SUCCESS = "SUCCESS"
    AMBIGUOUS = "AMBIGUOUS"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


class CandidatePose(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    location: GeoPoint
    heading: float | None = Field(default=None, ge=0, lt=360)
    score: float
    matched_constraints: int = Field(ge=0, strict=True)


class LocalizationResult(BaseModel):
    candidates: list[CandidatePose] = Field(default_factory=list)
    status: LocalizationStatus
    explanation: str
