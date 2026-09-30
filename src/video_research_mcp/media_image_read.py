"""Bounded local still-image decoding and exact PNG artifact readback."""

from __future__ import annotations

import math
import os
from pathlib import Path

from .image_ops import inspect_png
from .media_probe import FORMATS, MAX_DECODED_PIXELS, binary, probe_snapshot
from .media_process import run_media_process
from .media_snapshot import Snapshot, copy_hash, snapshot

MAX_FRAME_PIXELS = 1_000_000
MAX_OUTPUT_PIXELS = 16_000_000
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def limits() -> dict:
    """Describe enforced limits without claiming a process RSS bound."""
    return {"max_decoded_pixels": MAX_DECODED_PIXELS,
            "max_frame_pixels": MAX_FRAME_PIXELS, "max_output_pixels": MAX_OUTPUT_PIXELS,
            "max_artifact_bytes": MAX_ARTIFACT_BYTES, "max_frames": 48, "max_fps": 30,
            "max_single_allocation_bytes": 64 * 1024 * 1024,
            "process_rss_bound": None, "full_stream_validation": False,
            "explicit_non_square_or_invalid_sar": "rejected_before_render",
            "unspecified_sar": "rotated_stored_pixel_grid_not_verified_physical_aspect"}


def validate_pixels(max_pixels: int) -> None:
    """Validate explicit per-frame output pixels before opening an input."""
    if type(max_pixels) is not int or not 1 <= max_pixels <= MAX_FRAME_PIXELS:
        raise ValueError("max_pixels must be an integer between 1 and 1000000")


def geometry(source: dict, max_pixels: int, crop_box) -> tuple[int, int, str]:
    """Validate display-coordinate crop and compute bounded aspect-preserving size."""
    if source.get("display_geometry_supported") is False:
        raise ValueError("Native views require square pixels; normalize the explicit non-square or invalid sample aspect ratio before rendering")
    width, height = source["display_width"], source["display_height"]
    if not width or not height:
        raise ValueError("Source has no supported visual stream dimensions")
    crop = ""
    if crop_box is not None:
        if not isinstance(crop_box, (list, tuple)) or len(crop_box) != 4:
            raise ValueError("crop_box must contain x, y, width and height")
        if any(type(v) is not int for v in crop_box):
            raise ValueError("crop_box values must be integers")
        x, y, w, h = crop_box
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > width or y + h > height:
            raise ValueError("crop_box is outside the displayed source dimensions")
        width, height = w, h
        crop = f"crop={w}:{h}:{x}:{y}:exact=1,"
    ratio = min(1, math.sqrt(max_pixels / (width * height)))
    width, height = max(1, int(width * ratio)), max(1, int(height * ratio))
    if width * height > max_pixels:
        raise ValueError("Pixel budget cannot preserve this aspect ratio with at least one pixel per dimension")
    return width, height, f"{crop}scale={width}:{height},setsar=1,sidedata=mode=delete,format=rgb24"


def decode_command(owned: Snapshot, source: dict, *, before_input: list[str] | None = None) -> list[str]:
    """Build an explicitly file-only, bounded decode command for owned input bytes."""
    command = [binary("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-v", "info", "-y",
               "-max_alloc", "67108864", "-max_pixels", str(MAX_DECODED_PIXELS),
               "-threads", "1", "-filter_threads", "1", "-protocol_whitelist", "file",
               "-format_whitelist", FORMATS]
    command.extend(before_input or [])
    command.extend(["-copyts", "-i", str(owned.path)])
    if source["stream_index"] is not None:
        command.extend(["-map", f"0:{source['stream_index']}"])
    command.extend(["-an", "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1"])
    return command


async def png_artifact(path: Path) -> dict:
    """Read back actual generated PNG dimensions, bytes and full SHA256."""
    metadata = inspect_png(str(path))
    digest, size = await copy_hash(path)
    if size > MAX_ARTIFACT_BYTES:
        raise ValueError("Native image exceeds the aggregate artifact byte budget")
    os.chmod(path, 0o600)
    return {"path": str(path), "sha256": digest, "bytes": size,
            "width": metadata["width"], "height": metadata["height"]}


def coverage(frames: list[dict], window: dict | None = None, stop_reason: str | None = None) -> dict:
    """Report sampled source points without inferring watched temporal intervals."""
    return {"sampled_points": [f["actual_seconds"] for f in frames if f["actual_seconds"] is not None],
            "decoded_count": len(frames), "requested_window": window,
            "complete": stop_reason is None, "stop_reason": stop_reason,
            "watched_intervals": []}


async def read_image(file_path: str, *, max_pixels: int = MAX_FRAME_PIXELS) -> dict:
    """Return one bounded still; animation and multipage sequences are not traversed."""
    validate_pixels(max_pixels)
    if Path(file_path).suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("Supported still formats are PNG, JPEG, WebP, BMP, GIF and TIFF")
    async with snapshot(file_path) as owned:
        source = await probe_snapshot(owned, still=True)
        _, _, transform = geometry(source, max_pixels, None)
        output = owned.directory / "frame001.png"
        command = decode_command(owned, source)
        command.extend(["-vf", transform, "-frames:v", "1", "-threads", "1", str(output)])
        await run_media_process(command, owned.remaining())
        frame = {**await png_artifact(output), "requested_seconds": None,
                 "actual_seconds": None, "original_pts": None, "time_base": None,
                 "selection_method": "first_still", "approximate": False,
                 "delta_seconds": None, "crop_box": None}
        return {"source": source, "frames": [frame], "coverage": coverage([frame]),
                "status": "complete", "limits": {**limits(),
                "still_selection": "first_frame_or_page_only",
                "animation_traversed": False, "multipage_traversed": False,
                "exif_orientation_normalized_or_verified": False,
                "embedded_color_profile_verified": False}}
