"""Exact local frame snapshots for the selected Wan 2.7 HTTP media contract."""

import base64
import hashlib
from io import BytesIO
from pathlib import Path

from .file_io import open_regular
from .render_storyboard_sources import confined_path

I2V_WIRE_MODEL = "wan2.7-i2v-2026-04-25"
MAX_IMAGE_BYTES = 20_000_000
IMAGE_MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "BMP": "image/bmp", "WEBP": "image/webp"}


def inspect_image(body: bytes) -> dict:
    """Decode a bounded still image and refuse unsupported format or transparency."""
    try:
        from PIL import Image
    except ImportError:
        raise ValueError("Pillow image decoder is required before I2V reservation") from None
    try:
        with Image.open(BytesIO(body)) as image:
            width, height = image.size
            if (image.format not in IMAGE_MIMES
                    or not 240 <= width <= 8000 or not 240 <= height <= 8000
                    or not 1 / 8 <= width / height <= 8):
                raise ValueError("Selected I2V image format, dimensions or frame count is unsupported")
            metadata = {"format": image.format, "mime_type": IMAGE_MIMES[image.format],
                        "width": width, "height": height}
            image.verify()
        with Image.open(BytesIO(body)) as image:
            if (getattr(image, "n_frames", 1) != 1 or "A" in image.getbands() or "a" in image.getbands()
                    or "transparency" in image.info or image.getexif().get(274, 1) != 1):
                raise ValueError("Selected I2V frame must be single-frame, opaque and have unrotated dimensions")
            image.load()
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Selected I2V image did not decode ({type(exc).__name__})") from None
    return metadata


def reference_snapshot(project: Path, reference: dict) -> tuple[bytes, dict]:
    """Hash and decode the same stable regular-file bytes that will be encoded."""
    source = reference["source"]
    with open_regular(confined_path(project, source["path"])) as (stream, info):
        if not 0 < info.st_size <= MAX_IMAGE_BYTES:
            raise ValueError("Selected I2V frame must contain at most 20 MB")
        body = stream.read(MAX_IMAGE_BYTES + 1)
    sha = hashlib.sha256(body).hexdigest()
    if len(body) > MAX_IMAGE_BYTES or sha != source["sha256"]:
        raise ValueError("Selected I2V reference integrity failed")
    return body, {"role": reference["role"], "source": source, "sha256": sha,
                  "size_bytes": len(body), **inspect_image(body)}


def freeze_references(project: Path, generation: dict) -> list[dict]:
    """Admit only one first frame, optionally followed by one last frame."""
    roles = [reference["role"] for reference in generation["references"]]
    if (generation["continuation"] is not None or len(roles) != len(set(roles))
            or set(roles) not in ({"first_frame"}, {"first_frame", "last_frame"})):
        raise ValueError("Selected I2V supports only first_frame or first_frame plus last_frame here")
    metadata = [reference_snapshot(project, reference)[1] for reference in generation["references"]]
    first = next(item for item in metadata if item["role"] == "first_frame")
    numerator, denominator = map(int, generation["ratio"].split(":"))
    if first["width"] * denominator != first["height"] * numerator:
        raise ValueError("Declared I2V aspect ratio differs from the actual first frame")
    dimensions = generation.get("expected_dimensions")
    if not dimensions or any(value % 16 for value in dimensions):
        raise ValueError("I2V requires declared output dimensions that are multiples of 16")
    width, height = dimensions
    if abs(width * denominator - height * numerator) > 16 * (numerator + denominator):
        raise ValueError("Declared I2V output dimensions exceed the admitted aspect rounding bound")
    return metadata


def provider_media(project: Path, generation: dict, frozen_metadata: list[dict]) -> list[dict]:
    """Encode unchanged exact snapshots without reformatting or uploading them."""
    media = []
    for reference, expected in zip(generation["references"], frozen_metadata, strict=True):
        body, actual = reference_snapshot(project, reference)
        if actual != expected:
            raise ValueError("Selected I2V reference differs from its frozen metadata")
        media.append({"type": reference["role"],
                      "url": f"data:{actual['mime_type']};base64,{base64.b64encode(body).decode('ascii')}"})
    return media
