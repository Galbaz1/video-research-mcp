"""Fenced exact-byte local video Parts and retained File API upload preparation."""

from __future__ import annotations

import asyncio
import stat
import threading
from pathlib import Path

from google.genai import types

from ..config import get_config
from ..media_acquisition import _wait_worker
from ..media_local_io import _copy_hash, _open_regular
from ..media_snapshot import checked_path, snapshot
from .video_upload import upload_receipt, upload_snapshot
from .video_upload import wait_for_active as _wait_for_active

SUPPORTED_VIDEO_EXTENSIONS: dict[str, str] = {
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".avi": "video/x-msvideo", ".mkv": "video/x-matroska", ".mpeg": "video/mpeg",
    ".wmv": "video/x-ms-wmv", ".3gpp": "video/3gpp",
}
LARGE_FILE_THRESHOLD = 20 * 1024 * 1024


def _video_mime_type(path: Path) -> str:
    """Return the supported local video MIME type."""
    mime = SUPPORTED_VIDEO_EXTENSIONS.get(path.suffix.lower())
    if not mime:
        allowed = ", ".join(sorted(SUPPORTED_VIDEO_EXTENSIONS))
        raise ValueError(f"Unsupported video extension '{path.suffix}'. Supported: {allowed}")
    return mime


def _file_content_hash(path: Path) -> str:
    """Commit all regular source bytes under the configured fence and input ceiling."""
    return _copy_hash(checked_path(str(path)))[0]


def _validate_video_path(file_path: str) -> tuple[Path, str]:
    """Validate a regular, bounded local video before copying or provider preparation."""
    path = checked_path(file_path)
    try:
        info = path.lstat()
    except FileNotFoundError as error:
        raise FileNotFoundError(f"Video file not found: {file_path}") from error
    if not stat.S_ISREG(info.st_mode):
        raise ValueError(f"Not a file: {file_path}")
    if info.st_size > get_config().media_max_input_bytes:
        raise ValueError("Video exceeds MEDIA_MAX_INPUT_BYTES; use a bounded window")
    return path, _video_mime_type(path)


def _upload_cache_dir() -> Path:
    """Locate the private, fenced upload index directory."""
    directory = checked_path(str(Path(get_config().cache_dir) / "uploads"))
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    return directory


def _load_upload_cache(content_hash: str, mime_type: str = "video/mp4") -> dict | None:
    """Read account-scoped, attested preparation facts without any provider request."""
    return upload_receipt(content_hash, mime_type, _upload_cache_dir())


async def _upload_large_file(path: Path, mime_type: str, content_hash: str = "") -> str:
    """Snapshot generic local media and reuse only the same source/account resource."""
    async with snapshot(str(path), content_hash or None) as owned:
        uri = await upload_snapshot(owned.path, mime_type, owned.sha256, owned.size,
                                    _upload_cache_dir(), timeout=owned.remaining(),
                                    waiter=_wait_for_active)
    return uri


def _inline_bytes(path: Path, size: int) -> bytes:
    with _open_regular(path) as reader:
        data = reader.read(size + 1)
    if len(data) != size:
        raise ValueError("Owned source size changed before inline preparation")
    return data


async def _video_file_content(
    file_path: str, prompt: str, *, video_metadata: types.VideoMetadata | None = None,
) -> tuple[types.Content, str, str]:
    """Build inline/uploaded Content bound to the complete original source SHA.

    Typed metadata applies static clipping/sampling to either media Part. The
    original source commitment remains independent of requested clip settings.
    """
    path, mime = _validate_video_path(file_path)
    async with snapshot(str(path)) as owned:
        if owned.size >= LARGE_FILE_THRESHOLD:
            uri = await upload_snapshot(owned.path, mime, owned.sha256, owned.size,
                                        _upload_cache_dir(), timeout=owned.remaining(),
                                        waiter=_wait_for_active)
            media = types.Part(file_data=types.FileData(file_uri=uri, mime_type=mime))
        else:
            uri = ""
            task = asyncio.create_task(asyncio.to_thread(_inline_bytes, owned.path, owned.size))
            data = await _wait_worker(task, threading.Event())
            media = types.Part.from_bytes(data=data, mime_type=mime)
        if video_metadata is not None:
            media.video_metadata = video_metadata
            media.media_processing = types.MediaProcessing.STATIC
        content, digest = types.Content(parts=[media, types.Part(text=prompt)]), owned.sha256
    return content, digest, uri


async def _video_file_uri(file_path: str) -> tuple[str, str]:
    """Prepare a retained upload even for small local session videos."""
    path, mime = _validate_video_path(file_path)
    async with snapshot(str(path)) as owned:
        uri = await upload_snapshot(owned.path, mime, owned.sha256, owned.size,
                                    _upload_cache_dir(), timeout=owned.remaining(),
                                    waiter=_wait_for_active)
        digest = owned.sha256
    return uri, digest
