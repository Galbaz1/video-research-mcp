"""Licensed local narration/music/SFX mix requests with explicit rights and bounded cues."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .materials import PinnedFile


class AudioRights(BaseModel):
    """Caller-declared rights record pinned beside the audio bytes; not independently verified."""

    model_config = ConfigDict(extra="forbid")
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    license: str = Field(min_length=1, max_length=200)
    license_url: str = Field(min_length=1, max_length=2048)
    credit: str = Field(min_length=1, max_length=500)
    principal: str = Field(min_length=1, max_length=100)
    use_allowed: bool
    commercial_use: bool
    retrieved_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def explicit(self):
        """Require aware times and a concrete license."""
        if self.retrieved_at.tzinfo is None or self.valid_until.tzinfo is None:
            raise ValueError("Rights times require timezone offsets")
        if self.license.strip().lower() in {"unknown", "pending", "unlicensed"}:
            raise ValueError("An explicit audio license is required")
        return self


class AudioCue(BaseModel):
    """One local source placed on the output timeline at a declared storyboard/cue interval."""

    model_config = ConfigDict(extra="forbid")
    cue_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    role: Literal["narration", "music", "sfx"]
    source: PinnedFile
    rights: PinnedFile
    scene_id: str | None = Field(default=None, min_length=1, max_length=100, description="Storyboard scene; required for narration/sfx")
    start_seconds: float = Field(ge=0, le=300, allow_inf_nan=False)
    duration_seconds: float = Field(gt=0, le=300, allow_inf_nan=False)
    source_offset_seconds: float = Field(default=0, ge=0, le=300, allow_inf_nan=False)
    gain_db: float = Field(default=0, ge=-60, le=6, allow_inf_nan=False)
    fade_in_seconds: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)
    fade_out_seconds: float = Field(default=0, ge=0, le=10, allow_inf_nan=False)

    @model_validator(mode="after")
    def fades_fit(self):
        if self.fade_in_seconds + self.fade_out_seconds > self.duration_seconds:
            raise ValueError("Fades exceed the cue duration")
        if not self.source.path.lower().endswith(".wav"):
            raise ValueError("Only local .wav sources are supported")
        if self.role != "music" and self.scene_id is None:
            raise ValueError("Narration and SFX cues require a storyboard scene_id")
        return self


class AudioMixRequest(BaseModel):
    """A finite offline mix; music is ducked under narration, never generated or fetched."""

    model_config = ConfigDict(extra="forbid")
    principal: str = Field(min_length=1, max_length=100)
    storyboard: PinnedFile
    commercial: bool = False
    total_seconds: float = Field(gt=0, le=300, allow_inf_nan=False)
    cues: list[AudioCue] = Field(min_length=1, max_length=32)
    duck_db: float = Field(default=12, ge=0, le=30, allow_inf_nan=False,
                           description="Mapped to sidechain ratio 1+duck_db/2; attenuation is level-dependent, not a fixed dB")
    duck_attack_ms: int = Field(default=50, ge=1, le=2000)
    duck_release_ms: int = Field(default=400, ge=10, le=5000)
    sample_rate: Literal[44100, 48000] = 48000

    @model_validator(mode="after")
    def bounded_cues(self):
        """Unique cues inside the timeline; an identical source/interval may not be layered twice."""
        if len({c.cue_id for c in self.cues}) != len(self.cues):
            raise ValueError("Cue IDs must be unique")
        placed = [(c.role, c.source.sha256, c.start_seconds, c.source_offset_seconds) for c in self.cues]
        if len(set(placed)) != len(placed):
            raise ValueError("The same source is layered twice at the same interval")
        if any(c.start_seconds + c.duration_seconds > self.total_seconds for c in self.cues):
            raise ValueError("A cue extends past total_seconds")
        return self
