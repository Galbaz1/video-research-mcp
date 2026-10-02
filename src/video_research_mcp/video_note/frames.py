"""Temporal illustration selection with exact PNG buffers and source commitments."""

import math
import re
from pathlib import Path

from ..config import get_config
from ..media_frames import frame_at
from ..media_snapshot import checked_path
from .io import MAX_FRAME_BYTES, NoteError, digest, png_shape, read_bytes, write_bytes


def _native_view(frame):
    """Bind only the native view returned by this extraction, never foreign fixtures."""
    path = checked_path(frame["path"])
    base = checked_path(str(Path(get_config().cache_dir) / "media" / "views"))
    if path.parent.parent != base or not re.fullmatch(r"[0-9a-f]{32}", path.parent.name):
        return None
    if not re.fullmatch(r"frame\d{3}\.png", path.name):
        raise NoteError("Unexpected native tutorial illustration path")
    file, directory = path.lstat(), path.parent.lstat()
    return path, (file.st_dev, file.st_ino), (directory.st_dev, directory.st_ino)


def _discard_view(owned):
    """Remove only the unchanged owned native PNG and its empty private directory."""
    path, expected_file, expected_directory = owned
    checked_path(str(path))
    file, directory = path.lstat(), path.parent.lstat()
    if (file.st_dev, file.st_ino) != expected_file or (directory.st_dev, directory.st_ino) != expected_directory:
        raise NoteError("Native tutorial view ownership changed; cleanup withheld")
    path.unlink()
    path.parent.rmdir()


async def collect_frames(source, steps, directory):
    """Copy at most one verified decoded source point per step; preserve text on misses."""
    records, buffers, warnings, duration = [], [], [], None
    for index, step in enumerate(steps, 1):
        native = None
        requested = (step["start_seconds"] + step["end_seconds"]) / 2
        try:
            value = await frame_at(source["path"], time_seconds=requested, max_pixels=250000,
                                   selection="precise", expected_source_sha256=source["sha256"])
            if value["frames"]:
                native = _native_view(value["frames"][0])
            if value["source"]["sha256"] != source["sha256"] or len(value["frames"]) != 1:
                raise NoteError("Frame extraction does not bind the selected source")
            extent = value["source"].get("presentation_end_seconds") or value["source"].get("duration_seconds")
            if type(extent) not in (int, float) or not math.isfinite(extent) or extent <= 0:
                raise NoteError("Source duration unavailable")
            if duration is not None and duration != extent:
                raise NoteError("Source presentation extent changed")
            duration = extent
            frame = value["frames"][0]
            actual = frame["actual_seconds"]
            if type(actual) not in (float, int) or not math.isfinite(actual) or not step["start_seconds"] <= actual < step["end_seconds"]:
                raise NoteError("Decoded frame point is outside the requested tutorial step")
            data = read_bytes(frame["path"], MAX_FRAME_BYTES)
            width, height = png_shape(data, 250000)
            if digest(data) != frame["sha256"] or len(data) != frame["bytes"] or (width, height) != (frame["width"], frame["height"]):
                raise NoteError("Frame bytes differ from their extraction identity")
            if sum(map(len, buffers)) + len(data) > MAX_FRAME_BYTES:
                raise NoteError("Tutorial frames exceed 8 MiB aggregate")
            artifact = write_bytes(directory / f"frame-{index:02d}.png", data)
            records.append({**artifact, "step_index": index, "width": width, "height": height,
                            "requested_seconds": requested, "actual_seconds": actual,
                            "original_pts": frame["original_pts"], "time_base": frame["time_base"],
                            "source_sha256": source["sha256"], "selection": "first_decoded_at_or_after"})
            buffers.append(data)
        except Exception:
            warnings.append(f"Step {index}: source illustration unavailable; tutorial text retained.")
        finally:
            if native is not None:
                _discard_view(native)
    if duration is not None and any(step["end_seconds"] > duration for step in steps):
        raise NoteError("Tutorial step interval exceeds the observed source presentation extent")
    return records, buffers, warnings, duration
