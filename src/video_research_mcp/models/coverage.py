"""Controller-supplied media observations, separate from model timestamps."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MediaSpan(BaseModel):
    """A nonempty interval in the original source clock, in milliseconds."""

    model_config = ConfigDict(strict=True, extra="forbid")
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)

    @model_validator(mode="after")
    def ordered(self):
        """Reject reversed or empty intervals."""
        if self.end_ms <= self.start_ms:
            raise ValueError("Span end must follow start")
        return self


class MediaCoverage(BaseModel):
    """A caller's observation receipt; model output cannot create this authority.

    Extraction establishes available bytes, not observed content. Individual
    frames remain points and must never be expanded into intervals between frames.
    """

    model_config = ConfigDict(strict=True, extra="forbid")
    source_id: str = Field(min_length=1)
    source_revision: str | None = Field(default=None, min_length=1)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    measured_duration_ms: int | None = Field(default=None, gt=0)
    requested: list[MediaSpan] = Field(default_factory=list)
    extracted: list[MediaSpan] = Field(default_factory=list)
    observed: list[MediaSpan] = Field(default_factory=list)
    observed_frame_ms: list[int] = Field(default_factory=list)
    missing_stages: list[str] = Field(default_factory=lambda: ["media_observation"])

    @model_validator(mode="after")
    def bound_observations(self):
        """Require identity for observations and fence every span to measured media."""
        if (self.observed or self.observed_frame_ms) and not (
            self.source_revision and self.source_sha256
        ):
            raise ValueError("Observed media requires source revision and SHA-256")
        for group in (self.requested, self.extracted, self.observed):
            for span in group:
                if self.measured_duration_ms and span.end_ms > self.measured_duration_ms:
                    raise ValueError("Span exceeds measured media duration")
        for point in self.observed_frame_ms:
            if type(point) is not int or point < 0:
                raise ValueError("Observed frame time must be a nonnegative integer")
            if self.measured_duration_ms and point >= self.measured_duration_ms:
                raise ValueError("Observed frame is outside measured media duration")
        return self


class CoverageReport(BaseModel):
    """Observed interval union and gaps, never inferred from a final timestamp."""

    status: Literal["pass", "fail", "unknown"]
    observed_ratio: float | None = Field(default=None, ge=0, le=1)
    observed_ms: int = Field(default=0, ge=0)
    gaps: list[MediaSpan] = Field(default_factory=list)
    receipt: MediaCoverage


def summarize_coverage(receipt: MediaCoverage, minimum: float) -> CoverageReport:
    """Union actual observed intervals against measured duration; retain gaps."""
    if not 0 <= minimum <= 1:
        raise ValueError("Coverage minimum must be between zero and one")
    duration = receipt.measured_duration_ms
    merged: list[list[int]] = []
    for span in sorted(receipt.observed, key=lambda item: item.start_ms):
        if merged and span.start_ms <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], span.end_ms)
        else:
            merged.append([span.start_ms, span.end_ms])
    observed_ms = sum(end - start for start, end in merged)
    gaps = []
    cursor = 0
    if duration:
        for start, end in merged:
            if start > cursor:
                gaps.append(MediaSpan(start_ms=cursor, end_ms=start))
            cursor = end
        if cursor < duration:
            gaps.append(MediaSpan(start_ms=cursor, end_ms=duration))
    ratio = observed_ms / duration if duration else None
    status = "unknown"
    if ratio is not None and "media_observation" not in receipt.missing_stages:
        status = "pass" if ratio >= minimum else "fail"
    return CoverageReport(
        status=status,
        observed_ratio=ratio,
        observed_ms=observed_ms,
        gaps=gaps,
        receipt=receipt,
    )
