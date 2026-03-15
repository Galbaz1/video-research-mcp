"""Local video file helpers — MIME detection, hashing, content building, File API upload."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from google.genai import types

from ..client import GeminiClient
from ..config import get_config
from ..local_path_policy import enforce_local_access_root, resolve_path

logger = logging.getLogger(__name__)

SUPPORTED_VIDEO_EXTENSIONS: dict[str, str] = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mpeg": "video/mpeg",
    ".wmv": "video/x-ms-wmv",
    ".3gpp": "video/3gpp",
}

LARGE_FILE_THRESHOLD = 20 * 1024 * 1024  # 20 MB
_UPLOAD_LOCKS: dict[str, asyncio.Lock] = {}
_UPLOAD_LOCKS_GUARD = asyncio.Lock()


def _video_mime_type(path: Path) -> str:
    """Return MIME type for a video file, or raise ValueError if unsupported."""
    ext = path.suffix.lower()
    mime = SUPPORTED_VIDEO_EXTENSIONS.get(ext)
    if not mime:
        allowed = ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
        raise ValueError(f"Unsupported video extension '{ext}'. Supported: {allowed}")
    return mime


def _file_content_hash(path: Path) -> str:
    """SHA-256 of file contents, truncated to 16 hex chars."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def _validate_video_path(file_path: str) -> tuple[Path, str]:
    """Validate path exists and has supported extension. Returns (path, mime)."""
    p = enforce_local_access_root(resolve_path(file_path))
    if not p.exists():
        raise FileNotFoundError(f"Video file not found: {file_path}")
    if not p.is_file():
        raise ValueError(f"Not a file: {file_path}")
    mime = _video_mime_type(p)
    return p, mime


async def _wait_for_active(
    client, file_name: str, *, timeout: float = 120, interval: float = 2.0
) -> None:
    """Poll Gemini Files API until file state is ACTIVE.

    Args:
        client: google.genai client instance.
        file_name: The file resource name (e.g. "files/abc123").
        timeout: Max seconds to wait before raising TimeoutError.
        interval: Seconds between polling attempts.

    Raises:
        RuntimeError: If the file enters FAILED state.
        TimeoutError: If the file doesn't become ACTIVE within timeout.
    """
    loop = asyncio.get_event_loop()
    start = loop.time()
    deadline = start + timeout
    while True:
        file_info = await client.aio.files.get(name=file_name)
        if file_info.state == "ACTIVE":
            elapsed = loop.time() - start
            if elapsed > interval:  # Only log if we actually waited
                logger.info("File %s active after %.1fs", file_name, elapsed)
            return
        if file_info.state == "FAILED":
            raise RuntimeError(f"File processing failed: {file_name}")
        if loop.time() > deadline:
            raise TimeoutError(
                f"File {file_name} not active after {timeout}s (state: {file_info.state})"
            )
        await asyncio.sleep(interval)


def _upload_cache_dir() -> Path:
    """Return the upload cache directory, creating it if needed."""
    cfg = get_config()
    d = Path(cfg.cache_dir) / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_upload_cache(content_hash: str) -> dict | None:
    """Load a cached upload entry by content hash, or None if missing."""
    cache_file = _upload_cache_dir() / f"{content_hash}.json"
    if not cache_file.exists():
        return None
    try:
        return json.loads(cache_file.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def _save_upload_cache(content_hash: str, file_uri: str, file_name: str) -> None:
    """Persist an upload cache entry keyed by content hash."""
    cache_file = _upload_cache_dir() / f"{content_hash}.json"
    cache_file.write_text(json.dumps({
        "file_uri": file_uri,
        "file_name": file_name,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }))


async def _upload_large_file(path: Path, mime_type: str, content_hash: str = "") -> str:
    """Upload via Gemini File API, wait for ACTIVE state, return the file URI.

    When ``content_hash`` is provided, checks an on-disk cache first. If the
    cached file is still ACTIVE on the server, the upload is skipped entirely.
    This prevents re-upload loops when MCP clients retry after a timeout.
    """
    client = GeminiClient.get()

    if not content_hash:
        uploaded = await client.aio.files.upload(
            file=path,
            config=types.UploadFileConfig(mime_type=mime_type),
        )
        logger.info("Uploaded %s → %s (state=%s)", path.name, uploaded.uri, uploaded.state)
        await _wait_for_active(client, uploaded.name)
        return uploaded.uri

    async with _UPLOAD_LOCKS_GUARD:
        lock = _UPLOAD_LOCKS.setdefault(content_hash, asyncio.Lock())

    async with lock:
        cached = _load_upload_cache(content_hash)
        if cached:
            try:
                await _wait_for_active(client, cached["file_name"], timeout=10)
                logger.info("Upload cache hit for %s → %s", path.name, cached["file_uri"])
                return cached["file_uri"]
            except (RuntimeError, TimeoutError, KeyError):
                logger.debug("Stale upload cache for %s, re-uploading", path.name)

        uploaded = await client.aio.files.upload(
            file=path,
            config=types.UploadFileConfig(mime_type=mime_type),
        )
        logger.info("Uploaded %s → %s (state=%s)", path.name, uploaded.uri, uploaded.state)
        await _wait_for_active(client, uploaded.name)
        _save_upload_cache(content_hash, uploaded.uri, uploaded.name)
        return uploaded.uri


async def _video_file_content(file_path: str, prompt: str) -> tuple[types.Content, str, str]:
    """Build Content for a local video file.

    Small files (<20 MB) use inline Part.from_bytes.
    Large files are uploaded via the File API.

    Returns:
        (content, content_id, file_uri) where content_id is the SHA-256 hash
        prefix and file_uri is the File API URI (empty for small inline files).
    """
    p, mime = _validate_video_path(file_path)
    content_id = _file_content_hash(p)
    size = p.stat().st_size

    if size >= LARGE_FILE_THRESHOLD:
        file_uri = await _upload_large_file(p, mime, content_hash=content_id)
        parts = [types.Part(file_data=types.FileData(file_uri=file_uri))]
    else:
        file_uri = ""
        data = await asyncio.to_thread(p.read_bytes)
        parts = [types.Part.from_bytes(data=data, mime_type=mime)]

    parts.append(types.Part(text=prompt))
    return types.Content(parts=parts), content_id, file_uri


async def _video_file_uri(file_path: str) -> tuple[str, str]:
    """Upload a local video and return (file_uri, content_id) for sessions.

    Sessions always upload (even small files) to get a stable URI for multi-turn replay.
    """
    p, mime = _validate_video_path(file_path)
    content_id = _file_content_hash(p)
    uri = await _upload_large_file(p, mime, content_hash=content_id)
    return uri, content_id
