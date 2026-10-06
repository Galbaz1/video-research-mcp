"""Strict evidence, grouping and operator endpoint contracts for video dubbing."""

from __future__ import annotations

import ipaddress
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, model_validator

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
Text = Annotated[str, Field(min_length=1, max_length=10000, pattern=r"\S")]
Seconds = Annotated[float, Field(ge=0, le=86400)]
Ids = Annotated[list[Text], Field(min_length=1, max_length=1000)]


class StrictModel(BaseModel):
    """Reject unknown fields, scalar coercion and nonfinite evidence."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class DubbingService(StrictModel):
    """An operator-selected origin; credentials remain in the environment."""

    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    local: bool = False

    @model_validator(mode="after")
    def origin(self):
        """Admit HTTPS public origins or explicitly local literal loopback."""
        value = self.base_url
        parsed = urlsplit(value)
        if (any(ord(c) <= 32 or ord(c) == 127 for c in value)
                or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or "?" in value or "#" in value
                or parsed.path not in {"", "/"}):
            raise ValueError("Dubbing service requires a clean origin")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("Dubbing service port is invalid")
        if self.local:
            if parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "::1"}:
                raise ValueError("Local dubbing requires literal loopback")
        elif parsed.scheme != "https":
            raise ValueError("Remote dubbing requires HTTPS")
        else:
            try:
                address = ipaddress.ip_address(parsed.hostname)
            except ValueError:
                address = None
            if address is not None and (not address.is_global or address.is_multicast):
                raise ValueError("Remote dubbing requires a public address")
        return self


class Artifact(StrictModel):
    """An exact, locally held regular-file identity."""

    path: Text
    sha256: Digest
    bytes: Annotated[int, Field(gt=0)]


class VadSettings(StrictModel):
    """Concrete TEN-VAD controls exposed by the pinned source tool."""

    threshold: Annotated[float, Field(ge=0, le=1)] = 0.5
    hop_size: Annotated[int, Field(ge=80, le=1024)] = 256
    min_speech: Annotated[float, Field(ge=0, le=10)] = 0.2
    min_silence: Annotated[float, Field(ge=0, le=10)] = 0.3
    pad: Annotated[float, Field(ge=0, le=2)] = 0.1


class Interval(StrictModel):
    """A positive absolute source interval in seconds."""

    start_sec: Seconds
    end_sec: Seconds

    @model_validator(mode="after")
    def positive(self):
        """Reject empty or reversed intervals."""
        if self.end_sec <= self.start_sec:
            raise ValueError("Interval end must follow start")
        return self


class VadEvidence(StrictModel):
    """Service speech presence bound to the actual source and vocal stem."""

    schema_version: Literal["vrm/video-dubbing-vad/v1"] = "vrm/video-dubbing-vad/v1"
    source_movie: Text
    source_sha256: Digest
    audio_sha256: Digest
    duration_sec: Annotated[float, Field(gt=0, le=86400)]
    sample_rate: Annotated[int, Field(gt=0, le=192000)]
    parameters: dict
    segments: Annotated[list[Interval], Field(min_length=1, max_length=10000)]


class TranscriptSegment(Interval):
    """Reconciled source speech, speaker and text, without invented certainty."""

    segment_id: Text
    speaker: Text
    source_text: Text


class Transcript(StrictModel):
    """Agent-authored evidence retaining analysis windows and unresolved issues."""

    schema_version: Literal["vrm/video-dubbing-transcript/v1"]
    source_movie: Text
    source_sha256: Digest
    vad_sha256: Digest
    source_language: Text
    evidence_windows: Annotated[list[Interval], Field(min_length=1, max_length=1000)]
    unresolved_issues: list[Text]
    segments: Annotated[list[TranscriptSegment], Field(min_length=1, max_length=1000)]


class SpeakerReference(Interval):
    """A clean same-speaker interval justified by specific transcript evidence."""

    source_segment_ids: Ids
    selection_reason: Text


class DubGroup(TranscriptSegment):
    """One spoken translation consuming consecutive source segments exactly once."""

    source_segment_ids: Ids
    translated_text: Text
    merge_reason: str = ""
    reference: SpeakerReference


class TranslationPlan(StrictModel):
    """A complete content-bound translation with source grouping and references."""

    schema_version: Literal["vrm/video-dubbing-plan/v1"]
    source_movie: Text
    source_sha256: Digest
    vad_sha256: Digest
    transcript_sha256: Digest
    source_language: Text
    target_language: Text
    segments: Annotated[list[DubGroup], Field(min_length=1, max_length=1000)]


class Project(StrictModel):
    """Prepared source, stems and speech evidence retained for analysis and render."""

    schema_version: Literal["vrm/video-dubbing-project/v1"] = "vrm/video-dubbing-project/v1"
    source_movie: Text
    source_sha256: Digest
    source_language: Text
    target_language: Text
    target: Literal["analysis_only", "translation_only", "full", "resume"] = "full"
    style_brief: Annotated[str, Field(max_length=10000)] = ""
    duration_sec: Annotated[float, Field(gt=0, le=86400)]
    source: Artifact
    source_audio: Artifact
    vocals: Artifact
    no_vocals: Artifact
    vad: Artifact


class ListeningReview(StrictModel):
    """A supplied human review bound to the exact render; never generated by QA."""

    schema_version: Literal["vrm/video-dubbing-listening/v1"]
    output_sha256: Digest
    plan_sha256: Digest
    reviewer: Text
    segment_checks: dict[str, dict[str, Literal["PASS", "FAIL", "UNRESOLVED"]]]
    issues: list[Text]
