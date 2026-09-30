"""Bounded source metadata and acquisition using checked transport and owned storage."""

from __future__ import annotations

import asyncio
import hashlib
import json
import shutil
import stat
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlsplit

from .config import get_config
from .local_path_policy import enforce_local_access_root, resolve_path
from .media_assets import AssetCatalog
from .media_local_io import _copy_hash, _open_regular
from .media_identity import valid_digest
from .media_fetch import fetch_resource, head_resource
from .media_process import run_media_process
from .media_sources import VIDEO_TYPES, inspect_source, resolve_loom_metadata
from .redaction import redact_text

_METADATA_TYPES = ("text/html", "application/json", "application/ld+json")
_MEDIA_TYPES = tuple(VIDEO_TYPES.values()) + ("application/octet-stream",)


def _supported(source: str) -> dict:
    info = inspect_source(source)
    if info["source_kind"] == "unsupported":
        raise ValueError(info["hint"])
    return info


def _local_path(source: str) -> Path:
    """Enforce the configured boundary before any file read or subprocess."""
    if Path(source).expanduser().is_symlink():
        raise PermissionError("Local media inputs must be regular files, not symlinks")
    path = enforce_local_access_root(resolve_path(source))
    if path.suffix.lower() not in VIDEO_TYPES:
        raise ValueError("Unsupported local video extension")
    return path


def _owned_path(path: Path, directory: Path) -> Path:
    """Reject substituted or out-of-staging helper results before reading/moving."""
    if not stat.S_ISREG(path.lstat().st_mode) or not path.resolve().is_relative_to(
        directory.resolve()
    ):
        raise PermissionError("Acquisition helper returned a path outside owned regular staging")
    return path


def _youtube_receipt(path: Path, video_id: str) -> dict:
    """Bind catalog copying to the shared downloader's bounded exact-byte receipt."""
    try:
        with _open_regular(path.with_suffix(".receipt.json")) as reader:
            data = reader.read(4097)
        receipt = json.loads(data) if len(data) <= 4096 else None
    except (OSError, ValueError) as exc:
        raise ValueError(
            "YouTube acquisition receipt is missing or invalid; provenance cannot be verified"
        ) from exc
    if (
        not isinstance(receipt, dict)
        or receipt.get("version") != 1
        or receipt.get("video_id") != video_id
        or not valid_digest(receipt.get("sha256"))
        or type(receipt.get("bytes")) is not int
        or receipt["bytes"] <= 0
    ):
        raise ValueError("YouTube acquisition receipt is invalid")
    return receipt


async def _probe_local(path: Path) -> dict:
    """Use bounded ffprobe on stable local bytes without network protocols."""
    executable = shutil.which("ffprobe")
    if not executable:
        raise RuntimeError(
            "ffprobe not found; install it separately to inspect local media metadata"
        )
    with tempfile.TemporaryDirectory(prefix="media-probe-") as directory:
        snapshot = Path(directory) / ("media" + path.suffix.lower())
        canceled = threading.Event()
        task = asyncio.create_task(
            asyncio.to_thread(_copy_hash, path, snapshot, cancelled=canceled)
        )
        digest, size = await _wait_worker(task, canceled)
        stdout, _ = await run_media_process(
            [
                executable,
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-threads",
                "1",
                "-format_whitelist",
                "mov,matroska,webm,avi,mpeg,mpegvideo,mpegts,asf",
                "-show_entries",
                "format=duration,format_name:stream=codec_type,codec_name,width,height",
                "-of",
                "json",
                "-i",
                str(snapshot),
            ],
            get_config().media_acquire_timeout_seconds,
        )
        task = asyncio.create_task(asyncio.to_thread(_copy_hash, snapshot, cancelled=canceled))
        if await _wait_worker(task, canceled) != (digest, size):
            raise ValueError("Owned media snapshot changed during metadata inspection")
    value = json.loads(stdout)
    if not isinstance(value, dict) or not isinstance(value.get("streams"), list):
        raise ValueError("ffprobe returned unsupported metadata")
    return {
        "probe": value,
        "sha256": digest,
        "bytes": size,
        "source_revision": "sha256:" + digest,
        "metadata_method": "bounded_local_ffprobe",
    }


async def _loom(source: str, directory: Path) -> dict:
    """Read only bounded page metadata and resolve an explicit media locator."""
    result = await fetch_resource(
        source, directory, max_bytes=1024 * 1024, allowed_content_types=_METADATA_TYPES
    )
    path = _owned_path(result["path"], directory)
    with _open_regular(path) as reader:
        body = reader.read(1024 * 1024 + 1)
    if len(body) != result["bytes"] or hashlib.sha256(body).hexdigest() != result["sha256"]:
        raise ValueError("Loom metadata bytes differ from the checked transport receipt")
    value = resolve_loom_metadata(body, result["final_url"], result["content_type"])
    return {**value, "page_sha256": result["sha256"], "metadata_bytes": result["bytes"]}


