"""Strict local window selection and separately bounded synchronous runs."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class WindowRunLimits(BaseModel):
    """Bound count/generation transmissions; File API preparation is separate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    max_calls: StrictInt = Field(ge=1, le=100)
    max_tokens: StrictInt = Field(ge=1)
    max_output_tokens: StrictInt = Field(ge=1)
    max_frames: StrictInt = Field(ge=1)
    max_windows: StrictInt = Field(ge=1)

    @model_validator(mode="after")
    def validate_tokens(self) -> WindowRunLimits:
        """Reject an output reservation larger than the total token allowance."""
        if self.max_output_tokens > self.max_tokens:
            raise ValueError("max_output_tokens exceeds max_tokens")
        return self


class WindowAnalysisRequest(BaseModel):
    """Select half-open windows on the original source's millisecond timeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    file_path: str | None = Field(default=None, min_length=1)
    url: str | None = Field(default=None, min_length=1)
    instruction: str = Field(min_length=1)
    start_ms: StrictInt = Field(default=0, ge=0, le=2**53 - 1)
    end_ms: StrictInt = Field(gt=0, le=2**53 - 1)
    window_ms: StrictInt = Field(default=300000, gt=0, le=2**53 - 1)
    fps: float | None = Field(default=None, gt=0, le=30, strict=True, allow_inf_nan=False)
    output_schema: dict | None = None
    thinking_level: str = "high"

    @model_validator(mode="after")
    def validate_interval(self) -> WindowAnalysisRequest:
        """Reject empty, reversed or excessive window sets before reading media."""
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must exceed start_ms")
        if (self.file_path is None) == (self.url is None):
            raise ValueError("Exactly one of file_path or YouTube url is required")
        if (self.end_ms - self.start_ms + self.window_ms - 1) // self.window_ms > 256:
            raise ValueError("A plan may select at most 256 windows")
        return self
