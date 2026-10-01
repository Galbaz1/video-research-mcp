"""Typed finite plans and exact-scene approvals for bounded local footage edits."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .image_delivery import ImageDelivery
from .image_edit import Digest, ManifestArtifact, Number


class StrictModel(BaseModel):
    """Reject extra fields, nonfinite numbers and scalar coercion."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class Grade(StrictModel):
    """Explicit small corrections; defaults preserve the decoded signal."""

    contrast: Annotated[Number, Field(ge=.94, le=1.08)] = 1.0
    gamma: Annotated[Number, Field(ge=.94, le=1.10)] = 1.0
    saturation: Annotated[Number, Field(ge=.94, le=1.06)] = 1.0


class AudioPolicy(StrictModel):
    """Keep source audio with attenuation or structurally omit it."""

    mode: Literal["preserve", "mute"] = "preserve"
    gain_db: Annotated[Number, Field(ge=-24, le=0)] = 0.0

    @model_validator(mode="after")
    def mute_has_no_gain(self):
        """A muted stream has no applied gain measurement."""
        if self.mode == "mute" and self.gain_db != 0:
            raise ValueError("Muted audio must use the neutral gain declaration")
        return self


class Scene(StrictModel):
    """One exact source revision, half-open interval and explicit timeline placement."""

    scene_id: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_source_sha256: Digest
    start_seconds: Annotated[Number, Field(ge=0)]
    end_seconds: Annotated[Number, Field(gt=0)]
    timeline_start_seconds: Annotated[Number, Field(ge=0)]
    crop_box: Annotated[list[Annotated[int, Field(strict=True)]], Field(min_length=4, max_length=4)] | None = None
    grade: Grade = Field(default_factory=Grade)
    audio: AudioPolicy = Field(default_factory=AudioPolicy)

    @model_validator(mode="after")
    def interval(self):
        """Reject reversed intervals and impossible crop geometry before native work."""
        if not 0 < self.end_seconds - self.start_seconds <= 256:
            raise ValueError("Scene requires a positive bounded half-open interval")
        if self.crop_box and (min(self.crop_box[:2]) < 0 or min(self.crop_box[2:]) < 1):
            raise ValueError("Crop requires nonnegative origin and positive dimensions")
        return self


class BeatDecision(StrictModel):
    """Caller-declared grid or explicit no-music/offbeat choice, never detected beats."""

    mode: Literal["none", "offbeat", "declared"] = "none"
    bpm: Annotated[Number, Field(gt=0, le=300)] | None = None
    origin_seconds: Annotated[Number, Field(ge=0)] | None = None
    tolerance_frames: Annotated[Number, Field(ge=0, le=3)] = 1.5

    @model_validator(mode="after")
    def grid(self):
        """Bind complete declared grids and keep no-music decisions unambiguous."""
        if (self.bpm is None) != (self.origin_seconds is None):
            raise ValueError("A declared grid requires both BPM and origin")
        if self.mode == "declared" and self.bpm is None:
            raise ValueError("Declared beat mode requires BPM and origin")
        if self.mode == "none" and self.bpm is not None:
            raise ValueError("No-music mode must not declare a beat grid")
        return self


class PrepareRequest(StrictModel):
    """Prepare a contiguous hard-cut plan without declaring final delivery."""

    action: Literal["prepare"]
    brief: Annotated[str, Field(min_length=1, max_length=4096)]
    fps: Annotated[Number, Field(gt=0, le=30)] = 24.0
    scenes: Annotated[list[Scene], Field(min_length=1, max_length=8)]
    beats: BeatDecision = Field(default_factory=BeatDecision)

    @model_validator(mode="after")
    def plan(self):
        """Require unique scenes, two exact sources and a bounded gapless timeline."""
        if not self.brief.strip() or len({s.scene_id for s in self.scenes}) != len(self.scenes):
            raise ValueError("Plan requires a brief and unique scene IDs")
        sources = {(s.file_path, s.expected_source_sha256) for s in self.scenes}
        if len(sources) > 2 or len({s.expected_source_sha256 for s in self.scenes}) > 2:
            raise ValueError("Plan supports at most two exact source revisions")
        endpoint = 0.0
        for scene in self.scenes:
            duration = scene.end_seconds - scene.start_seconds
            if abs(scene.timeline_start_seconds - endpoint) > 1e-9:
                raise ValueError("Timeline must start at zero without gaps or overlaps")
            if abs(duration * self.fps - round(duration * self.fps)) > 1e-6:
                raise ValueError("Scene duration must span whole declared timeline frames")
            endpoint += duration
        if not 1 <= round(endpoint * self.fps) <= 256:
            raise ValueError("Timeline exceeds the 256 frame budget")
        if len({s.audio.mode for s in self.scenes}) != 1:
            raise ValueError("This route requires one audio mode across all scenes")
        return self


class SceneApproval(StrictModel):
    """An external approval assertion committed to an entire measured scene file."""

    scene_id: Annotated[str, Field(pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")]
    scene_sha256: Digest
    prepared_manifest_sha256: Digest
    locked: bool


class AssembleRequest(StrictModel):
    """Reopen an exact prepared manifest and approve every actual scene revision."""

    action: Literal["assemble"]
    manifest_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_manifest_sha256: Digest
    approvals: Annotated[list[SceneApproval], Field(min_length=1, max_length=8)]


FootageEditRequest = Annotated[PrepareRequest | AssembleRequest, Field(discriminator="action")]


class FootageEditResult(StrictModel):
    """Measured artifacts and integrity commitments with explicit acceptance limits."""

    status: Literal["prepared", "delivered"]
    operation: Literal["local_footage_edit"] = "local_footage_edit"
    source: dict
    sources: list[dict]
    plan: dict
    plan_sha256: Digest
    scenes: list[dict]
    timeline: dict
    artifact: dict
    artifacts: list[dict]
    technical: dict
    native_identities: dict
    approval_status: dict
    provenance: dict
    warnings: list[str]
    limits: dict
    manifest: ManifestArtifact


class FootageEditResponse(StrictModel):
    """Identical metadata for native-image and text-only callers."""

    metadata: FootageEditResult
    native_images: list[ImageDelivery]
