"""Bounded replay clocks, source identities and explicit optional recording scope."""

from fractions import Fraction
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

ID = Annotated[str, Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
LocalPath = Annotated[str, Field(min_length=1, max_length=4096)]
Ticks = Annotated[StrictInt, Field(ge=0, le=10**15)]


class LiveModel(BaseModel):
    """Reject undeclared fields, coercion and nonfinite values at the boundary."""

    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class LiveSource(LiveModel):
    """Original bytes and a declared mapping from source ticks to the common clock."""

    source_id: ID
    revision: ID
    path: LocalPath
    sha256: Digest
    time_base: str = Field(pattern=r"^[1-9][0-9]{0,8}/[1-9][0-9]{0,8}$")
    offset_us: StrictInt = Field(ge=-86_400_000_000, le=86_400_000_000)
    clock_basis: Literal["observed", "inferred"]
    clock_description: str = Field(min_length=1, max_length=512)


class EventTime(LiveModel):
    """Keep original timestamps even when alignment is inferred."""

    event_id: ID
    source_id: ID
    timestamp_ticks: Ticks
    duration_ticks: Ticks = 0
    reference_us: StrictInt = Field(ge=0, le=86_400_000_000)
    text: str = Field(min_length=1, max_length=4000)


class SpeechEvent(EventTime):
    """Speech recognition is inference; supplied captions are source assertions."""

    kind: Literal["speech"]
    basis: Literal["inferred", "source_assertion"]


class OCREvent(EventTime):
    """OCR recognition remains inference rather than verified text truth."""

    kind: Literal["OCR"]
    basis: Literal["inferred"]


class FrameEvent(EventTime):
    """A supplied frame observation does not authenticate its acquisition."""

    kind: Literal["frame"]
    basis: Literal["observed"]


class BrowserEvent(EventTime):
    """Browser telemetry is retained data, never a navigation or script instruction."""

    kind: Literal["browser"]
    basis: Literal["observed"]
    category: Literal["navigation", "console", "network", "DOM"]


Event = Annotated[SpeechEvent | OCREvent | FrameEvent | BrowserEvent, Field(discriminator="kind")]


class QueueState(LiveModel):
    """Missing producer telemetry is unknown; replay has no background queue."""

    depth: Annotated[StrictInt | None, Field(ge=0, le=1_000_000)] = None
    dropped_frames: Annotated[StrictInt | None, Field(ge=0, le=1_000_000)] = None
    dropped_events: Annotated[StrictInt | None, Field(ge=0, le=1_000_000)] = None
    basis: Literal["source_reported", "unknown"] = "unknown"

    @model_validator(mode="after")
    def telemetry_basis(self):
        """Do not describe supplied counters as absent telemetry."""
        known = any(v is not None for v in (self.depth, self.dropped_frames, self.dropped_events))
        if known != (self.basis == "source_reported"):
            raise ValueError("Queue counters require source_reported basis; absent counters are unknown")
        return self


class ReplayRequest(LiveModel):
    """Freeze at most 100 events and eight bounded originals without processing media."""

    store_dir: LocalPath
    session_id: ID
    revision: ID
    clock_id: ID
    tolerance_us: StrictInt = Field(ge=0, le=1_000_000)
    sources: list[LiveSource] = Field(min_length=1, max_length=8)
    events: list[Event] = Field(min_length=1, max_length=100)
    queue: QueueState = Field(default_factory=QueueState)

    @model_validator(mode="after")
    def clocks_and_ids(self):
        """Reject duplicate identities, unused sources and out-of-tolerance mappings."""
        sources = {s.source_id: s for s in self.sources}
        if len(sources) != len(self.sources) or len({e.event_id for e in self.events}) != len(self.events):
            raise ValueError("Source and event IDs must be unique")
        if {e.source_id for e in self.events} != sources.keys():
            raise ValueError("Every event must bind a declared source; every source must be used")
        for event in self.events:
            source = sources[event.source_id]
            start = event.timestamp_ticks * Fraction(source.time_base) * 1_000_000 + source.offset_us
            end = start + event.duration_ticks * Fraction(source.time_base) * 1_000_000
            if start < 0 or end > 86_400_000_000:
                raise ValueError("Mapped event lies outside the bounded common clock")
            if abs(start - event.reference_us) > self.tolerance_us:
                raise ValueError("Event mapping exceeds declared alignment tolerance")
        return self


class SessionPin(LiveModel):
    """All subsequent reads bind the exact immutable archive bytes and revision."""

    session_id: ID
    revision: ID
    path: LocalPath
    sha256: Digest


class RetainedSource(LiveModel):
    """Exact retained source metadata; sizes and extra fields cannot be silently coerced."""

    path: LocalPath
    sha256: Digest
    bytes: StrictInt = Field(ge=0, le=2 * 1024 * 1024)


class ReplayArchive(LiveModel):
    """Validate the entire bounded archive on every pinned read after restart."""

    request: ReplayRequest
    retained: dict[ID, RetainedSource] = Field(min_length=1, max_length=8)


class ReadRequest(LiveModel):
    """The cursor binds page size and snapshot; repeating it returns the same page."""

    pin: SessionPin
    cursor: str | None = Field(default=None, max_length=256)
    limit: StrictInt = Field(default=20, ge=1, le=100)


class MonitorRequest(ReadRequest):
    """A finite literal event/count condition; no generated correction or code execution."""

    kind: Literal["speech", "OCR", "frame", "browser"]
    contains: str = Field(default="", max_length=256)
    min_matches: StrictInt = Field(default=1, ge=1, le=100)
    max_checks: StrictInt = Field(ge=1, le=100)
    deadline_seconds: float = Field(gt=0, le=30)


class FinalizeRequest(LiveModel):
    """An explicit ordinary corpus destination and optimistic collection revision."""

    pin: SessionPin
    index_path: LocalPath
    collection: ID
    expected_revision: StrictInt = Field(ge=0)


class RecordingAuthority(LiveModel):
    """Caller-declared operation scope; this record does not authenticate a principal."""

    operation_id: ID
    target: Literal["screen", "window"]
    window_title: str | None = Field(default=None, min_length=1, max_length=256)
    duration_seconds: float = Field(gt=0, le=30)
    retention: str = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def exact_target(self):
        """Require a title for a window and prohibit one for the full screen."""
        if (self.target == "window") != (self.window_title is not None):
            raise ValueError("Window recording scope requires exactly its window_title")
        return self


class ProbeRequest(LiveModel):
    """Inspect explicit device nodes and an optional separately installed companion."""

    companion_root: LocalPath | None = None
    device_paths: list[LocalPath] = Field(default_factory=list, max_length=8)


class CaptureRequest(LiveModel):
    """Prepare an isolated operator invocation; core tools never launch recording."""

    companion_root: LocalPath
    output_dir: LocalPath
    authority: RecordingAuthority


class LiveResult(LiveModel):
    """Local typed metadata; supplied replay observations remain unauthenticated."""

    operation: Literal["replay", "read", "monitor", "stop", "finalize", "probe", "capture"]
    status: str
    data: dict
    recording_started: Literal[False] = False
    provider_calls: Literal[0] = 0
    evidence_basis: Literal["supplied_replay_not_native_qualification"] = "supplied_replay_not_native_qualification"
