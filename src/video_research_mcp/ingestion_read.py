"""Restart-safe ingestion readback and source-bound located evidence."""

from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path

from .config import get_config
from .image_manifest import canonical, json_digest, read_manifest
from .image_preprocessing import check_worker, image_worker
from .job_store import JobStore
from .media_local_io import _open_regular
from .models.evidence import EvidenceSource, SourcePassage, SourceSnapshot
from .models.ingestion import ParsedSource

MAX_DERIVED_BYTES = 8 * 1024 * 1024


def _get_job(job_id, cancelled, deadline):
    """Join original/artifact readback under the caller's cooperative deadline."""
    return JobStore(readback_check=lambda: check_worker(cancelled, deadline)).get(job_id)


def evidence_source(source: dict, parsed: ParsedSource, extraction_sha256: str) -> EvidenceSource:
    """Bind quotes to located observations while keeping original bytes separate."""
    passages = [SourcePassage(
        id=segment.id, quote=segment.text, location=segment.location.model_dump(mode="json"),
        method=segment.method,
    ) for segment in parsed.segments if segment.text.strip()]
    intervals = [
        {"start_ms": s.location.start_ms, "end_ms": s.location.end_ms}
        for s in parsed.segments if s.kind == "audio"
    ]
    record = {"asset_sha256": source["sha256"], "revision": source["revision"],
              "observed_intervals": intervals,
              "passages": [{key: p.model_dump()[key] for key in ("id", "quote", "start_ms", "end_ms")}
                           for p in passages],
              "locations": {p.id: p.model_extra["location"] for p in passages},
              "methods": {p.id: p.model_extra["method"] for p in passages},
              "extraction_sha256": extraction_sha256}
    text = canonical(record).decode("utf-8")
    return EvidenceSource(
        id=source["id"], revision=source["revision"], sha256=source["sha256"],
        path=Path(source["path"]).name, modality="audio" if intervals else "document",
        asset_kind="original", snapshot=SourceSnapshot(text=text, sha256=hashlib.sha256(text.encode()).hexdigest()),
        passages=passages, observed_intervals=intervals,
        duration_ms=max((s["end_ms"] for s in intervals), default=None),
        extraction_sha256=extraction_sha256,
    )


def _read_segments(retained, cancelled, deadline):
    """Parse only the exact extraction bytes listed in the frozen manifest."""
    check_worker(cancelled, deadline)
    path = retained["segments_artifact"]
    record = next((a for a in retained["artifacts"] if a["path"] == path), None)
    if record is None:
        raise ValueError("Retained extraction is not a committed artifact")
    with _open_regular(Path(path)) as reader:
        data = reader.read(MAX_DERIVED_BYTES + 1)
    if len(data) != record["bytes"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ValueError("Retained extraction differs from its byte commitment")
    parsed = ParsedSource.model_validate_json(data)
    if not parsed.segments:
        raise ValueError("Retained extraction is empty")
    artifacts = {a["path"] for a in retained["artifacts"]}
    if any(s.artifact is not None and s.artifact not in artifacts for s in parsed.segments):
        raise ValueError("Retained element references an uncommitted artifact")
    check_worker(cancelled, deadline)
    return parsed


async def read_ingestion(job_id: str) -> dict:
    """Read retained located elements after rechecking job, manifest and all bytes."""
    timeout = get_config().media_acquire_timeout_seconds
    async with asyncio.timeout(timeout):
        return await _read_ingestion(job_id, time.monotonic() + timeout)


async def _read_ingestion(job_id, deadline):
    """Admit durable state and exact located derivatives within one overall deadline."""
    row = await image_worker(_get_job, job_id, deadline=deadline)
    if row is None or row["kind"] != "source_ingestion":
        raise ValueError("Unknown source ingestion job")
    attestation = row["attestation"]
    if (attestation["request_integrity"] != "verified"
            or attestation["result_integrity"] not in {"verified", "absent"}
            or attestation["artifact_integrity"] not in {"verified", "absent"}):
        return {"job_id": job_id, "status": "unknown", "recorded_status": row["status"],
                "error": "Ingestion binding or artifact readback failed", "indexed": False}
    if row["status"] != "completed":
        status = row["status"]
        if status in {"running", "cancel_requested"} and row["lease_until"] <= time.time():
            status = "unknown"
        return {**(row["result"] or {}), "job_id": job_id, "status": status,
                "recorded_status": row["status"], "indexed": False}
    manifest = row["result"]["manifest"]
    retained = await read_manifest(manifest["path"], manifest["sha256"])
    original, binding = retained["source"], row["request"]
    actual = {"source_id": original["id"], "revision": original["revision"],
              "source_sha256": original["sha256"], "source_bytes": original["bytes"],
              "parser": retained["parser"]}
    if actual != binding or retained["extraction_sha256"] != json_digest(retained["parser"]):
        raise ValueError("Retained source/parser differs from the frozen job binding")
    parsed = await image_worker(_read_segments, retained, deadline=deadline)
    source = evidence_source(retained["source"], parsed, retained["extraction_sha256"])
    return {"status": "completed", "job_id": job_id, "source": source.model_dump(mode="json"),
            "source_root": str(Path(retained["source"]["path"]).parent),
            "original": retained["source"], "extraction": parsed.model_dump(mode="json"),
            "parser": retained["parser"], "manifest": manifest, "artifact_verified": True,
            "indexed": False, "semantic_support": "not_verified"}
