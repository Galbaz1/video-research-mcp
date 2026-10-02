"""Exact-source local scene, storyboard, similarity and audio-export requests."""

from typing import Annotated

from pydantic import Field, StrictBool, model_validator

from .image_edit import Digest, Number, StrictModel


class SourceRequest(StrictModel):
    """One source revision; no caller-selected output location or overwrite."""

    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_source_sha256: Digest


class WindowRequest(SourceRequest):
    """Omitted endpoints select the whole source within the operation's limits."""

    start_seconds: Annotated[Number, Field(ge=0)] = 0
    end_seconds: Annotated[Number | None, Field(gt=0)] = None

    @model_validator(mode="after")
    def ordered(self):
        """Reject empty/reversed selections before opening source bytes."""
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("end_seconds must exceed start_seconds")
        return self


class SceneRequest(WindowRequest):
    """Hard visual-cut detection with a bounded returned boundary population."""

    threshold: Annotated[Number, Field(gt=0, lt=1)] = 0.3
    min_scene_seconds: Annotated[Number, Field(gt=0, le=60)] = 1
    max_cuts: Annotated[int, Field(strict=True, ge=1, le=256)] = 64


class StoryboardRequest(WindowRequest):
    """Bounded source-clock labels burned into measured frame tiles."""

    columns: Annotated[int, Field(strict=True, ge=1, le=6)] = 4
    rows: Annotated[int, Field(strict=True, ge=1, le=4)] = 2
    max_pixels: Annotated[int, Field(strict=True, ge=1, le=1000000)] = 1000000

    @model_validator(mode="after")
    def tile_limit(self):
        """Reject an excessive grid without silently removing requested tiles."""
        if self.columns * self.rows > 16:
            raise ValueError("Storyboard supports at most sixteen tiles")
        return self


class FrameDedupRequest(SourceRequest):
    """Every requested candidate remains in the lossy visual-similarity report."""

    times_seconds: Annotated[list[Annotated[Number, Field(ge=0)]], Field(min_length=1, max_length=64)]
    hamming_threshold: Annotated[int, Field(strict=True, ge=0, le=32)] = 6
    max_pixels: Annotated[int, Field(strict=True, ge=1, le=1000000)] = 16384


class AudioSegment(StrictModel):
    """A finite candidate interval for bounded mono PCM comparison."""

    start_seconds: Annotated[Number, Field(ge=0)]
    end_seconds: Annotated[Number, Field(gt=0)]

    @model_validator(mode="after")
    def bounded(self):
        """Bound each decoded MFCC matrix before any media process is launched."""
        if not 0 < self.end_seconds - self.start_seconds <= 30:
            raise ValueError("Audio candidates must be positive and at most thirty seconds")
        return self


class AudioDedupRequest(SourceRequest):
    """Explicit audio candidates; similarity does not establish equal speech."""

    segments: Annotated[list[AudioSegment], Field(min_length=1, max_length=64)]
    similarity_threshold: Annotated[Number, Field(ge=0, le=1)] = 0.95

    @model_validator(mode="after")
    def aggregate_audio(self):
        """Bound aggregate decoded sample work without dropping submitted candidates."""
        if sum(s.end_seconds - s.start_seconds for s in self.segments) > 120:
            raise ValueError("Audio candidates exceed the aggregate 120-second decode budget")
        return self


class AudioExportRequest(WindowRequest):
    """Whole or one-sided audio interval exported as bounded 16kHz mono PCM WAV."""


class ClipSelectionRequest(WindowRequest):
    """Whole or one-sided video selection using the existing short clip limits."""

    max_pixels: Annotated[int, Field(strict=True, ge=1, le=1000000)] = 1000000
    include_audio: StrictBool = True
