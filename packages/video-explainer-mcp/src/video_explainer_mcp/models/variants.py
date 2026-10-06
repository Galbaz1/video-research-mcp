"""Finite local aspect/caption variants of a bound approved production render."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .materials import PinnedFile


class VariantRequest(BaseModel):
    """Select complete contiguous scenes, exact media, and an explicit local TTF."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_job_id: str = Field(min_length=1, max_length=128)
    source_video: PinnedFile
    scene_ids: list[str] = Field(min_length=1, max_length=16)
    aspects: list[Literal["16:9", "9:16", "1:1"]] = Field(default=["16:9", "9:16", "1:1"], min_length=1, max_length=3)
    font: PinnedFile
    captions: Literal["words", "srt"] = "words"
    srt: PinnedFile | None = None

    @model_validator(mode="after")
    def population(self):
        """Refuse duplicates and unsupported caption population changes."""
        if len(set(self.aspects)) != len(self.aspects) or len(set(self.scene_ids)) != len(self.scene_ids):
            raise ValueError("Scene IDs and aspects must be unique")
        if any(not 1 <= len(name) <= 100 for name in self.scene_ids):
            raise ValueError("Scene IDs require1..100 characters")
        if (self.captions == "srt") != (self.srt is not None):
            raise ValueError("SRT mode requires exactly one pinned SRT")
        return self
