"""Bounded Pillow decoding, pixel-corner geometry and exact encoded artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import io
import math
import os
import threading
import time
from .media_acquisition import _wait_worker
from .media_local_io import _copy_hash, _open_regular
from .media_snapshot import checked_path

MAX_STILL_BYTES = 16 * 1024 * 1024
MAX_DECODED_PIXELS = 8_000_000
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_PIXELS = 16_000_000
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def check_worker(cancelled, deadline):
    """Stop cooperative image work before publication after cancel or deadline."""
    if cancelled.is_set() or time.monotonic() >= deadline:
        raise TimeoutError("Image operation canceled or exceeded its overall deadline")


async def image_worker(function, *args, deadline):
    """Join the owned Pillow worker before staging may be removed."""
    cancelled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(function, *args, cancelled, deadline))
    return await _wait_worker(task, cancelled)


def multiply(a, b):
    """Compose two concrete homogeneous pixel-corner transforms."""
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def inverse(matrix):
    """Invert the nondegenerate affine transforms produced by this engine."""
    a, b, x = matrix[0]
    c, d, y = matrix[1]
    determinant = a * d - b * c
    if not determinant:
        raise ValueError("Image transform is not invertible")
    return [[d / determinant, -b / determinant, (b * y - d * x) / determinant],
            [-c / determinant, a / determinant, (c * x - a * y) / determinant], [0, 0, 1]]


def map_point(matrix, x, y):
    """Map a top-left pixel corner without inventing rounding precision."""
    return (matrix[0][0] * x + matrix[0][1] * y + matrix[0][2],
            matrix[1][0] * x + matrix[1][1] * y + matrix[1][2])


def orientation_matrix(orientation, width, height):
    """Match Pillow EXIF 1..8 transforms using continuous stored pixel corners."""
    matrices = {1: IDENTITY, 2: [[-1, 0, width], [0, 1, 0], [0, 0, 1]],
                3: [[-1, 0, width], [0, -1, height], [0, 0, 1]],
                4: [[1, 0, 0], [0, -1, height], [0, 0, 1]],
                5: [[0, 1, 0], [1, 0, 0], [0, 0, 1]],
                6: [[0, -1, height], [1, 0, 0], [0, 0, 1]],
                7: [[0, -1, height], [-1, 0, width], [0, 0, 1]],
                8: [[0, 1, 0], [-1, 0, width], [0, 0, 1]]}
    if orientation not in matrices:
        raise ValueError("Unsupported EXIF orientation; expected 1..8")
    return matrices[orientation]


def _exif_readback(exif, include):
    """Retain at most 32 bounded top-level tags; GPS IFD traversal is not performed."""
    tags, total, truncated = [], 0, False
    if include:
        for tag, value in sorted(exif.items()):
            if isinstance(value, bytes):
                value = "bytes:" + value[:64].hex()
            elif isinstance(value, (tuple, list)):
                value = str(value[:8])
            else:
                value = str(value)
            encoded = value.encode("utf-8")
            bounded = encoded[:256].decode("utf-8", errors="ignore")
            if len(tags) >= 32 or total + len(bounded.encode()) > 4096:
                truncated = True
                break
            truncated |= len(encoded) > 256
            tags.append({"tag": int(tag), "value": bounded})
            total += len(bounded.encode())
    return {"exif_tags": tags, "exif_included": include, "exif_truncated": truncated,
            "exif_gps_present": 34853 in exif, "exif_nested_ifds_traversed": False}


def load_oriented(path, include_exif, cancelled, deadline):
    """Inspect header geometry and EXIF before bounded first-page decode."""
    try:
        from PIL import Image, ImageOps
    except ImportError as error:
        raise ImportError("Pillow is unavailable; install video-research-mcp[images] for local image editing") from error

    check_worker(cancelled, deadline)
    with _open_regular(checked_path(str(path))) as reader:
        if os.fstat(reader.fileno()).st_size > MAX_STILL_BYTES:
            raise ValueError("Still image exceeds the 16 MiB source byte limit")
        with Image.open(reader, formats=["PNG", "JPEG", "WEBP", "BMP", "GIF", "TIFF"]) as opened:
            width, height = opened.size
            if width <= 0 or height <= 0 or width * height > MAX_DECODED_PIXELS:
                raise ValueError("Decoded image exceeds the 8 megapixel input limit")
            exif = opened.getexif()
            orientation = exif.get(274, 1)
            matrix = orientation_matrix(orientation, width, height)
            exif_metadata = _exif_readback(exif, include_exif)
            profile = opened.info.get("icc_profile")
            mode, source_format = opened.mode, opened.format
            opened.seek(0)
            oriented = ImageOps.exif_transpose(opened)
            try:
                image = oriented.convert("RGBA")
            finally:
                oriented.close()
    image.info.clear()
    check_worker(cancelled, deadline)
    metadata = {"stored_width": width, "stored_height": height,
                "oriented_width": image.width, "oriented_height": image.height,
                "exif_orientation": orientation, "source_mode": mode,
                "source_format": source_format,
                "source_has_transparency": image.getchannel("A").getextrema() != (255, 255),
                "icc_profile_present": bool(profile),
                "icc_profile_sha256": hashlib.sha256(profile).hexdigest() if profile else None,
                "selection": "first_frame_or_page_only", "animation_traversed": False,
                "multipage_traversed": False, "profile_handling": "stripped_not_color_managed",
                "metadata_handling": "stripped_after_exif_normalization", **exif_metadata}
    return image, metadata, matrix


def crop_bounds(width, height, region):
    """Resolve strict pixel xywh or outward-rounded normalized1000 xyxy."""
    x, y, w, h = 0, 0, width, height
    if region:
        x, y, a, b = region.coordinates
        if region.space == "normalized1000":
            x, y, a, b = (math.floor(x * width / 1000), math.floor(y * height / 1000),
                          math.ceil(a * width / 1000), math.ceil(b * height / 1000))
            w, h = a - x, b - y
        else:
            x, y, w, h = map(int, (x, y, a, b))
        if min(x, y) < 0 or min(w, h) < 1 or x + w > width or y + h > height:
            raise ValueError("Crop exceeds the oriented source pixel grid")
    return [x, y, w, h]


def crop_resize(image, request):
    """Apply declared strict crop rounding and exact or uniformly bounded resize."""
    from PIL import Image

    x, y, w, h = crop_bounds(*image.size, request.crop)
    target = (request.resize.width, request.resize.height) if request.resize else (w, h)
    if request.resize and target[0] * target[1] > request.max_pixels:
        raise ValueError("Requested resize exceeds max_pixels")
    if not request.resize:
        ratio = min(1, math.sqrt(request.max_pixels / (w * h)))
        target = max(1, int(w * ratio)), max(1, int(h * ratio))
    cropped = image.crop((x, y, x + w, y + h))
    result = cropped.resize(target, Image.Resampling.LANCZOS) if target != cropped.size else cropped
    if result is not cropped:
        cropped.close()
    matrix = [[target[0] / w, 0, -x * target[0] / w],
              [0, target[1] / h, -y * target[1] / h], [0, 0, 1]]
    return result, matrix, [x, y, w, h]


class BoundedEncoding(io.BytesIO):
    """Reject encoded data before the artifact byte ceiling is allocated."""

    def __init__(self, maximum):
        super().__init__()
        self.maximum = maximum

    def write(self, value):
        if self.tell() + len(value) > self.maximum:
            raise ValueError("Image artifacts exceed the 8 MiB aggregate byte limit")
        return super().write(value)


def _converted_output(image, output_format, background):
    """Declare opaque compositing or GIF palette/one-bit alpha before encoding."""
    from PIL import Image

    if output_format in {"jpeg", "bmp"}:
        converted = Image.new("RGB", image.size, background)
        converted.paste(image, mask=image.getchannel("A") if image.mode == "RGBA" else None)
        return converted
    if output_format == "gif":
        converted = image.convert("RGB").quantize(colors=255, dither=Image.Dither.NONE)
        converted.paste(255, mask=image.getchannel("A").point(lambda v: 255 if v < 128 else 0))
        return converted
    return None


def save_artifact(image, path, output_format, background, quality, remaining_bytes, cancelled, deadline):
    """Encode without inherited metadata and write one exclusive exact-byte artifact."""
    check_worker(cancelled, deadline)
    image.info.clear()
    options = {"png": {}, "jpeg": {"quality": quality}, "webp": {"quality": quality},
               "bmp": {}, "gif": {"transparency": 255}}
    converted = _converted_output(image, output_format, background)
    with BoundedEncoding(remaining_bytes) as buffer:
        try:
            (converted or image).save(buffer, format=output_format.upper(), **options[output_format])
            data = buffer.getvalue()
        finally:
            if converted:
                converted.close()
    check_worker(cancelled, deadline)
    path = checked_path(str(path))
    with path.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        writer.write(data)
        writer.flush()
        os.fsync(writer.fileno())
    actual_digest, size = _copy_hash(path, cancelled=cancelled, max_bytes=remaining_bytes)
    return {"path": str(path), "sha256": actual_digest, "bytes": size,
            "width": image.width, "height": image.height,
            "mime": {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp",
                     "bmp": "image/bmp", "gif": "image/gif"}[output_format]}
