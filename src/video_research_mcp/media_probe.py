"""Bounded local ffprobe metadata from verified exact-byte media snapshots."""

from __future__ import annotations

import json
import math
import shutil
from fractions import Fraction

from .media_process import run_media_process
from .media_snapshot import Snapshot, snapshot

MAX_DECODED_PIXELS = 8_000_000
FORMATS = "mov,matroska,webm,avi,mpeg,mpegvideo,mpegts,asf,wav,mp3,flac,ogg,aac,aiff,image2,image2pipe,png_pipe,jpeg_pipe,webp_pipe,bmp_pipe,gif,tiff_pipe"


def binary(name: str) -> str:
    """Resolve a separately installed native binary without installing runtimes."""
    value = shutil.which(name)
    if not value:
        raise ImportError(f"{name} is unavailable; install FFmpeg separately for native media")
    return value


def finite(value) -> float | None:
    """Convert observed finite numeric metadata; unavailable values remain unknown."""
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def video_stream(streams: list[dict]) -> dict | None:
    """Select the first actual video stream, excluding attached cover pictures."""
    return next((s for s in streams if s.get("codec_type") == "video"
                 and not s.get("disposition", {}).get("attached_pic")), None)


def _aspect(stream: dict | None) -> tuple:
    """Distinguish observed square pixels from an explicitly unspecified pixel grid."""
    if not stream:
        return None, None, False, False
    value = stream.get("sample_aspect_ratio")
    if value is None:
        return None, "stored_pixel_grid_sar_unspecified", False, True
    try:
        ratio = Fraction(value.replace(":", "/"))
    except (AttributeError, ValueError, ZeroDivisionError):
        return value, "unsupported_invalid_sample_aspect_ratio", False, False
    if ratio == 1:
        return value, "observed_square_pixels", True, True
    return value, "unsupported_non_square_sample_aspect_ratio", False, False


def _geometry(stream: dict | None) -> tuple:
    if not stream:
        return None, None, None, None, None
    width, height = stream.get("width"), stream.get("height")
    if type(width) is not int or type(height) is not int or width <= 0 or height <= 0:
        return None, None, None, None, None
    if width * height > MAX_DECODED_PIXELS:
        raise ValueError("Decoded media exceeds the 8 megapixel input limit")
    angle = finite(stream.get("tags", {}).get("rotate")) or 0.0
    for item in stream.get("side_data_list", []):
        if "rotation" in item:
            angle = finite(item["rotation"])
    if angle is None or angle % 90:
        raise ValueError("Unsupported non-orthogonal video rotation")
    if not _aspect(stream)[3]:
        return width, height, None, None, angle
    rotated = int(angle) % 180 == 90
    return width, height, height if rotated else width, width if rotated else height, angle


async def probe_snapshot(owned: Snapshot, *, still: bool = False) -> dict:
    """Read stream/container metadata under bounded file-only native processing."""
    stdout, _ = await run_media_process(
        [binary("ffprobe"), "-v", "error", "-max_alloc", "67108864", "-max_pixels",
         str(MAX_DECODED_PIXELS), "-threads", "1", "-protocol_whitelist", "file",
         "-format_whitelist", FORMATS, "-show_format", "-show_streams", "-show_chapters",
         "-of", "json", "-i", str(owned.path)], owned.remaining(),
    )
    observed = json.loads(stdout)
    streams = observed.get("streams")
    if not isinstance(streams, list) or not all(isinstance(s, dict) for s in streams):
        raise ValueError("ffprobe returned invalid stream metadata")
    stream = video_stream(streams)
    width, height, display_w, display_h, rotation = _geometry(stream)
    sar, geometry_basis, aspect_verified, geometry_supported = _aspect(stream)
    fmt = observed.get("format", {})
    stream_duration = finite(stream.get("duration")) if stream else None
    duration = finite(fmt.get("duration"))
    duration = duration if duration is not None else stream_duration
    start = finite(fmt.get("start_time"))
    if start is None and stream:
        start = finite(stream.get("start_time"))
    stream_start = finite(stream.get("start_time")) if stream else None
    presentation_end = duration
    if stream_start is not None and stream_duration is not None and start is not None:
        presentation_end = stream_start - start + stream_duration
    time_base = stream.get("time_base") if stream and not still else None
    if time_base is not None and Fraction(time_base) <= 0:
        raise ValueError("Video stream has an invalid presentation time base")
    return {
        "path": str(owned.original), "sha256": owned.sha256, "bytes": owned.size,
        "source_revision": "sha256:" + owned.sha256,
        "duration_seconds": None if still else duration,
        "container_start_seconds": None if still else start,
        "stream_start_seconds": None if still else stream_start,
        "stream_duration_seconds": None if still else stream_duration,
        "presentation_end_seconds": None if still else presentation_end,
        "stored_width": width, "stored_height": height,
        "display_width": display_w, "display_height": display_h,
        "sample_aspect_ratio": sar, "display_geometry_basis": geometry_basis,
        "display_aspect_ratio": stream.get("display_aspect_ratio") if stream else None,
        "pixel_aspect_verified": aspect_verified, "display_geometry_supported": geometry_supported,
        "rotation_degrees": None if still else rotation, "time_base": time_base,
        "stream_index": None if still or not stream else stream.get("index"),
        "streams": streams, "chapters": observed.get("chapters", []),
        "metadata_method": "bounded_local_ffprobe_exact_snapshot",
    }


async def inspect_media(file_path: str) -> dict:
    """Inspect exact local source bytes without inference or full-stream validation."""
    async with snapshot(file_path) as owned:
        return await probe_snapshot(owned, still=owned.path.suffix.lower() in
                                    {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"})
