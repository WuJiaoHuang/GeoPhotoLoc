"""Geometry tolerances and explicit, non-mutating .env configuration loading."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError, field_validator


class GeometryConfig(BaseModel):
    model_config = ConfigDict(frozen=True, allow_inf_nan=False)

    distance_tolerance_m: float = Field(default=1e-6, gt=0)
    angular_tolerance_deg: float = Field(default=0.1, gt=0, lt=90)


class ConfigurationError(ValueError):
    """Safe configuration failure without exposing raw values or credentials."""


class VisionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, hide_input_in_errors=True)

    api_key: SecretStr = Field(repr=False)
    model: str = Field(default="qwen3.8-flash", min_length=1)
    base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    timeout: float = Field(default=60, gt=0, le=600)
    max_retries: int = Field(default=2, ge=0, le=5)

    @field_validator("api_key")
    @classmethod
    def key_present(cls, value):
        if not value.get_secret_value().strip():
            raise ValueError("API key is required")
        return value

    @field_validator("model")
    @classmethod
    def model_present(cls, value):
        if not value.strip():
            raise ValueError("Model name is required")
        return value

    @field_validator("base_url")
    @classmethod
    def valid_url(cls, value):
        parsed = urlsplit(value)
        if (parsed.scheme not in ("https", "http") or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("Base URL must be an HTTP(S) URL without credentials or query")
        return value

    @classmethod
    def from_env(cls, env_file: str | Path = ".env"):
        """Process environment overrides .env; neither is modified. No interpolation."""
        try:
            file_values = dotenv_values(env_file, encoding="utf-8-sig", interpolate=False)
            fields = {
                "api_key": "GEOPHOTOLOC_VLM_API_KEY",
                "model": "GEOPHOTOLOC_VLM_MODEL",
                "base_url": "GEOPHOTOLOC_VLM_BASE_URL",
                "timeout": "GEOPHOTOLOC_VLM_TIMEOUT",
                "max_retries": "GEOPHOTOLOC_VLM_MAX_RETRIES",
            }
            values = {}
            for field, variable in fields.items():
                if variable in os.environ:
                    values[field] = os.environ[variable]
                elif variable in file_values:
                    values[field] = file_values[variable]
            if not values.get("api_key"):
                raise ConfigurationError("Missing GEOPHOTOLOC_VLM_API_KEY in environment or .env")
            return cls.model_validate(values)
        except (OSError, UnicodeError, ValidationError):
            raise ConfigurationError(
                "Invalid vision configuration; check API key, model, base URL, timeout and retries"
            ) from None


class ImageProcessingConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)

    max_file_bytes: int = Field(default=20 * 1024 * 1024, gt=0)
    max_pixels: int = Field(default=40_000_000, gt=0)
    max_dimension: int = Field(default=1600, gt=0)
    max_encoded_bytes: int = Field(default=4 * 1024 * 1024, gt=0)
