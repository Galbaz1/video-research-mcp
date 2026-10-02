"""Original-byte ingestion with located derivatives and existing durable job receipts."""

from __future__ import annotations

import asyncio
import hashlib
import shutil
import time
import uuid
from pathlib import Path

from .config import get_config
from .image_manifest import canonical, json_digest, write_manifest
from .image_preprocessing import check_worker, image_worker
from .ingestion_jobs import publish, reserve
from .ingestion_read import read_ingestion
from .ingestion_sources import retain_source, verify_origin
from .job_store import JobStore
from .media_local_io import _copy_hash
from .media_snapshot import checked_path, view_directory
from .models.ingestion import SourceIngestRequest
from .redaction import redact_text

MAX_DERIVED_BYTES = 8 * 1024 * 1024


def parser_profile(source_format: str) -> dict:
    """Bind the actual firstparty parsers and optional installed PDF commands."""
    package = Path(__file__).parent
    names = ["ingestion.py", "ingestion_sources.py", "ingestion_pdf.py", "ingestion_audio.py",
             "ingestion_text.py", "ingestion_docx.py", "ingestion_read.py", "ingestion_jobs.py",
             "models/ingestion.py", "models/ingestion_location.py"]
    profile = {"format": source_format, "implementation": {
        name: hashlib.sha256((package / name).read_bytes()).hexdigest() for name in names
    }, "derived_max_bytes": MAX_DERIVED_BYTES, "indexing": "not_requested"}
    if source_format == "pdf":
        from .ingestion_pdf import pdf_profile

        profile["native"] = pdf_profile()
    return profile


def _local_parse(path, source_format, directory, cancelled, deadline):
    """Join bounded parsers before cancellation may expose their output directory."""
    check_worker(cancelled, deadline)
    if source_format == "docx":
        from .ingestion_docx import parse_docx_source

        result = parse_docx_source(path, directory)
    elif source_format == "audio":
        from .ingestion_audio import parse_audio_source

        result = parse_audio_source(path, directory)
    else:
        from .ingestion_text import parse_text_source

        result = parse_text_source(path, source_format, directory)
    check_worker(cancelled, deadline)
    return result


def _artifacts(directory, cancelled, deadline):
    """Bound every produced regular artifact; never follow an output link."""
    records, total = [], 0
    for path in sorted(directory.iterdir()):
        check_worker(cancelled, deadline)
        digest, size = _copy_hash(checked_path(str(path)), cancelled=cancelled,
                                 max_bytes=MAX_DERIVED_BYTES - total)
        total += size
        if not size or total > MAX_DERIVED_BYTES or len(records) >= 64:
            raise ValueError("Extraction artifacts exceed byte/count bounds or contain an empty file")
        records.append({"path": str(path), "sha256": digest, "bytes": size,
                        "asset_kind": "extracted", "source_role": "derived_parser_output"})
    return records


async def _extract(request, source, directory, profile, deadline) -> dict:
    """Produce located artifacts and publish only after original/parser readbacks."""
    derived = directory / "derived"
    derived.mkdir(mode=0o700)
    if request.source_format == "pdf":
        from .ingestion_pdf import parse_pdf_source

        parsed = await parse_pdf_source(Path(source["path"]), derived, profile["native"],
                                        max(0.01, deadline - time.monotonic()))
    else:
        parsed = await image_worker(_local_parse, Path(source["path"]), request.source_format,
                                    derived, deadline=deadline)
    if not parsed.segments:
        raise ValueError("Empty extraction is a terminal failure; source was not indexed")
    segments = derived / "segments.json"
    encoded = canonical(parsed.model_dump(mode="json"))
    if len(encoded) > MAX_DERIVED_BYTES:
        raise ValueError("Extraction exceeds the 8 MiB derived byte ceiling")
    with segments.open("xb") as writer:
        segments.chmod(0o600)
        writer.write(encoded)
    artifacts = await image_worker(_artifacts, derived, deadline=deadline)
    for segment in parsed.segments:
        if segment.artifact is not None and segment.artifact not in {a["path"] for a in artifacts}:
            raise ValueError("Extracted element references an uncommitted artifact")
    await verify_origin(source, deadline)
    if parser_profile(request.source_format) != profile:
        raise ValueError("Parser implementation/settings changed during extraction")
    payload = {"source": source, "artifacts": artifacts, "segments_artifact": str(segments),
               "parser": profile, "extraction_sha256": json_digest(profile),
               "source_id": source["id"], "source_revision": source["revision"]}
    manifest = await write_manifest(payload, directory)
    if parser_profile(request.source_format) != profile:
        raise ValueError("Parser implementation/settings changed before publication")
    return {"manifest": manifest, "artifact_hashes": {
        r["path"]: r["sha256"] for r in [source, *artifacts, manifest]
    }}


async def ingest_source(request: SourceIngestRequest) -> dict:
    """Deduplicate exact original/parser requests; never retry unknown extraction work."""
    profile = parser_profile(request.source_format)
    directory = view_directory()
    source, state, owner = None, {}, "ingestion:" + uuid.uuid4().hex
    timeout = get_config().media_acquire_timeout_seconds
    deadline = time.monotonic() + timeout
    try:
        async with asyncio.timeout(timeout):
            source = await retain_source(request, directory, deadline)
            binding = {"source_id": source["id"], "revision": source["revision"],
                       "source_sha256": source["sha256"], "source_bytes": source["bytes"],
                       "parser": profile}
            job_id = "ingestion-" + json_digest(binding)
            owned = await image_worker(reserve, binding, source, job_id, owner, timeout, state,
                                       deadline=deadline)
            if not owned:
                shutil.rmtree(directory)
                return {**await read_ingestion(job_id), "deduplicated": True}
            artifacts = await _extract(request, source, directory, profile, deadline)
            await image_worker(publish, job_id, owner, artifacts, deadline=deadline)
            return {**await read_ingestion(job_id), "deduplicated": False}
    except asyncio.CancelledError:
        row = state.get("row")
        if row is not None:
            JobStore().cancel(row["job_id"])
            JobStore().checkpoint(row["job_id"], owner, status="cancelled", release=True,
                                  error="Owned extraction cancellation joined")
        else:
            shutil.rmtree(directory)
        raise
    except Exception as error:
        row = state.get("row")
        if row is None:
            shutil.rmtree(directory)
            raise
        message = str(error) or f"{type(error).__name__} during source extraction"
        if isinstance(error, TimeoutError):
            message = f"Source ingestion exceeded its {timeout:g}-second deadline; owned work joined"
        result = {"status": "failed", "error": redact_text(message), "indexed": False}
        if source is not None:
            result["original"] = source
        current = JobStore().get(row["job_id"])
        cancelled = current["status"] == "cancel_requested"
        if cancelled:
            result["error"] = "Owned extraction cancellation joined"
        JobStore().checkpoint(row["job_id"], owner,
                              status="cancelled" if cancelled else "failed", release=True,
                              result=result, error=result["error"],
                              artifact_hashes={source["path"]: source["sha256"]})
        return {**await read_ingestion(row["job_id"]), "deduplicated": False}
