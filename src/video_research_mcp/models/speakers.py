"""Strict local speaker diarization, relabel, sample, registry and enrollment contracts."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field, StrictBool, model_validator

from .image_edit import Digest, Number, StrictModel

MAX_SELECTION_SECONDS = 120

LocalPath = Annotated[str, Field(min_length=1, max_length=4096)]
SpeakerName = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")]
ClusterLabel = Annotated[str, Field(pattern=r"^SPEAKER_[0-9]{2}$")]
Role = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,31}$")]


def _bounded(start: float, end: float, minimum: float = 0) -> None:
    """Refuse empty, reversed, too-short or over-long selections instead of truncating them."""
    span = end - start
    if span <= 0 or span < minimum or span > MAX_SELECTION_SECONDS:
        raise ValueError(f"Speaker audio selection must be non-empty, >= {minimum}s and <= {MAX_SELECTION_SECONDS}s")


class RuntimeModel(StrictModel):
    """One pinned local ONNX model; the licence text is a Root admission statement."""

    path: LocalPath
    sha256: Digest
    bytes: Annotated[int, Field(strict=True, ge=1)]
    license: Annotated[str, Field(min_length=1, max_length=512)]


class EmbeddingModel(RuntimeModel):
    """Speaker-embedding model; its dimension is declared, then rechecked by the worker."""

    dimension: Annotated[int, Field(strict=True, ge=1, le=4096)]


class SpeakerRuntime(StrictModel):
    """speaker-runtime/v1: separately installed interpreter, packages and models; no defaults."""

    format: Literal["speaker-runtime/v1"]
    python: LocalPath
    site_packages: LocalPath
    sherpa_onnx_version: Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
    provider: Literal["cpu"]
    num_threads: Annotated[int, Field(strict=True, ge=1, le=8)]
    segmentation_model: RuntimeModel
    embedding_model: EmbeddingModel

    @model_validator(mode="after")
    def absolute_paths(self):
        """Keep interpreter, packages and models independent of the server working directory."""
        paths = (self.python, self.site_packages, self.segmentation_model.path, self.embedding_model.path)
        if not all(Path(path).is_absolute() for path in paths):
            raise ValueError("Speaker runtime paths must be absolute")
        return self


class RecordReference(StrictModel):
    """One SHA-bound speaker-diarization/v1 record written by the diarize action."""

    diarization_record_path: LocalPath
    expected_record_sha256: Digest


class DiarizeRequest(StrictModel):
    """Anonymous turns for one bounded exact-source selection through the optional runtime."""

    action: Literal["diarize"]
    file_path: LocalPath
    expected_source_sha256: Digest
    output_directory: LocalPath
    start_seconds: Annotated[Number, Field(ge=0)] = 0
    end_seconds: Annotated[Number, Field(gt=0)]
    runtime_descriptor_path: LocalPath
    expected_runtime_descriptor_sha256: Digest
    num_speakers: Annotated[int, Field(strict=True, ge=1, le=16)] | None = None
    export_rttm: StrictBool = True
    dry_run: StrictBool = True

    @model_validator(mode="after")
    def bounded_selection(self):
        """Apply the 120-second selection ceiling before any source bytes are opened."""
        _bounded(self.start_seconds, self.end_seconds)
        return self


class RelabelRequest(RecordReference):
    """Explicit recording-scoped labels written as a new record; the parent stays unchanged."""

    action: Literal["relabel"]
    output_directory: LocalPath
    assignments: Annotated[dict[ClusterLabel, SpeakerName], Field(max_length=64)] = {}
    roles: Annotated[dict[SpeakerName, Role], Field(max_length=64)] = {}
    note: Annotated[str, Field(max_length=2048)] | None = None
    match_registry: StrictBool = False
    expected_speakers: Annotated[list[SpeakerName], Field(max_length=16)] = []
    registry_path: LocalPath | None = None
    runtime_descriptor_path: LocalPath | None = None
    expected_runtime_descriptor_sha256: Digest | None = None
    export_rttm: StrictBool = True
    dry_run: StrictBool = True

    @model_validator(mode="after")
    def explicit_scope(self):
        """Labels come from the caller; registry suggestions need an explicit match request."""
        if not self.assignments and not self.match_registry:
            raise ValueError("Relabel requires explicit assignments or match_registry")
        if set(self.roles) - set(self.assignments.values()):
            raise ValueError("Relabel roles may only tag names assigned in this request")
        runtime = (self.registry_path, self.runtime_descriptor_path, self.expected_runtime_descriptor_sha256)
        if self.match_registry != all(value is not None for value in runtime) or (
                not self.match_registry and any(value is not None for value in runtime)):
            raise ValueError("match_registry requires, and alone accepts, registry and runtime descriptor fields")
        if self.expected_speakers and not self.match_registry:
            raise ValueError("expected_speakers only restricts explicit match_registry suggestions")
        return self


class SamplesRequest(RecordReference):
    """Bounded per-cluster WAV clips cut at exact sample offsets of the retained input."""

    action: Literal["samples"]
    output_directory: LocalPath
    clusters: Annotated[list[ClusterLabel], Field(max_length=64)] = []
    per_cluster: Annotated[int, Field(strict=True, ge=1, le=3)] = 1
    max_seconds: Annotated[Number, Field(ge=1, le=15)] = 8
    dry_run: StrictBool = True


class RegistryRequest(StrictModel):
    """Read-only registry listing grouped by embedding model, never returning voiceprints."""

    action: Literal["registry"]
    registry_path: LocalPath


SpeakersRequest = Annotated[
    DiarizeRequest | RelabelRequest | SamplesRequest | RegistryRequest, Field(discriminator="action"),
]


class FileWindowSource(StrictModel):
    """Exact-source window recorded as the voiceprint provenance."""

    kind: Literal["file_window"]
    file_path: LocalPath
    expected_source_sha256: Digest
    start_seconds: Annotated[Number, Field(ge=0)] = 0
    end_seconds: Annotated[Number, Field(gt=0)]

    @model_validator(mode="after")
    def bounded_window(self):
        """Require at least one second and at most the shared selection ceiling."""
        _bounded(self.start_seconds, self.end_seconds, minimum=1)
        return self


class ClusterSource(RecordReference):
    """One anonymous cluster of a SHA-bound diarization record."""

    kind: Literal["diarized_cluster"]
    cluster: ClusterLabel


class EnrollRequest(StrictModel):
    """The only voiceprint write: an explicit name, caller consent statement and model key."""

    speaker_name: SpeakerName
    consent_confirmed: StrictBool
    registry_path: LocalPath
    runtime_descriptor_path: LocalPath
    expected_runtime_descriptor_sha256: Digest
    source: Annotated[FileWindowSource | ClusterSource, Field(discriminator="kind")]
    role: Role | None = None
    replace_existing: StrictBool = False
    dry_run: StrictBool = True

    @model_validator(mode="after")
    def stated_consent(self):
        """Record only consent the caller states; it is never inferred or defaulted."""
        if self.consent_confirmed is not True:
            raise ValueError("Enrollment requires consent_confirmed=true from the caller")
        return self


class SpeakerArtifact(StrictModel):
    """One retained output file relative to its output directory."""

    path: str
    sha256: Digest
    bytes: Annotated[int, Field(strict=True, ge=0)]
    role: str


class SpeakersResult(StrictModel):
    """Planned or completed local speaker operation; identities are never verified."""

    action: Literal["diarize", "relabel", "samples", "registry", "enroll"]
    status: Literal["planned", "complete"]
    output_directory: str | None = None
    artifacts: list[SpeakerArtifact] = []
    record: dict
    speaker_identity_verified: Literal[False] = False
    voiceprints_persisted: Annotated[int, Field(strict=True, ge=0, le=1)] = 0
