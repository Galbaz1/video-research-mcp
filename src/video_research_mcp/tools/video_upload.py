"""Credential-scoped File API resource reservations and bounded reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from google.genai import errors, types

from ..client import GeminiClient
from ..config import get_config
from ..job_store import JobStore
from ..media_local_io import _open_regular
from ..media_snapshot import checked_path

KIND = "file_upload_resource"
_LOCKS: dict[str, asyncio.Lock] = {}
_INDEX_LIMIT = 8192


class FileUnavailable(RuntimeError):
    """The provider explicitly reports a failed or absent uploaded resource."""

    def __init__(self, message: str, provider_state: str = "FAILED"):
        super().__init__(message)
        self.provider_state = provider_state


def account_scope() -> str:
    """Commit the same effective credential used by the shared Developer API client."""
    key = get_config().gemini_api_key or os.getenv("GEMINI_API_KEY", "")
    if not key:
        raise ValueError("No Gemini API key configured")
    return hashlib.sha256(key.encode()).hexdigest()


def resource_key(digest: str, mime_type: str, scope: str) -> str:
    """Return an opaque source, MIME and account resource commitment."""
    return hashlib.sha256(json.dumps([digest, mime_type, scope]).encode()).hexdigest()


def _index_path(directory: Path, key: str) -> Path:
    directory = checked_path(str(directory))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory / f"{key}.json"


def _load_index(path: Path) -> dict | None:
    try:
        with _open_regular(path) as reader:
            data = reader.read(_INDEX_LIMIT + 1)
    except FileNotFoundError:
        return None
    if len(data) > _INDEX_LIMIT:
        raise ValueError("Upload cache index exceeds its byte limit")
    try:
        entry = json.loads(data)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("Upload cache index is corrupt; refusing a duplicate upload") from error
    if not isinstance(entry, dict) or set(entry) != {"version", "job_id", "resource_key"}:
        raise ValueError("Upload cache index has an unsupported format")
    if entry["version"] != 1 or not re.fullmatch(r"[a-f0-9]{32}", str(entry["job_id"])):
        raise ValueError("Upload cache index has an invalid resource identity")
    return entry


def _save_index(path: Path, row: dict) -> None:
    if path.exists() or path.is_symlink():
        with _open_regular(path):
            pass
    temporary = path.with_name(uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            writer.write(json.dumps({"version": 1, "job_id": row["job_id"],
                                     "resource_key": row["exclusive_key"]}).encode())
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _verified(row: dict, key: str, request: dict) -> None:
    if row["exclusive_key"] != key or row["request"] != request:
        raise ValueError("Upload cache resource binding differs from this request")
    attestation = row["attestation"]
    if attestation["request_integrity"] != "verified" or (
        row["result"] is not None and attestation["result_integrity"] != "verified"
    ):
        raise ValueError("Upload resource integrity is unverified")


def _resource(store: JobStore, path: Path, key: str, request: dict) -> dict:
    index = _load_index(path)
    row = None
    if index:
        if index["resource_key"] != key:
            raise ValueError("Upload cache index resource binding differs")
        row = store.get(index["job_id"])
        if row is None:
            raise ValueError("Upload resource record is missing; refusing a duplicate upload")
        _verified(row, key, request)
    if row is None or row["status"] in {"failed", "cancelled"}:
        row = next((r for r in store.list_active(KIND) if r["exclusive_key"] == key), None)
        if row is None:
            try:
                row = store.create(KIND, request, request["source_sha256"], exclusive_key=key)
            except ValueError:
                row = next((r for r in store.list_active(KIND) if r["exclusive_key"] == key), None)
                if row is None:
                    raise
        _verified(row, key, request)
        _save_index(path, row)
    return row


def _checkpoint(store: JobStore, row: dict, owner: str, **changes) -> None:
    if not store.checkpoint(row["job_id"], owner, **changes):
        raise RuntimeError("Upload resource lease lost; outcome requires reconciliation")


def _http_options(seconds: float) -> types.HttpOptions:
    return types.HttpOptions(timeout=max(1, int(seconds * 1000)),
                             retry_options=types.HttpRetryOptions(attempts=1))


async def wait_for_active(client, file_name: str, *, timeout: float = 120,
                          interval: float = 2, on_poll=None,
                          expected_uri: str | None = None) -> None:
    """Poll under one deadline, verifying the retained identity when supplied."""
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"File not active after {timeout}s")
        if on_poll:
            on_poll()
        try:
            info = await asyncio.wait_for(client.aio.files.get(
                name=file_name, config=types.GetFileConfig(http_options=_http_options(remaining))
            ), remaining)
        except errors.ClientError as error:
            if error.code == 404:
                raise FileUnavailable("Uploaded file is absent (HTTP 404)", "NOT_FOUND") from error
            raise
        if expected_uri is not None:
            uri, name, _ = _identity(info)
            if (uri, name) != (expected_uri, file_name):
                raise ValueError("File API resource identity differs from the retained upload")
        expires = getattr(info, "expiration_time", None)
        if isinstance(expires, datetime) and expires.tzinfo is not None:
            if expires <= datetime.now(timezone.utc):
                raise FileUnavailable("Uploaded file has expired", "EXPIRED")
        if info.state == "ACTIVE":
            return
        if info.state == "FAILED":
            raise FileUnavailable("File processing failed")
        if info.state != "PROCESSING":
            raise RuntimeError("File processing state is unknown; retaining upload identity")
        await asyncio.sleep(min(interval, max(0, deadline - time.monotonic())))


def _identity(uploaded) -> tuple[str, str, str]:
    uri, name = uploaded.uri, uploaded.name
    if not isinstance(uri, str) or len(uri) > 4096 or not isinstance(name, str):
        raise ValueError("File API returned no valid resource identity")
    parsed = urlsplit(uri)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or parsed.query or parsed.fragment
            or not re.fullmatch(r"files/[A-Za-z0-9_-]{1,256}", name)
            or not parsed.path.endswith("/" + name)):
        raise ValueError("File API returned an unsupported resource identity")
    state = uploaded.state
    if state not in {"ACTIVE", "PROCESSING", "FAILED"}:
        state = "UNKNOWN"
    return uri, name, getattr(state, "value", state)


async def _prepare(store, row, owner, source, mime_type, client, deadline, waiter):
    result = dict(row["result"] or {"upload_attempts": 0, "poll_attempts": 0,
                                   "wire_attempts": None, "provider_state": "UNKNOWN"})
    if row["external_id"] is None:
        if row["attempts"] != 1 or row["status"] == "unknown":
            raise RuntimeError("Previous upload outcome is unknown; refusing duplicate submission")
        result["upload_attempts"] = 1
        _checkpoint(store, row, owner, status="unknown", result=result)
        remaining = deadline - time.monotonic()
        with _open_regular(source) as reader:
            os.set_blocking(reader.fileno(), True)
            uploaded = await asyncio.wait_for(client.aio.files.upload(
                file=reader, config=types.UploadFileConfig(
                    mime_type=mime_type, http_options=_http_options(remaining))
            ), remaining)
        uri, name, state = _identity(uploaded)
        result.update(file_uri=uri, file_name=name, provider_state=state)
        external_id = row["request"]["account_scope"] + ":" + name
        _checkpoint(store, row, owner, status="running", external_id=external_id, result=result)
        if state == "FAILED":
            raise FileUnavailable("File processing failed")
    def counted_poll():
        result["poll_attempts"] += 1
        _checkpoint(store, row, owner, result=result)
    await waiter(client, result["file_name"], timeout=deadline - time.monotonic(),
                 on_poll=counted_poll, expected_uri=result["file_uri"])
    if account_scope() != row["request"]["account_scope"]:
        raise ValueError("Credential scope changed during upload preparation")
    result["provider_state"] = "ACTIVE"
    _checkpoint(store, row, owner, status="running", result=result, release=True)
    return result["file_uri"]


async def upload_snapshot(source: Path, mime_type: str, digest: str, size: int,
                          directory: Path, *, timeout: float, waiter=wait_for_active) -> str:
    """Prepare exact owned bytes, retaining known identities and unknown reservations."""
    scope = account_scope()
    key = resource_key(digest, mime_type, scope)
    request = {"source_sha256": digest, "source_bytes": size,
               "mime_type": mime_type, "account_scope": scope}
    deadline = time.monotonic() + timeout
    client = GeminiClient.get()
    async with _LOCKS.setdefault(key, asyncio.Lock()):
        if account_scope() != scope:
            raise ValueError("Credential scope changed before upload preparation")
        store, path = JobStore(), _index_path(directory, key)
        for attempt in range(2):
            row = _resource(store, path, key, request)
            owner = uuid.uuid4().hex
            existing = row["external_id"] is not None
            row = store.claim(row["job_id"], owner, lease_seconds=timeout + 30)
            if row is None:
                raise RuntimeError("Upload resource is being prepared by another worker")
            try:
                return await _prepare(store, row, owner, source, mime_type,
                                      client, deadline, waiter)
            except FileUnavailable as error:
                result = dict(store.get(row["job_id"])["result"] or {})
                result["provider_state"] = error.provider_state
                _checkpoint(store, row, owner, status="failed", release=True,
                            result=result, error={"outcome": "provider_resource_unavailable"})
                if not existing or attempt:
                    raise
            except BaseException as error:
                _checkpoint(store, row, owner, status="unknown", release=True,
                            error={"outcome": "unknown", "error_type": type(error).__name__})
                raise
    raise RuntimeError("Upload resource reconciliation failed")


def upload_receipt(digest: str, mime_type: str, directory: Path) -> dict | None:
    """Read attested preparation telemetry without creating work or polling the provider."""
    scope = account_scope()
    key = resource_key(digest, mime_type, scope)
    index = _load_index(_index_path(directory, key))
    if index is None:
        return None
    row = JobStore().get(index["job_id"])
    if row is None:
        raise ValueError("Upload resource record is missing")
    _verified(row, key, {"source_sha256": digest, "source_bytes": row["request"]["source_bytes"],
                         "mime_type": mime_type, "account_scope": scope})
    return {"job_id": row["job_id"], "status": row["status"], "owner": row["owner"],
            "attestation": row["attestation"], **(row["result"] or {})}
