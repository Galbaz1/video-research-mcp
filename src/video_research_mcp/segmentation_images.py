"""Bounded original-grid preparation and exact external PNG mask/overlay evidence."""

import base64
import hashlib
import io
import math
import os
import struct
import zlib

from .image_preprocessing import (
    MAX_ARTIFACT_BYTES, MAX_STILL_BYTES, check_worker, load_oriented, save_artifact,
)
from .media_local_io import _copy_hash, _open_regular
from .media_snapshot import checked_path

MAX_GRID_PIXELS = 1000000
MAX_MASK_PIXELS = 4000000


def source_header(path, cancelled, deadline) -> None:
    """Reject non-stills, oversized grids and orientation changes before decode/upload."""
    from PIL import Image

    check_worker(cancelled, deadline)
    with _open_regular(checked_path(str(path))) as reader:
        if os.fstat(reader.fileno()).st_size > MAX_STILL_BYTES:
            raise ValueError("Source exceeds 16 MiB")
        with Image.open(reader, formats=["PNG", "JPEG", "WEBP", "BMP", "GIF", "TIFF"]) as image:
            if image.width * image.height > MAX_GRID_PIXELS or min(image.size) < 1:
                raise ValueError("Source exceeds the unchanged 1 megapixel grid")
            if getattr(image, "n_frames", 1) != 1:
                raise ValueError("Segmentation supports single-frame still images only")
            if image.getexif().get(274, 1) != 1:
                raise ValueError("Non-1 EXIF orientation is unsupported; no normalization is performed")
    check_worker(cancelled, deadline)


def prepare(owned, cancelled, deadline) -> tuple[dict, dict, bytes]:
    """Prepare an unscaled RGB PNG using the joined qualified Pillow helpers."""
    source_header(owned.path, cancelled, deadline)
    image, metadata, _ = load_oriented(owned.path, False, cancelled, deadline)
    try:
        with image.convert("RGB") as rgb:
            pixel_sha = hashlib.sha256(rgb.tobytes()).hexdigest()
            record = save_artifact(rgb, owned.directory / "prepared.png", "png", (255, 255, 255),
                                   100, MAX_ARTIFACT_BYTES, cancelled, deadline)
    finally:
        image.close()
    record.update(role="image", pixel_sha256=pixel_sha, pixel_mode="RGB", origin="source_derived")
    with _open_regular(checked_path(record["path"])) as reader:
        body = reader.read(MAX_ARTIFACT_BYTES + 1)
    if len(body) != record["bytes"] or hashlib.sha256(body).hexdigest() != record["sha256"]:
        raise ValueError("Prepared PNG bytes changed")
    source = {"path": str(owned.original), "sha256": owned.sha256, "bytes": owned.size,
              **metadata, "grid": "stored_untransformed_pixels", "resize": None, "crop": None}
    check_worker(cancelled, deadline)
    return source, record, body


