"""Bounded contact sheets retaining every input frame's exact temporal mapping."""

from __future__ import annotations

import math
import re
from pathlib import Path

from .config import get_config
from .media_image_read import MAX_ARTIFACT_BYTES, MAX_OUTPUT_PIXELS, limits, png_artifact
from .media_probe import binary
from .media_process import run_media_process
from .media_snapshot import checked_path, copy_hash, snapshot


def _frame_path(frame: dict) -> Path:
    path = checked_path(frame["path"])
    base = checked_path(str(Path(get_config().cache_dir) / "media" / "views"))
    if path.parent.parent != base or not re.fullmatch(r"[0-9a-f]{32}", path.parent.name):
        raise PermissionError("Sheet inputs must be artifacts in the private owned media view cache")
    return path


async def _copy_frames(frames: list[dict], directory: Path) -> None:
    for index, frame in enumerate(frames):
        path = _frame_path(frame)
        artifact = await png_artifact(path)
        if any(artifact[k] != frame[k] for k in ("sha256", "bytes", "width", "height")):
            raise ValueError("Contact sheet frame artifact changed after sampling")
        copied = await copy_hash(path, directory / f"tile{index + 1:03d}.png")
        if copied != (frame["sha256"], frame["bytes"]):
            raise ValueError("Contact sheet frame changed during copying")


def _layout(frames: list[dict], columns: int) -> tuple[int, int, int]:
    rows = math.ceil(len(frames) / columns)
    width, height = max(f["width"] for f in frames), max(f["height"] for f in frames)
    used_pixels = sum(f["width"] * f["height"] for f in frames)
    available_bytes = MAX_ARTIFACT_BYTES - sum(f["bytes"] for f in frames) - 65536
    available_pixels = min(MAX_OUTPUT_PIXELS - used_pixels, available_bytes // 4)
    if available_pixels < columns * rows:
        raise ValueError("No aggregate artifact budget remains for a contact sheet")
    ratio = min(1, math.sqrt(available_pixels / (width * height * columns * rows)))
    return max(1, int(width * ratio)), max(1, int(height * ratio)), rows


async def contact_sheet(result: dict, *, columns: int = 4) -> dict:
    """Compose exact sampled artifacts, preserving source/time/digest per tile.

    Args:
        result: A native frame result from this library.
        columns: Sheet columns; use one for a vertical filmstrip.

    Returns:
        Sheet artifact and tile mappings with unchanged sampled-point coverage.
    """
    if type(columns) is not int or not 1 <= columns <= 48:
        raise ValueError("columns must be between 1 and 48")
    frames, source = result["frames"], result["source"]
    if not 1 <= len(frames) <= 48:
        raise ValueError("Contact sheet requires between 1 and 48 frame artifacts")
    columns = min(columns, len(frames))
    width, height, rows = _layout(frames, columns)
    async with snapshot(source["path"], source["sha256"]) as owned:
        await _copy_frames(frames, owned.directory)
        output = owned.directory / "sheet.png"
        transform = (f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                     f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2,"
                     f"tile={columns}x{rows}:nb_frames={len(frames)},sidedata=mode=delete,format=rgb24")
        command = [binary("ffmpeg"), "-hide_banner", "-nostdin", "-v", "error", "-y",
                   "-max_alloc", "67108864", "-max_pixels", "1000000", "-threads", "1",
                   "-filter_threads", "1", "-protocol_whitelist", "file", "-format_whitelist", "image2",
                   "-framerate", "1", "-i", str(owned.directory / "tile%03d.png"),
                   "-vf", transform, "-map_metadata", "-1", "-map_chapters", "-1",
                   "-frames:v", "1", "-threads", "1", str(output)]
        await run_media_process(command, owned.remaining())
        artifact = await png_artifact(output)
        if artifact["width"] != width * columns or artifact["height"] != height * rows:
            raise ValueError("Contact sheet dimensions differ from the bounded tile layout")
        if sum(f["bytes"] for f in frames) + artifact["bytes"] > MAX_ARTIFACT_BYTES:
            raise ValueError("Frames and sheet exceed the aggregate artifact byte budget")
        await _verify_frames(frames, owned.directory)
        tiles = [{"frame_index": i, "x": i % columns * width, "y": i // columns * height,
                  "width": width, "height": height, "actual_seconds": frame["actual_seconds"],
                  "original_pts": frame["original_pts"], "time_base": frame["time_base"],
                  "source_frame_sha256": frame["sha256"]} for i, frame in enumerate(frames)]
        return {"source": source, "artifact": artifact, "tiles": tiles,
                "coverage": result["coverage"], "status": result["status"], "limits": {**limits(),
                "sheet_columns": columns, "sheet_rows": rows, "sheet_padding_in_pixel_budget": True}}


async def _verify_frames(frames: list[dict], directory: Path) -> None:
    """Verify originals and exact owned tile snapshots before exposing the sheet."""
    for index, frame in enumerate(frames):
        expected = frame["sha256"], frame["bytes"]
        if await copy_hash(_frame_path(frame)) != expected:
            raise ValueError("Contact sheet frame changed during composition")
        tile = directory / f"tile{index + 1:03d}.png"
        if await copy_hash(tile) != expected:
            raise ValueError("Contact sheet owned tile changed during composition")
        tile.unlink()
