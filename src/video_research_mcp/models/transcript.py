"""Strict captions-first requests and explicit source/asserted versus inferred transcripts."""

import json
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from .image_edit import Digest, Number, StrictModel
from ..errors import ToolError


class ASRService(StrictModel):
    """One explicitly configured ASR wire; qualification is operator asserted."""

    base_url: Annotated[str, Field(min_length=1, max_length=2048)]
    local: Annotated[bool, Field(strict=True)] = False
    api_key_env: Annotated[str | None, Field(pattern=r"^[A-Z][A-Z0-9_]*API_KEY$")] = None
    declared_model: Annotated[str | None, Field(min_length=1, max_length=256)] = None
    runtime_qualified: Annotated[bool, Field(strict=True)] = False
    protocol: Literal["qwen", "faster_whisper_v1"] = "qwen"
    expected_descriptor_sha256: Digest | None = None

    @model_validator(mode="after")
    def configured_origin(self):
        """Reject credentials/queries and constrain local services to literal loopback."""
        p = urlsplit(self.base_url)
        if not p.hostname or p.username is not None or p.password is not None or p.query or p.fragment or any(ord(c) <= 32 for c in self.base_url):
            raise ValueError("ASR service requires an origin without credentials, query or fragment")
        if self.local:
            if p.scheme not in {"http", "https"} or p.hostname not in {"127.0.0.1", "::1"}:
                raise ValueError("Local ASR requires literal loopback")
        elif p.scheme != "https":
            raise ValueError("Remote ASR requires HTTPS")
        if p.port is not None and not 1 <= p.port <= 65535:
            raise ValueError("ASR service port is invalid")
        if self.protocol == "faster_whisper_v1" and (not self.local or self.expected_descriptor_sha256 is None or self.api_key_env is not None):
            raise ValueError("Timed local ASR requires literal loopback, an exact descriptor digest and no remote credential")
        return self


class CaptionSource(StrictModel):
    """An explicit exact caption file, or one explicitly selected embedded subtitle track."""

    origin: Literal["uploaded", "embedded", "native", "sidecar"]
    source_sha256: Digest
    format: Literal["srt", "vtt", "json", "tsv"] = "srt"
    file_path: Annotated[str | None, Field(min_length=1, max_length=4096)] = None
    expected_sha256: Digest | None = None
    embedded_track: Annotated[int | None, Field(strict=True, ge=0, le=7)] = None
    language: Annotated[str | None, Field(min_length=1, max_length=32)] = None

    @model_validator(mode="after")
    def exact_caption(self):
        """An embedded extraction has no preexisting bytes; all provided files require a digest."""
        if self.embedded_track is not None:
            if self.origin != "embedded" or self.file_path is not None or self.expected_sha256 is not None or self.format != "srt":
                raise ValueError("Embedded extraction requires only an embedded track and SRT format")
        elif self.file_path is None or self.expected_sha256 is None:
            raise ValueError("Provided captions require an exact file path and SHA256")
        return self


class TranscriptWord(StrictModel):
    """An actual supplied or inferred word interval, never proportional text subdivision."""

    text: Annotated[str, Field(min_length=1, max_length=1024)]
    start_seconds: Annotated[Number, Field(ge=0)]
    end_seconds: Annotated[Number, Field(gt=0)]

    @model_validator(mode="after")
    def interval(self):
        """Require a useful positive finite word interval."""
        if self.end_seconds <= self.start_seconds or not self.text.strip():
            raise ValueError("Word interval must be positive with nonempty text")
        return self


class TranscriptCue(StrictModel):
    """Sentence/cue times and optional word/speaker values with separate evidence provenance."""

    start_seconds: Annotated[Number, Field(ge=0)]
    end_seconds: Annotated[Number, Field(gt=0)]
    text: Annotated[str, Field(min_length=1, max_length=8192)]
    speaker_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None
    words: Annotated[list[TranscriptWord], Field(max_length=128)] = []

    @model_validator(mode="after")
    def matched_words(self):
        """Keep every word inside its sentence and require matching actual text population."""
        if self.end_seconds <= self.start_seconds or not self.text.strip():
            raise ValueError("Transcript cue requires positive duration and nonempty text")
        previous = self.start_seconds
        for word in self.words:
            if word.start_seconds < previous or word.start_seconds < self.start_seconds or word.end_seconds > self.end_seconds:
                raise ValueError("Word intervals are unordered or outside their sentence")
            previous = word.start_seconds
        if self.words and "".join("".join(w.text.split()) for w in self.words) != "".join(self.text.split()):
            raise ValueError("Word text does not match its complete sentence text")
        return self


class TranscriptSegment(TranscriptCue):
    """A source record ID or stable server-assigned inferred record ID."""

    id: Annotated[str, Field(min_length=1, max_length=128)]


class CaptionDocument(StrictModel):
    """Full-precision canonical round-trip; input provenance remains an unverified assertion."""

    schema_version: Literal[1] = 1
    segments: Annotated[list[TranscriptSegment], Field(max_length=512)]
    provenance: dict = {}

    @model_validator(mode="before")
    @classmethod
    def declared_version(cls, value):
        """Do not coerce a boolean or missing schema version into an admitted document."""
        if not isinstance(value, dict) or type(value.get("schema_version")) is not int or value["schema_version"] != 1:
            raise ValueError("Canonical captions require integer schema_version1")
        return value


