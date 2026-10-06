"""Stop and index pinned replay evidence using the existing ordinary corpus library."""

import hashlib
from fractions import Fraction
from pathlib import Path

from .corpus_index import canonical as corpus_canonical
from .corpus_index import connect, local_path, mutate, revision
from .live_replay import MAX_ARCHIVE_BYTES, MAX_SOURCE_BYTES, load, read_bytes, timeline
from .media_snapshot import checked_path
from .models.corpus import EvidenceRef, IndexRequest, Observation
from .models.live import FinalizeRequest, LiveResult, SessionPin
from .video_memory.av_store import canonical, publish


def _sidecar(pin: SessionPin, suffix: str) -> Path:
    """Keep lifecycle records adjacent to the pinned archive under the same fence."""
    return checked_path(str(Path(pin.path).with_name(Path(pin.path).name + suffix)))


def _publish_exact(path: Path, value: dict) -> None:
    """Create once, or require exact previously committed bytes."""
    raw = canonical(value)
    if not publish(path, raw) and read_bytes(path, MAX_ARCHIVE_BYTES) != raw:
        raise ValueError("Live lifecycle record conflicts with its durable intent")


def stop(pin: SessionPin) -> dict:
    """Seal a replay session without touching its events or invoking any processor."""
    load(pin)
    data = {"pin": pin.model_dump(), "events_sealed": True, "capture_process": "none_replay"}
    _publish_exact(_sidecar(pin, ".stopped.json"), data)
    return LiveResult(operation="stop", status="stopped", data=data).model_dump()


def _observations(pin: SessionPin, archive: dict) -> list[Observation]:
    """Verify retained originals and reference exact timestamps in the frozen archive."""
    sources = {s["source_id"]: s for s in archive["request"]["sources"]}
    for source_id, artifact in archive["retained"].items():
        raw = read_bytes(Path(artifact["path"]), MAX_SOURCE_BYTES)
        if len(raw) != artifact["bytes"] or hashlib.sha256(raw).hexdigest() != sources[source_id]["sha256"]:
            raise ValueError("Retained live original integrity mismatch")
        if artifact["sha256"] != sources[source_id]["sha256"]:
            raise ValueError("Retained live source commitment mismatch")
    result = []
    for event in timeline(archive):
        source = sources[event["source_id"]]
        artifact = archive["retained"][event["source_id"]]
        observation_id = "live:" + hashlib.sha256(canonical(
            [pin.session_id, pin.revision, event["event_id"]])).hexdigest()
        result.append(Observation(
            video_id=event["source_id"], observation_id=observation_id,
            source_revision=source["revision"], media_digest=source["sha256"],
            kind=event["kind"] if event["kind"] in {"speech", "OCR"} else "description",
            start_seconds=float(Fraction(event["media_seconds_exact"])),
            end_seconds=float(Fraction(event["end_seconds_exact"])), text=event["text"],
            artifact_refs=[EvidenceRef(artifact_id=event["source_id"], kind="description",
                                      path=artifact["path"], sha256=artifact["sha256"]),
                           EvidenceRef(artifact_id=pin.session_id, kind="description", path=pin.path, sha256=pin.sha256)],
        ))
    return result


def _committed(request: IndexRequest) -> bool:
    """Reconcile an interrupted effect from exact existing library payloads, never resubmit."""
    if not checked_path(request.index_path).exists():
        return False
    with connect(request.index_path) as db:
        if revision(db, request.collection) < request.expected_revision + 1:
            return False
        for obs in request.observations:
            row = db.execute("""SELECT o.payload FROM observations o JOIN sources s
                ON s.collection=o.collection AND s.video=o.video AND s.revision=o.revision AND s.digest=o.digest
                WHERE o.collection=? AND o.observation=? AND o.revision=?""",
                (request.collection, obs.observation_id, obs.source_revision)).fetchone()
            if row is None or row["payload"] != corpus_canonical(obs.model_dump(mode="json")):
                return False
    return True


def finalize(request: FinalizeRequest) -> dict:
    """Persist once; an occupied unresolved intent cannot retry a possibly external effect."""
    archive = load(request.pin)
    observations = _observations(request.pin, archive)
    index_path = local_path(str(checked_path(request.index_path)))
    index = IndexRequest(action="index", index_path=str(index_path), collection=request.collection,
                         expected_revision=request.expected_revision, observations=observations)
    stop(request.pin)
    intent = {"request": request.model_dump(), "observations_sha256": hashlib.sha256(
        canonical([o.model_dump(mode="json") for o in observations])).hexdigest()}
    intent_path, receipt_path = _sidecar(request.pin, ".finalize-intent.json"), _sidecar(request.pin, ".finalized.json")
    owner = publish(intent_path, canonical(intent))
    if not owner and read_bytes(intent_path, MAX_ARCHIVE_BYTES) != canonical(intent):
        raise ValueError("Live finalization destination/revision conflicts with durable intent")
    receipt_exists = receipt_path.exists()
    if owner and not receipt_exists:
        mutate(index)
    if not _committed(index):
        return LiveResult(operation="finalize", status="unresolved", data={
            "pin": request.pin.model_dump(), "intent_path": str(intent_path),
            "reason": "occupied_intent_requires_library_reconciliation", "reprocessed": False,
        }).model_dump()
    result = LiveResult(operation="finalize", status="finalized", data={
        "pin": request.pin.model_dump(), "library": {"index_path": str(index_path),
        "collection": request.collection, "index_revision": request.expected_revision + 1},
        "observations": len(observations), "reprocessed": False, "original_timestamps": "retained_exactly_in_archive",
        "source_hashes": {s["source_id"]: s["sha256"] for s in archive["request"]["sources"]},
    }).model_dump()
    if receipt_exists and read_bytes(receipt_path, MAX_ARCHIVE_BYTES) != canonical(result):
        raise ValueError("Finalized live receipt integrity mismatch")
    _publish_exact(receipt_path, result)
    return result
