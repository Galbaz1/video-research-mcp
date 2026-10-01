"""Retained original document bytes through existing local and checked URL fences."""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from .media_snapshot import checked_path
from .models.ingestion import SourceIngestRequest
from .redaction import redact_text
from .research_sources import _copy_file, _worker
from .url_policy import checked_response

MAX_SOURCE_BYTES = 50 * 1024 * 1024
SUFFIXES = {"pdf": ".pdf", "docx": ".docx", "markdown": ".md", "html": ".html",
            "text": ".txt", "audio": ".wav"}
CONTENT_TYPES = {
    "pdf": {"application/pdf"},
    "docx": {"application/zip", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "markdown": {"text/markdown", "text/plain"},
    "html": {"text/html", "application/xhtml+xml"},
    "text": {"text/plain"},
    "audio": {"audio/wav", "audio/x-wav", "audio/wave"},
}


async def _download(request: SourceIngestRequest, target: Path) -> dict:
    """Commit decoded HTTP response-body bytes without flattening source content."""
    digest, consumed = hashlib.sha256(), 0
    host = urlsplit(request.url).hostname
    async with checked_response(request.url, allowed_hosts={host}) as response:
        mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if mime not in CONTENT_TYPES[request.source_format] | {"application/octet-stream"}:
            raise ValueError("URL content type differs from the selected source format")
        length = response.headers.get("content-length")
        if length is not None and (not length.isdecimal() or int(length) > MAX_SOURCE_BYTES):
            raise ValueError("URL source exceeds the 50 MiB acquisition ceiling")
        with target.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            async for chunk in response.aiter_bytes(65536):
                consumed += len(chunk)
                if consumed > MAX_SOURCE_BYTES:
                    raise ValueError("URL source exceeds the 50 MiB acquisition ceiling")
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        return {"path": str(target), "sha256": digest.hexdigest(), "bytes": consumed,
                "origin_url": redact_text(request.url), "final_url": redact_text(str(response.url)),
                "content_type": mime, "representation": "decoded_http_response_body"}


async def retain_source(request: SourceIngestRequest, directory: Path, deadline: float) -> dict:
    """Retain a separate original and preserve exact caller ID/revision commitments."""
    target = directory / ("original" + SUFFIXES[request.source_format])
    if request.url is not None:
        source = await _download(request, target)
    else:
        original = checked_path(request.file_path)
        record = {"received_bytes": 0}
        digest = await _worker(_copy_file, original, target, record, ceiling=MAX_SOURCE_BYTES,
                               deadline=deadline)
        source = {"path": str(target), "sha256": digest, "bytes": record["received_bytes"],
                  "origin_path": str(original), "representation": "exact_local_file_bytes"}
    if request.expected_source_sha256 is not None and source["sha256"] != request.expected_source_sha256:
        raise ValueError("Original source SHA256 differs from the requested commitment")
    return {**source, "id": request.source_id, "revision": request.revision,
            "asset_kind": "original", "format": request.source_format}


async def verify_origin(source: dict, deadline: float) -> None:
    """Recheck a local input after parsing without reacquiring remote representations."""
    if "origin_path" not in source:
        return
    from .image_preprocessing import image_worker

    digest, size = await image_worker(
        _hash_origin, checked_path(source["origin_path"]), deadline=deadline,
    )
    if (digest, size) != (source["sha256"], source["bytes"]):
        raise ValueError("Original input changed during extraction")


def _hash_origin(path, cancelled, deadline):
    """Hash one fenced origin through the existing cooperative regular-file reader."""
    if time.monotonic() >= deadline:
        raise TimeoutError("Source verification exceeded its deadline")
    from .media_local_io import _copy_hash

    return _copy_hash(path, cancelled=cancelled, max_bytes=MAX_SOURCE_BYTES)
