"""Explicit request limits for an opt-in, bounded video execution."""

from __future__ import annotations

import math

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class ExecutionLimits(BaseModel):
    """Limit operations and reserved tokens; prices and charges remain unverified."""

    model_config = ConfigDict(extra="forbid")

    max_calls: StrictInt = Field(ge=1, le=100)
    max_tokens: StrictInt = Field(ge=1)
    max_output_tokens: StrictInt = Field(ge=1)
    max_frames: StrictInt = Field(ge=1)
    max_windows: StrictInt = Field(ge=1)
    start_ms: StrictInt = Field(ge=0, le=2**53 - 1)
    end_ms: StrictInt = Field(gt=0, le=2**53 - 1)
    fps: float = Field(gt=0, le=30, strict=True, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_window(self) -> ExecutionLimits:
        """Reject impossible reservations before sending any source material."""
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must exceed start_ms")
        if self.max_output_tokens > self.max_tokens:
            raise ValueError("max_output_tokens exceeds the total token budget")
        if self.requested_frames > self.max_frames:
            raise ValueError("Requested window sampling exceeds max_frames")
        return self

    @property
    def requested_frames(self) -> int:
        """Return the requested static sampling count, not observed decoded frames."""
        return math.ceil((self.end_ms - self.start_ms) * self.fps / 1000)
