"""Bounded lifecycle requests over the existing canonical AV-memory snapshots.

Independent implementation of the lifecycle protocol documented by QwenLM/
Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f (Apache-2.0).
Changed: explicit byte commitments, caller-labelled clocks/identity links, immutable
revisions, and evidence-only watch/replay through the existing AV route.
"""

import math
from typing import Annotated, Literal, Union

from pydantic import Field, model_validator

from .image_edit import Digest, Number, StrictModel
from .video_memory_av import AVRoute, ArtifactRef, FactInput, LocalPath, PersonId

Positive = Annotated[int, Field(strict=True, ge=1)]
Window = Annotated[int, Field(strict=True, ge=0, le=511)]
Label = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]
Duration = Annotated[Number, Field(gt=0, le=15360)]


class LifecycleConfig(StrictModel):
    """Semantic configuration; any change forbids reuse of a prior checkpoint."""

    protocol: Literal["av-lifecycle/1"] = "av-lifecycle/1"
    profile: Label = "supplied-artifacts-v1"
    av_route: AVRoute | None = None


class InvocationLimits(StrictModel):
    """Finite work per invocation; these limits never change the planned denominator."""

    max_windows: Annotated[int, Field(strict=True, ge=1, le=64)] = 16
    timeout_seconds: Annotated[Number, Field(gt=0, le=60)] = 30.0


class RetainedClip(StrictModel):
    """Caller-selected clip bytes; parent-clock correspondence is caller asserted."""

    window: Window
    path: LocalPath
    sha256: Digest
    bytes: Annotated[int, Field(strict=True, ge=1, le=32 * 1024 * 1024)]


class Segment(StrictModel):
    """One chronological source, with explicit observations and optional identity links."""

    segment_id: Label
    file_path: LocalPath
    expected_source_sha256: Digest
    expected_source_bytes: Positive
    duration_seconds: Duration
    clock_basis: Literal["caller_asserted"] = "caller_asserted"
    artifacts: Annotated[list[ArtifactRef], Field(max_length=16)] = []
    clips: Annotated[list[RetainedClip], Field(max_length=512)] = []
    identity_bindings: dict[Annotated[str, Field(min_length=1, max_length=128)], PersonId] = {}
    identity_basis: Literal["user_asserted"] = "user_asserted"
    facts: Annotated[list[FactInput], Field(max_length=256)] = []

    @model_validator(mode="after")
    def unique_inputs(self):
        """Reject duplicate inputs and clip indices before work starts."""
        if len({a.sha256 for a in self.artifacts}) != len(self.artifacts):
            raise ValueError("Duplicate artifact digest")
        if sum(a.kind == "transcript" for a in self.artifacts) > 1:
            raise ValueError("Only one transcript per source")
        if len({c.window for c in self.clips}) != len(self.clips):
            raise ValueError("Duplicate retained clip window")
        if len(self.identity_bindings) > 999:
            raise ValueError("Too many identity bindings")
        return self


class PlannedSegment(StrictModel):
    """Frozen source manifest and its caller-declared position on the global clock."""

    source: Segment
    offset_seconds: Annotated[Number, Field(ge=0)]
    planned_windows: Positive


class Checkpoint(StrictModel):
    """Progress embedded in AV revision history, rather than a second memory store."""

    schema_version: Literal[1] = 1
    config_sha256: Digest
    segments: Annotated[list[PlannedSegment], Field(min_length=1, max_length=16)]
    extracted: list[str] = []
    failure: dict | None = None

    @model_validator(mode="after")
    def valid_progress(self):
        """Completion is exactly a chronological prefix of the frozen plan."""
        offset = 0.0
        for segment in self.segments:
            if segment.planned_windows != math.ceil(segment.source.duration_seconds / 30):
                raise ValueError("Planned denominator differs from the declared source clock")
            if segment.offset_seconds != offset:
                raise ValueError("Source offsets are not one chronological global timeline")
            offset += segment.source.duration_seconds
        wanted = [f"{s.source.segment_id}:{w}" for s in self.segments
                  for w in range(s.planned_windows)]
        if len(wanted) > 512 or len(set(wanted)) != len(wanted):
            raise ValueError("Plan exceeds 512 windows or repeats segment IDs")
        if self.extracted != wanted[:len(self.extracted)]:
            raise ValueError("Checkpoint progress is not a chronological plan prefix")
        return self


class LifecycleRef(StrictModel):
    """Exact anchor source, semantic configuration and memory directory."""

    memory_dir: LocalPath
    expected_source_sha256: Digest
    config: LifecycleConfig = LifecycleConfig()


class BuildLifecycle(LifecycleRef):
    """Freeze all source windows, then ingest at most one finite invocation."""

    action: Literal["build"]
    segments: Annotated[list[Segment], Field(min_length=1, max_length=16)]
    limits: InvocationLimits = InvocationLimits()


class AppendLifecycle(LifecycleRef):
    """Extend only a completed memory; retain all earlier canonical results."""

    action: Literal["append"]
    expected_revision: Positive
    segments: Annotated[list[Segment], Field(min_length=1, max_length=16)]
    limits: InvocationLimits = InvocationLimits()


class ResumeLifecycle(LifecycleRef):
    """Resume the frozen plan once, without reprocessing its completed prefix."""

    action: Literal["resume"]
    expected_revision: Positive
    limits: InvocationLimits = InvocationLimits()


class StatusLifecycle(LifecycleRef):
    """Verify source/config freshness and return exact extracted/planned coverage."""

    action: Literal["status"]


class ReplayLimits(StrictModel):
    """Explicit clip, payload, media-duration and invocation-time ceilings."""

    max_clips: Annotated[int, Field(strict=True, ge=1, le=8)] = 3
    max_payload_bytes: Annotated[int, Field(strict=True, ge=1, le=32 * 1024 * 1024)] = 8 * 1024 * 1024
    max_duration_seconds: Annotated[Number, Field(gt=0, le=1800)] = 120.0
    timeout_seconds: Annotated[Number, Field(gt=0, le=60)] = 30.0


class ReplayLifecycle(LifecycleRef):
    """Inspect selected retained clips through an explicitly authorized AV route."""

    action: Literal["replay"]
    av_route: AVRoute | None = None
    clips: Annotated[list[Annotated[str, Field(max_length=80)]], Field(min_length=1, max_length=512)]
    limits: ReplayLimits = ReplayLimits()


class WatchLifecycle(StrictModel):
    """Watch one caller-described source without building a memory or background job."""

    action: Literal["watch"]
    source: Segment
    config: LifecycleConfig = LifecycleConfig()
    limits: ReplayLimits = ReplayLimits()


VideoMemoryLifecycleRequest = Annotated[
    Union[BuildLifecycle, AppendLifecycle, ResumeLifecycle, StatusLifecycle,
          ReplayLifecycle, WatchLifecycle], Field(discriminator="action"),
]
