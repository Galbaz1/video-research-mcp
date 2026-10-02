"""YouTube-only, bounded yt-dlp downloads with verified byte receipts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import shutil
import tempfile
import stat
import weakref
from pathlib import Path

from ..config import get_config
from ..local_path_policy import enforce_local_access_root, resolve_path
from ..media_process import run_media_process

_FORMAT = "mp4[height<=720][width<=1280]/best[ext=mp4][height<=720][width<=1280]"
_LOCKS: weakref.WeakValueDictionary[str, asyncio.Lock] = weakref.WeakValueDictionary()


def _download_dir() -> Path:
    """Return the configured download cache."""
    directory = Path(get_config().cache_dir) / "downloads"
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    return directory


def _byte_receipt(path: Path, video_id: str) -> dict:
    """Verify regular nonempty bytes without following a final symlink."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    digest, count = hashlib.sha256(), 0
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError("YouTube download must be an owned regular file")
        while chunk := stream.read(65536):
            count += len(chunk)
            if count > get_config().media_max_input_bytes:
                raise ValueError("Downloaded video exceeds MEDIA_MAX_INPUT_BYTES")
            digest.update(chunk)
    if not count:
        raise ValueError("yt-dlp produced an empty video")
    return {"version": 1, "video_id": video_id, "bytes": count, "sha256": digest.hexdigest()}


def _cached_download(path: Path, video_id: str) -> bool:
    """Reuse only exact bytes bound to the original YouTube acquisition."""
    if path.is_symlink():
        raise ValueError("YouTube cache symlinks are not allowed")
    if not path.exists():
        return False
    metadata = path.stat()
    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("YouTube cache must be an owned regular file")
    if metadata.st_size == 0:
        return False
    actual = _byte_receipt(path, video_id)
    receipt = path.with_suffix(".receipt.json")
    try:
        fd = os.open(receipt, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 4096:
                raise ValueError("YouTube receipt must be a bounded regular file")
            recorded = json.loads(stream.read(4097))
    except (OSError, ValueError) as exc:
        raise ValueError("Cached YouTube provenance is unknown; remove this cached file before retrying") from exc
    if recorded != actual:
        raise ValueError("Cached YouTube bytes changed; remove this cached file before retrying")
    return True


def _cookies() -> list[str]:
    """Use only an explicitly configured, readable file within the local fence."""
    configured = get_config().media_cookies_file
    if not configured:
        return []
    try:
        path = enforce_local_access_root(resolve_path(configured))
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 1024 * 1024:
                raise OSError("cookies must be a nonempty regular file up to 1 MiB")
    except (OSError, ValueError, PermissionError) as exc:
        raise ValueError("MEDIA_COOKIES_FILE is unavailable; configure a readable cookies file within LOCAL_FILE_ACCESS_ROOT") from exc
    return ["--cookies", str(path)]


async def _download(video_id: str, target_dir: Path, cookies: list[str]) -> Path:
    """Publish one new download atomically after bounded execution and readback."""
    target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output = target_dir / f"{video_id}.mp4"
    if await asyncio.to_thread(_cached_download, output, video_id):
        return output
    binary = shutil.which("yt-dlp")
    if not binary:
        raise RuntimeError("yt-dlp not found; install yt-dlp independently to acquire YouTube media")
    staging = Path(tempfile.mkdtemp(prefix=".youtube-", dir=target_dir))
    temporary = staging / "video.mp4"
    cfg = get_config()
    command = [
        binary, "--no-playlist", "--quiet", "--no-warnings", "--ignore-config",
        "--no-cache-dir", "--no-progress", "--retries", "0", "--fragment-retries", "0",
        "--extractor-retries", "0", "--socket-timeout", "30",
        "--max-filesize", str(cfg.media_max_input_bytes), "-f", _FORMAT,
        "-o", str(temporary), *cookies, f"https://www.youtube.com/watch?v={video_id}",
    ]
    try:
        try:
            await run_media_process(command, cfg.media_acquire_timeout_seconds)
        except (RuntimeError, TimeoutError) as exc:
            raise RuntimeError(f"yt-dlp failed; check source availability or configured cookies: {exc}") from exc
        receipt = await asyncio.to_thread(_byte_receipt, temporary, video_id)
        os.chmod(temporary, 0o600)
        sidecar = staging / "receipt.json"
        sidecar.write_text(json.dumps(receipt, sort_keys=True))
        os.chmod(sidecar, 0o600)
        temporary.replace(output)
        sidecar.replace(output.with_suffix(".receipt.json"))
        return output
    finally:
        shutil.rmtree(staging)


async def download_youtube_video(video_id: str, target_dir: Path | None = None) -> Path:
    """Acquire a canonical YouTube ID; exact cached bytes survive process restart.

    Optional cookies come only from MEDIA_COOKIES_FILE. The independently installed
    downloader receives a canonical YouTube URL, never an arbitrary remote source.
    The whole operation has a configured timeout and cleans only its own staging.
    """
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", video_id):
        raise ValueError("Expected an eleven-character YouTube video ID")
    cookies = _cookies()
    target_dir = target_dir if target_dir is not None else _download_dir()
    key = str(target_dir.resolve() / f"{video_id}.mp4")
    lock = _LOCKS.setdefault(key, asyncio.Lock())
    async with asyncio.timeout(get_config().media_acquire_timeout_seconds):
        async with lock:
            return await _download(video_id, target_dir, cookies)
