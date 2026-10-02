"""Bounded exact-byte manifests for the current image, OCR and clip callers."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path

from .config import get_config
from .image_preprocessing import MAX_ARTIFACT_BYTES, check_worker, image_worker
from .media_local_io import _copy_hash, _open_regular
from .media_snapshot import checked_path

MAX_MANIFEST_BYTES = 128 * 1024


def canonical(value: dict) -> bytes:
    """Encode the frozen finite JSON contract without whitespace ambiguity."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def json_digest(value: dict) -> str:
    """Hash the exact canonical operation or manifest payload bytes."""
    return hashlib.sha256(canonical(value)).hexdigest()


def _records(payload):
    """Validate explicit source/artifact commitments before reading any bytes."""
    source, artifacts = payload.get("source"), payload.get("artifacts")
    if not isinstance(source, dict) or not isinstance(artifacts, list) or not 1 <= len(artifacts) <= 64:
        raise ValueError("Manifest requires one source and 1..64 explicit artifacts")
    sources = payload.get("sources", [source])
    if not isinstance(sources, list) or not 1 <= len(sources) <= 2 or sources[0] != source:
        raise ValueError("Manifest requires 1..2 explicit source inputs including its primary source")
    total, paths = 0, set()
    for record in [*sources, *artifacts]:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise ValueError("Manifest file record has no valid path")
        if not isinstance(record.get("sha256"), str) or not re.fullmatch(r"[a-f0-9]{64}", record["sha256"]):
            raise ValueError("Manifest file record has no full SHA256")
        if type(record.get("bytes")) is not int or record["bytes"] <= 0:
            raise ValueError("Manifest file record has no positive byte commitment")
        checked_path(record["path"])
    for artifact in artifacts:
        path = str(checked_path(artifact["path"]))
        if path in paths:
            raise ValueError("Manifest artifacts must appear exactly once")
        paths.add(path)
        total += artifact["bytes"]
    if total > MAX_ARTIFACT_BYTES:
        raise ValueError("Manifest artifacts exceed the 8 MiB aggregate byte limit")
    if "artifact" in payload and payload["artifact"] not in artifacts:
        raise ValueError("Manifest primary artifact is not committed in artifacts")
    return sources, artifacts


def _verify(payload, cancelled, deadline):
    """Read every committed regular file under the same caller deadline."""
    sources, artifacts = _records(payload)
    for record in [*sources, *artifacts]:
        check_worker(cancelled, deadline)
        limit = (
            get_config().media_max_input_bytes
            if any(record is source for source in sources) else MAX_ARTIFACT_BYTES
        )
        path = checked_path(record["path"])
        actual = _copy_hash(path, cancelled=cancelled, max_bytes=limit)
        if actual != (record["sha256"], record["bytes"]):
            raise ValueError("Manifest source or artifact identity changed")
    check_worker(cancelled, deadline)


def _write(payload, directory, cancelled, deadline):
    """Create one private manifest without overwriting or deleting existing files."""
    encoded = canonical({"version": 1, "payload": payload, "payload_sha256": json_digest(payload)})
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest exceeds its 128 KiB byte limit")
    _verify(payload, cancelled, deadline)
    path = checked_path(str(directory)) / "manifest.json"
    created = False
    try:
        with path.open("xb") as writer:
            created = True
            os.fchmod(writer.fileno(), 0o600)
            writer.write(encoded)
            writer.flush()
            os.fsync(writer.fileno())
        check_worker(cancelled, deadline)
        digest, size = _copy_hash(path, cancelled=cancelled, max_bytes=MAX_MANIFEST_BYTES)
        return {"path": str(path), "sha256": digest, "bytes": size}
    except BaseException:
        if created:
            path.unlink(missing_ok=True)
        raise


async def write_manifest(metadata: dict, directory: Path) -> dict:
    """Write one exclusive manifest after source and all artifact readbacks verify."""
    timeout = get_config().media_acquire_timeout_seconds
    async with asyncio.timeout(timeout):
        return await image_worker(_write, metadata, directory, deadline=time.monotonic() + timeout)


def _read(path, expected_sha256, cancelled, deadline):
    """Bind bounded JSON parsing and file revalidation to the explicit digest."""
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[a-f0-9]{64}", expected_sha256):
        raise ValueError("An exact expected manifest SHA256 is required")
    path = checked_path(path)
    with _open_regular(path) as reader:
        if os.fstat(reader.fileno()).st_size > MAX_MANIFEST_BYTES:
            raise ValueError("Manifest exceeds its 128 KiB byte limit")
        data = reader.read(MAX_MANIFEST_BYTES + 1)
    if len(data) > MAX_MANIFEST_BYTES:
        raise ValueError("Manifest exceeds its 128 KiB byte limit")
    if hashlib.sha256(data).hexdigest() != expected_sha256:
        raise ValueError("Manifest SHA256 differs from the expected digest")
    envelope = json.loads(data)
    if not isinstance(envelope, dict) or set(envelope) != {"version", "payload", "payload_sha256"}:
        raise ValueError("Unsupported manifest envelope")
    payload = envelope["payload"]
    if envelope["version"] != 1 or not isinstance(payload, dict) or json_digest(payload) != envelope["payload_sha256"]:
        raise ValueError("Manifest payload commitment is invalid")
    _verify(payload, cancelled, deadline)
    return {**payload, "manifest": {"path": str(path), "sha256": expected_sha256, "bytes": len(data)},
            "verified": True}


async def read_manifest(manifest_path: str, expected_sha256: str) -> dict:
    """Revalidate the explicit digest, original source and every listed artifact."""
    timeout = get_config().media_acquire_timeout_seconds
    async with asyncio.timeout(timeout):
        return await image_worker(_read, manifest_path, expected_sha256,
                                  deadline=time.monotonic() + timeout)
