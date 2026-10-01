"""Explicit source windows and bounded deterministic or optional native DSP operations."""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from .scene_assets import WindowRequest

Operation = Literal[
    "analyze",
    "compare",
    "audio_info",
    "spectral_features",
    "harmonic_analysis",
    "rhythm_analysis",
    "full_analysis",
    "juzzy_compare",
    "ferrous_analyze",
    "ferrous_compare",
]


class AudioDspRequest(WindowRequest):
    """One immutable analysis or A/B comparison; optional binaries are operator configured."""

    operation: Operation = "analyze"
    reference: WindowRequest | None = None
    max_events: Annotated[int, Field(strict=True, ge=1, le=128)] = 128
    native_return_format: Literal["summary", "full", "visual_only"] = "summary"
    job_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None

    @model_validator(mode="after")
    def bounded(self):
        """Reject incompatible references and oversized windows before any file or process work."""
        compare = self.operation in {"compare", "juzzy_compare", "ferrous_compare"}
        if compare != (self.reference is not None):
            raise ValueError("Only comparison operations require and accept a reference source")
        if self.native_return_format != "summary" and self.operation != "ferrous_analyze":
            raise ValueError("Native return formats apply only to ferrous_analyze")
        for window in (self, self.reference):
            if (
                window is not None
                and window.end_seconds is not None
                and window.end_seconds - window.start_seconds > 30
            ):
                raise ValueError("Each DSP window must be at most30 seconds")
        windows = [self] + ([self.reference] if self.reference else [])
        if (
            all(w.end_seconds is not None for w in windows)
            and sum(w.end_seconds - w.start_seconds for w in windows) > 30
        ):
            raise ValueError("DSP primary and reference exceed30 seconds aggregate selected audio")
        return self


class AudioDspResponse(BaseModel):
    """Finite source-bound report or retained terminal error with an independently attested job."""

    metadata: dict
    job_receipt: dict
    native_images: list[dict] = Field(default_factory=list)
