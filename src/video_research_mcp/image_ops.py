"""Bounded local PNG inspection and cropping using an optional installed FFmpeg."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import zlib

from .config import get_config
from .local_path_policy import enforce_local_access_root, resolve_path
from .redaction import redact_text

MAX_INPUT_PIXELS = 8_000_000
MAX_OUTPUT_PIXELS = 4_000_000
MAX_DECODE_ALLOCATION = 64 * 1024 * 1024


def _source_digest(path: Path) -> str:
    """Hash bounded source bytes without an unbounded whole-file allocation."""
    digest = hashlib.sha256()
    consumed = 0
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            consumed += len(chunk)
            if consumed > get_config().media_max_input_bytes:
                raise ValueError("Image exceeds MEDIA_MAX_INPUT_BYTES")
            digest.update(chunk)
    return digest.hexdigest()


def inspect_png(file_path: str) -> dict:
    """Validate bounded PNG header metadata before decoding or allocating pixels."""
    path = enforce_local_access_root(resolve_path(file_path))
    if not path.is_file():
        raise FileNotFoundError("PNG source is not a regular file")
    if path.stat().st_size > get_config().media_max_input_bytes:
        raise ValueError("Image exceeds MEDIA_MAX_INPUT_BYTES")
    with path.open("rb") as stream:
        header = stream.read(33)
    if len(header) != 33 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR":
        raise ValueError("Expected a PNG with a complete IHDR header")
    if zlib.crc32(header[12:29]) != struct.unpack(">I", header[29:33])[0]:
        raise ValueError("PNG header checksum is invalid")
    width, height = struct.unpack(">II", header[16:24])
    if not width or not height or width * height > MAX_INPUT_PIXELS:
        raise ValueError("PNG exceeds the decoded input pixel ceiling")
    if header[24] != 8 or header[25] not in {2, 6}:
        raise ValueError("Only 8-bit RGB or RGBA PNG input is supported")
    if header[26:29] != b"\x00\x00\x00":
        raise ValueError("Only standard noninterlaced PNG input is supported")
    return {"path": str(path), "width": width, "height": height}


def crop_png(file_path: str, output_path: str, box: tuple[int, int, int, int]) -> dict:
    """Crop an in-bounds PNG rectangle and atomically retain its checked artifact.

    Args:
        file_path: Original PNG within the local access fence.
        output_path: New PNG path within the same server access fence.
        box: Integer x, y, width and height in original image pixels.

    Returns:
        Source/output hashes, original dimensions and exact crop coordinates.
    """
    source = inspect_png(file_path)
    if len(box) != 4 or any(type(value) is not int for value in box):
        raise ValueError("Crop coordinates must be four finite integers")
    x, y, width, height = box
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("Crop coordinates must have nonnegative origin and positive dimensions")
    if x + width > source["width"] or y + height > source["height"]:
        raise ValueError("Crop rectangle is outside the original image")
    if width * height > MAX_OUTPUT_PIXELS:
        raise ValueError("Crop exceeds the output pixel ceiling")
    target = enforce_local_access_root(resolve_path(output_path))
    if target.suffix.lower() != ".png" or target.exists():
        raise ValueError("Output must be a new PNG file")
    executable = shutil.which("ffmpeg")
    if not executable:
        raise RuntimeError("PNG cropping requires an independently installed FFmpeg")
    original = Path(source["path"])
    source_hash = _source_digest(original)
    artifact_hash = _render_crop(original, target, box, executable, source_hash, source)
    return {
        "source_sha256": source_hash,
        "source_width": source["width"],
        "source_height": source["height"],
        "crop_box": list(box),
        "artifact": str(target),
        "artifact_sha256": artifact_hash,
        "artifact_width": width,
        "artifact_height": height,
        "operation": "source-crop",
    }


def _freeze_source(original: Path, snapshot: Path, expected: dict, source_hash: str) -> None:
    """Bind header metadata and decoder bytes to one bounded private snapshot."""
    consumed = 0
    with original.open("rb") as source, snapshot.open("wb") as target:
        while chunk := source.read(64 * 1024):
            consumed += len(chunk)
            if consumed > get_config().media_max_input_bytes:
                raise ValueError("Image exceeds MEDIA_MAX_INPUT_BYTES")
            target.write(chunk)
    frozen = inspect_png(str(snapshot))
    if (frozen["width"], frozen["height"]) != (expected["width"], expected["height"]):
        raise ValueError("PNG source changed after header inspection")
    if _source_digest(snapshot) != source_hash:
        raise ValueError("PNG source changed before decoding")


def _render_crop(
    original: Path,
    target: Path,
    box: tuple,
    executable: str,
    source_hash: str,
    source: dict,
) -> str:
    """Decode one bounded frame, verify it and promote only a fresh output."""
    x, y, width, height = box
    with tempfile.TemporaryDirectory(prefix="vrm-crop-", dir=target.parent) as scratch:
        staged = Path(scratch) / "crop.png"
        snapshot = Path(scratch) / "source.png"
        _freeze_source(original, snapshot, source, source_hash)
        command = [
            executable,
            "-nostdin",
            "-v",
            "error",
            "-max_alloc",
            str(MAX_DECODE_ALLOCATION),
            "-threads",
            "1",
            "-max_pixels",
            str(MAX_INPUT_PIXELS),
            "-c:v",
            "png",
            "-i",
            str(snapshot),
            "-vf",
            f"crop={width}:{height}:{x}:{y},format=rgba",
            "-frames:v",
            "1",
            "-filter_threads",
            "1",
            "-threads",
            "1",
            str(staged),
        ]
        result = subprocess.run(command, capture_output=True, timeout=30, check=False)
        if result.returncode:
            raise RuntimeError(
                f"PNG crop failed: {redact_text(result.stderr.decode(errors='replace')[:500])}"
            )
        decoded = inspect_png(str(staged))
        if (decoded["width"], decoded["height"]) != (width, height):
            raise ValueError("Decoded crop dimensions differ from the requested rectangle")
        if _source_digest(original) != source_hash:
            raise ValueError("PNG source changed during cropping")
        artifact_hash = hashlib.sha256(staged.read_bytes()).hexdigest()
        os.link(staged, target)
    return artifact_hash
