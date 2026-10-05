"""Independent immutable replay of the licensed watch-skill clock/cursor protocol."""

import hashlib
from fractions import Fraction
from pathlib import Path

from .media_local_io import _open_regular
from .media_snapshot import checked_path
from .models.live import LiveResult, ReadRequest, ReplayArchive, ReplayRequest, SessionPin
from .video_memory.av_store import canonical, publish

MAX_ARCHIVE_BYTES = 2 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_SOURCE_BYTES = 8 * 1024 * 1024


def read_bytes(path: Path, ceiling: int) -> bytes:
    """Reuse the regular-file fence and reject changes during bounded reads."""
    import os

    with _open_regular(checked_path(str(path))) as stream:
        before = os.fstat(stream.fileno())
        if before.st_size > ceiling:
            raise ValueError("Live artifact exceeds byte ceiling")
        raw = stream.read(ceiling + 1)
        after = os.fstat(stream.fileno())
    current = path.lstat()
    def identity(s):
        return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns
    if len(raw) > ceiling or identity(before) != identity(after) or identity(after) != identity(current):
        raise ValueError("Live artifact changed during read or exceeds byte ceiling")
    return raw


def load(pin: SessionPin) -> dict:
    """Verify bytes, identities and clocks before trusting an archive or cursor."""
    raw = read_bytes(Path(pin.path), MAX_ARCHIVE_BYTES)
    if hashlib.sha256(raw).hexdigest() != pin.sha256:
        raise ValueError("Immutable live archive SHA256 mismatch")
    value = ReplayArchive.model_validate_json(raw).model_dump(mode="json")
    request = ReplayRequest.model_validate(value["request"])
    if (request.session_id, request.revision) != (pin.session_id, pin.revision):
        raise ValueError("Live archive session/revision mismatch")
    if set(value["retained"]) != {s.source_id for s in request.sources}:
        raise ValueError("Retained originals differ from declared sources")
    expected_path = checked_path(str(Path(request.store_dir) / f"{request.session_id}.{request.revision}.json"))
    if expected_path != checked_path(pin.path):
        raise ValueError("Archive path differs from its declared session location")
    for source in request.sources:
        artifact = value["retained"][source.source_id]
        expected = str(checked_path(str(Path(request.store_dir) / f"source-{source.sha256}.bin")))
        if artifact.get("path") != expected or artifact.get("sha256") != source.sha256:
            raise ValueError("Retained source location/identity mismatch")
    return value


def replay(request: ReplayRequest) -> dict:
    """Retain exact bounded originals and publish one immutable session revision."""
    root = checked_path(request.store_dir)
    path = checked_path(str(root / f"{request.session_id}.{request.revision}.json"))
    if path.exists():
        existing = read_bytes(path, MAX_ARCHIVE_BYTES)
        import json

        if json.loads(existing).get("request") != request.model_dump(mode="json"):
            raise ValueError("Immutable live session conflict")
    originals, retained, total = {}, {}, 0
    for source in request.sources:
        raw = read_bytes(Path(source.path), MAX_SOURCE_BYTES)
        if hashlib.sha256(raw).hexdigest() != source.sha256:
            raise ValueError("Original live source SHA256 mismatch")
        total += len(raw)
        if total > MAX_TOTAL_SOURCE_BYTES:
            raise ValueError("Live originals exceed aggregate byte ceiling")
        target = checked_path(str(root / f"source-{source.sha256}.bin"))
        originals[target] = raw
        retained[source.source_id] = {"path": str(target), "sha256": source.sha256, "bytes": len(raw)}
    payload = canonical({"request": request.model_dump(mode="json"), "retained": retained})
    if len(payload) > MAX_ARCHIVE_BYTES:
        raise ValueError("Live archive exceeds byte ceiling")
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    for target, raw in [*originals.items(), (path, payload)]:
        checked_path(str(target))
        if not publish(target, raw) and read_bytes(target, max(MAX_SOURCE_BYTES, MAX_ARCHIVE_BYTES)) != raw:
            raise ValueError("Immutable live session/source conflict")
    pin = SessionPin(session_id=request.session_id, revision=request.revision,
                     path=str(path), sha256=hashlib.sha256(payload).hexdigest())
    return LiveResult(operation="replay", status="ready", data={
        "pin": pin.model_dump(), "events_total": len(request.events), "source_bytes": total,
        "clock_id": request.clock_id, "tolerance_us": request.tolerance_us,
        "queue": request.queue.model_dump(),
    }).model_dump()


def timeline(archive: dict) -> list[dict]:
    """Map rational source clocks without rounding or rewriting original timestamps."""
    sources = {s["source_id"]: s for s in archive["request"]["sources"]}
    result = []
    for event in archive["request"]["events"]:
        source = sources[event["source_id"]]
        start = event["timestamp_ticks"] * Fraction(source["time_base"]) + Fraction(source["offset_us"], 1_000_000)
        end = start + event["duration_ticks"] * Fraction(source["time_base"])
        result.append({**event, "source_revision": source["revision"], "source_sha256": source["sha256"],
                       "time_base": source["time_base"], "clock_basis": source["clock_basis"],
                       "media_seconds_exact": str(start), "end_seconds_exact": str(end),
                       "alignment_error_us_exact": str(start * 1_000_000 - event["reference_us"])})
    return sorted(result, key=lambda e: (Fraction(e["media_seconds_exact"]), e["event_id"]))


def page(request: ReadRequest, archive: dict) -> dict:
    """Return an immutable page; no filtering can silently advance past evidence."""
    events = timeline(archive)
    prefix = f"{request.pin.sha256}:{request.limit}:"
    offset = 0
    if request.cursor is not None:
        if not request.cursor.startswith(prefix):
            raise ValueError("Cursor differs from archive revision or page size")
        suffix = request.cursor[len(prefix):]
        if not suffix.isascii() or not suffix.isdecimal() or str(int(suffix)) != suffix:
            raise ValueError("Malformed live cursor")
        offset = int(suffix)
        if offset > len(events) or (offset % request.limit and offset != len(events)):
            raise ValueError("Cursor offset is not a page boundary")
    selected = events[offset:offset + request.limit]
    next_offset = offset + len(selected)
    return {"pin": request.pin.model_dump(), "cursor": prefix + str(offset),
            "next_cursor": prefix + str(next_offset), "events": selected,
            "has_more": next_offset < len(events), "events_total": len(events),
            "remaining_events": len(events) - next_offset, "queue": archive["request"]["queue"],
            "correlation_basis": "declared_common_clock_cooccurrence_not_causation"}


def read(request: ReadRequest) -> dict:
    """Read a pinned archive after restart without capture or inference."""
    return LiveResult(operation="read", status="read", data=page(request, load(request.pin))).model_dump()