async def source_metadata(source: str) -> dict:
    """Fetch explicit metadata without video download, provider inference or upload.

    Args:
        source: Supported local video or HTTPS source.

    Returns:
        Syntax inspection plus observed metadata and zero video-download count.
    """
    info = _supported(source)
    async with asyncio.timeout(get_config().media_acquire_timeout_seconds):
        if info["source_kind"] == "local":
            metadata = await _probe_local(_local_path(source))
        elif info["source_kind"] == "youtube":
            from .youtube import YouTubeClient

            metadata = (await YouTubeClient.video_metadata(info["source_id"])).model_dump(
                mode="json"
            )
        elif info["source_kind"] == "loom":
            with tempfile.TemporaryDirectory(prefix="media-metadata-") as directory:
                metadata = await _loom(source, Path(directory))
                metadata["resolved_url"] = redact_text(metadata["resolved_url"])
        else:
            metadata = await head_resource(source)
            metadata["final_url"] = redact_text(metadata["final_url"])
            metadata["metadata_method"] = "checked_head_headers_only"
    return {
        **info,
        "metadata": metadata,
        "media_download_bytes": 0,
        "inference_performed": False,
        "upload_performed": False,
    }


def _video_suffix(url: str, content_type: str) -> str:
    """Keep a supported extension for downstream local video analysis."""
    suffix = Path(urlsplit(url).path).suffix.lower()
    if suffix in VIDEO_TYPES:
        return suffix
    media_type = content_type.split(";", 1)[0].strip().lower()
    for extension, mime_type in VIDEO_TYPES.items():
        if mime_type == media_type:
            return extension
    raise ValueError("Response does not identify a supported video container")


async def _remote_media(source: str, kind: str, staging: Path, provenance: dict) -> tuple:
    """Resolve platform pages, then acquire only checked direct or finite HLS bytes."""
    resolved = source
    if kind == "loom":
        metadata = await _loom(source, staging)
        resolved = metadata.pop("resolved_url")
        provenance["metadata"] = metadata
    if inspect_source(resolved)["source_kind"] == "hls":
        from .media_hls import acquire_hls

        acquired = await acquire_hls(resolved, staging)
        path = _owned_path(acquired["path"], staging)
        provenance["transport"] = acquired["provenance"]
        output = acquired["provenance"]["output"]
        probed = isinstance(acquired["provenance"].get("container_probe"), dict)
        return path, output["sha256"], output["bytes"], probed
    fetched = await fetch_resource(
        resolved,
        staging,
        max_bytes=get_config().media_max_input_bytes,
        allowed_content_types=_MEDIA_TYPES,
    )
    path = staging / ("media" + _video_suffix(fetched["final_url"], fetched["content_type"]))
    _owned_path(fetched["path"], staging).rename(path)
    provenance["transport"] = {
        key: redact_text(value) if isinstance(value, str) else value
        for key, value in fetched.items()
        if key != "path"
    }
    return path, fetched["sha256"], fetched["bytes"], False


async def acquire_media(source: str) -> dict:
    """Acquire one source and return a freshly verified immutable owned asset.

    Args:
        source: Local video, YouTube/Loom URL, direct HTTPS video or HLS manifest.

    Returns:
        Exact-byte catalog identity, provenance and a path usable by video_analyze.
    """
    info = _supported(source)
    catalog = await asyncio.to_thread(AssetCatalog)
    kind = info["source_kind"]
    async with asyncio.timeout(get_config().media_acquire_timeout_seconds):
        with tempfile.TemporaryDirectory(prefix="acquire-", dir=catalog.staging) as directory:
            staging = Path(directory)
            provenance = {
                "source_kind": kind,
                "method": kind,
                "live_verified": kind == "local",
                "inference_performed": False,
                "upload_performed": False,
            }
            expected_digest, expected_bytes = None, None
            probe_performed = False
            if kind == "local":
                path = _local_path(source)
            elif kind == "youtube":
                from .tools.youtube_download import download_youtube_video

                path = await download_youtube_video(info["source_id"], staging)
                _owned_path(path, staging)
                provenance["method"] = "youtube_id_only_yt_dlp"
                receipt = _youtube_receipt(path, info["source_id"])
                provenance["transport"] = receipt
                expected_digest, expected_bytes = receipt["sha256"], receipt["bytes"]
            else:
                path, expected_digest, expected_bytes, probe_performed = await _remote_media(
                    source, kind, staging, provenance
                )
            if kind != "local":
                _owned_path(path, staging)
            asset = await _adopt(catalog, path, source, provenance, expected_digest, expected_bytes)
    return {
        **asset,
        "source_kind": kind,
        "media_probe_performed": probe_performed,
        "inference_performed": False,
        "upload_performed": False,
    }


async def _adopt(
    catalog: AssetCatalog,
    path: Path,
    source: str,
    provenance: dict,
    expected_digest: str | None,
    expected_bytes: int | None,
) -> dict:
    """Wait for the bounded copy worker before cleaning its staging on cancellation."""
    canceled = threading.Event()
    task = asyncio.create_task(
        asyncio.to_thread(
            catalog.adopt,
            path,
            alias=source,
            provenance=provenance,
            expected_digest=expected_digest,
            expected_bytes=expected_bytes,
            cancelled=canceled,
        )
    )
    return await _wait_worker(task, canceled)


async def _wait_worker(task: asyncio.Task, canceled: threading.Event):
    """Join actual copying/adoption threads before deleting their temporary files."""
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        canceled.set()
        while not task.done():
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                continue
        if not task.cancelled():
            task.exception()
        raise