def complete_png(body: bytes) -> None:
    """Require complete CRC-valid PNG chunks with no animation or trailing bytes."""
    if body[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("Expected PNG bytes")
    offset, kinds = 8, []
    while offset < len(body):
        if offset + 12 > len(body):
            raise ValueError("Truncated PNG chunk")
        size = struct.unpack(">I", body[offset:offset + 4])[0]
        end = offset + 12 + size
        if end > len(body):
            raise ValueError("Truncated PNG data")
        kind = body[offset + 4:offset + 8]
        if kind in {b"acTL", b"fcTL", b"fdAT"}:
            raise ValueError("Animated PNG is unsupported")
        if zlib.crc32(body[offset + 4:end - 4]) != struct.unpack(">I", body[end - 4:end])[0]:
            raise ValueError("PNG chunk checksum differs")
        kinds.append(kind)
        offset = end
        if kind == b"IEND":
            if size or offset != len(body):
                raise ValueError("PNG end or trailing bytes are invalid")
            break
    if not kinds or kinds[0] != b"IHDR" or kinds.count(b"IHDR") != 1 or b"IDAT" not in kinds or kinds[-1] != b"IEND":
        raise ValueError("PNG requires one complete image")


def decoded_png(value, size, mask, cancelled, deadline) -> tuple[bytes, dict]:
    """Validate actual single-frame source-size PNGs and binary mask pixels."""
    from PIL import Image

    check_worker(cancelled, deadline)
    if not isinstance(value, str) or len(value) > 350000:
        raise ValueError("Invalid or oversized Base64 PNG")
    body = base64.b64decode(value, validate=True)
    complete_png(body)
    with Image.open(io.BytesIO(body), formats=["PNG"]) as opened:
        if opened.size != size or getattr(opened, "n_frames", 1) != 1 or opened.getexif().get(274, 1) != 1:
            raise ValueError("PNG must retain the original single-frame pixel grid")
        if opened.mode not in ({"L", "1"} if mask else {"RGB", "RGBA"}):
            raise ValueError("Mask must be binary L/1; overlay must be RGB/RGBA")
        opened.load()
        stored_mode = opened.mode
        with opened.convert("L") if mask else opened.copy() as image:
            pixels = image.tobytes()
            detail = {"pixel_sha256": hashlib.sha256(pixels).hexdigest(), "pixel_mode": image.mode,
                      "stored_mode": stored_mode}
            if mask:
                histogram = image.histogram()
                foreground = histogram[255]
                if sum(histogram[1:255]) or not foreground:
                    raise ValueError("Mask must contain nonempty binary foreground")
                detail.update(foreground_pixels=foreground, total_pixels=size[0] * size[1],
                              coverage=foreground / (size[0] * size[1]))
    check_worker(cancelled, deadline)
    return body, detail


def number(value) -> float:
    """Preserve finite numeric precision while refusing bools and coercion."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("Expected finite numeric score/corners")
    return float(value)


def validate_response(payload, prompt, size, cancelled, deadline) -> tuple[list, tuple | None]:
    """Admit the complete actual raster population before publishing any returned PNG."""
    if not isinstance(payload, dict) or payload.get("prompt") != prompt:
        raise ValueError("Response must be an object matching the exact prompt")
    count, results = payload.get("num_masks"), payload.get("results")
    if type(count) is not int or not 0 <= count <= 16 or not isinstance(results, list) or len(results) != count:
        raise ValueError("Mask count must exactly match 0..16 results")
    if count * size[0] * size[1] > MAX_MASK_PIXELS:
        raise ValueError("Masks exceed the 4 megapixel aggregate grid limit")
    masks = []
    for index, value in enumerate(results):
        if not isinstance(value, dict):
            raise ValueError("Mask result must be an object")
        score = number(value["score"])
        box = value["box"]
        if not isinstance(box, list) or len(box) != 4 or not 0 <= score <= 1:
            raise ValueError("Score/box population is invalid")
        x1, y1, x2, y2 = map(number, box)
        if not 0 <= x1 < x2 <= size[0] or not 0 <= y1 < y2 <= size[1]:
            raise ValueError("Box must be ordered within original pixel corners")
        body, detail = decoded_png(value["mask_b64"], size, True, cancelled, deadline)
        masks.append((body, {"index": index, "score": score, "box_xyxy": [x1, y1, x2, y2], **detail}))
    overlay = decoded_png(payload.get("image_b64"), size, False, cancelled, deadline) if count else None
    return masks, overlay


def persist_png(body, detail, path, size, origin, role, remaining, cancelled, deadline) -> dict:
    """Preserve exact service PNG bytes rather than synthesizing a replacement overlay."""
    check_worker(cancelled, deadline)
    if len(body) > remaining:
        raise ValueError("Artifacts exceed the unchanged 8 MiB aggregate byte limit")
    path = checked_path(str(path))
    with path.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        writer.write(body)
        writer.flush()
        os.fsync(writer.fileno())
    sha, length = _copy_hash(path, cancelled=cancelled, max_bytes=remaining)
    if (sha, length) != (hashlib.sha256(body).hexdigest(), len(body)):
        raise ValueError("Returned PNG changed during publication")
    return {"path": str(path), "sha256": sha, "bytes": length, "width": size[0], "height": size[1],
            "mime": "image/png", "role": role, "pixel_sha256": detail["pixel_sha256"],
            "pixel_mode": detail["pixel_mode"], "origin": origin}


def publish(response, request, owned, prepared, origin, cancelled, deadline) -> tuple[list, list]:
    """Publish a fully validated result into this invocation's exclusive staging only."""
    size = prepared["width"], prepared["height"]
    masks, overlay = validate_response(response, request.prompt, size, cancelled, deadline)
    artifacts, records = [prepared], []
    for body, detail in masks:
        artifact = persist_png(body, detail, owned.directory / f"mask-{detail['index']:02d}.png", size,
                               origin, "alpha_mask", MAX_ARTIFACT_BYTES - sum(a["bytes"] for a in artifacts), cancelled, deadline)
        artifacts.append(artifact)
        records.append({key: value for key, value in detail.items() if key not in {"pixel_sha256", "pixel_mode"}} | {"mask": artifact})
    if overlay:
        body, detail = overlay
        artifacts.append(persist_png(body, detail, owned.directory / "overlay.png", size, origin, "image",
                                     MAX_ARTIFACT_BYTES - sum(a["bytes"] for a in artifacts), cancelled, deadline))
    check_worker(cancelled, deadline)
    return artifacts, records