class ASRAnswer(StrictModel):
    """WAV-relative model answer; empty and explicitly abstained are distinct."""

    outcome: Literal["transcript", "empty", "abstained"]
    segments: Annotated[list[TranscriptCue], Field(max_length=128)]
    abstentions: Annotated[list[Annotated[str, Field(max_length=2048)]], Field(max_length=32)] = []

    @model_validator(mode="before")
    @classmethod
    def bounded_answer(cls, value):
        """Match the existing per-window finite128KiB structured response ceiling."""
        if len(json.dumps(value, allow_nan=False, default=lambda item: item.model_dump(mode="json")).encode()) > 128 * 1024:
            raise ValueError("ASR answer exceeds128KiB")
        return value

    @model_validator(mode="after")
    def truthful_population(self):
        """Prevent malformed empty/nonempty outcomes from being promoted into speech."""
        if (self.outcome == "transcript") != bool(self.segments) or (self.outcome == "abstained" and not self.abstentions) or (self.outcome == "empty" and self.abstentions):
            raise ValueError("ASR outcome differs from its actual record population")
        return self


class TranscriptLimits(StrictModel):
    """Audio-only ceilings, including serialized schema and repeated submissions."""

    max_calls: Annotated[int, Field(strict=True, ge=1, le=24)] = 8
    max_tokens: Annotated[int, Field(strict=True, ge=1, le=2000000)] = 100000
    max_output_tokens: Annotated[int, Field(strict=True, ge=1, le=8192)] = 2048
    max_windows: Annotated[int, Field(strict=True, ge=1, le=4)] = 4
    max_payload_bytes: Annotated[int, Field(strict=True, ge=1, le=8 * 1024 * 1024)] = 8 * 1024 * 1024
    max_transmitted_bytes: Annotated[int, Field(strict=True, ge=1, le=64 * 1024 * 1024)] = 32 * 1024 * 1024
    timeout_seconds: Annotated[Number, Field(gt=0, le=120)] = 120

    @model_validator(mode="after")
    def token_reservation(self):
        """Reject an impossible output reservation before dispatch."""
        if self.max_output_tokens > self.max_tokens:
            raise ValueError("Output tokens exceed the total transcript allowance")
        return self


class TranscriptRequest(StrictModel):
    """One exact source, explicit captions/backend, and an absent durable output namespace."""

    action: Literal["transcribe", "readback"] = "transcribe"
    file_path: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_source_sha256: Digest
    output_directory: Annotated[str, Field(min_length=1, max_length=4096)]
    expected_receipt_sha256: Digest | None = None
    start_seconds: Annotated[Number, Field(ge=0)] = 0
    end_seconds: Annotated[Number | None, Field(gt=0)] = None
    window_seconds: Annotated[Number, Field(ge=1, le=30)] = 30
    caption_sources: Annotated[list[CaptionSource], Field(max_length=8)] = []
    caption_preference: list[Literal["uploaded", "embedded", "native", "sidecar"]] = ["uploaded", "embedded", "native", "sidecar"]
    backend: Literal["none", "gemini", "qwen", "faster_whisper"] = "none"
    fallback_backend: Literal["qwen"] | None = None
    local_only: Annotated[bool, Field(strict=True)] = False
    language: Annotated[str | None, Field(min_length=1, max_length=32)] = None
    glossary: Annotated[list[Annotated[str, Field(min_length=1, max_length=128)]], Field(max_length=32)] = []
    require_timestamps: Annotated[bool, Field(strict=True)] = True
    require_word_alignment: Annotated[bool, Field(strict=True)] = False
    dry_run: Annotated[bool, Field(strict=True)] = True
    authorize_submission: Annotated[bool, Field(strict=True)] = False
    export_formats: Annotated[list[Literal["json", "text", "srt", "vtt", "tsv"]], Field(min_length=1, max_length=5)] = ["json", "text", "srt"]
    thinking_level: Literal["low", "medium", "high"] = "medium"
    limits: TranscriptLimits = TranscriptLimits()

    @model_validator(mode="after")
    def workflow(self):
        """Refuse ambiguous policies, mismatched sources and cloud selection in local-only mode."""
        if self.end_seconds is not None and self.end_seconds <= self.start_seconds:
            raise ValueError("Transcript selection must be positive")
        if set(self.caption_preference) != {"uploaded", "embedded", "native", "sidecar"} or len(self.caption_preference) != 4:
            raise ValueError("Caption preference must contain each origin exactly once")
        if len(set(self.export_formats)) != len(self.export_formats):
            raise ValueError("Transcript export formats must be unique")
        if any(c.source_sha256 != self.expected_source_sha256 for c in self.caption_sources):
            raise ValueError("Caption source association differs from the exact media SHA256")
        if self.local_only and (self.backend == "gemini" or self.fallback_backend is not None):
            raise ValueError("Local-only forbids cloud selection or a cloud-to-local fallback plan")
        if self.fallback_backend is not None and self.backend != "gemini":
            raise ValueError("Explicit Qwen fallback belongs only to Gemini selection")
        if (self.action == "readback") != (self.expected_receipt_sha256 is not None):
            raise ValueError("Readback requires an independently trusted receipt SHA256")
        return self


class TranscriptResult(StrictModel):
    """Durable observed lineage with speech/word/speaker accuracy kept unverified."""

    operation: Literal["audio_transcribe"] = "audio_transcribe"
    status: Literal["planned", "complete", "partial", "failed"]
    outcome: Literal["planned", "captions", "inferred", "empty", "abstained", "partial", "failed"]
    source: dict | None
    request_sha256: Digest
    selection: dict | None
    captions: list[dict]
    segments: list[TranscriptSegment]
    untimed_text: list[dict]
    windows: list[dict]
    attempts: list[dict]
    exports: list[dict]
    artifacts: list[dict]
    provenance: dict
    warnings: list[str]
    execution: dict
    receipt: dict | None = None


class TranscriptFailure(ToolError):
    """A typed terminal failure retaining the complete bounded partial transcript state."""

    metadata: TranscriptResult
