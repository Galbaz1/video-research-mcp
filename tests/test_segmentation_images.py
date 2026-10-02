"""Fixed first-party raster controls for original-grid segmentation evidence."""

import base64
from copy import deepcopy
import hashlib
import io
import threading
import time

from PIL import Image
import pytest

from video_research_mcp.image_preprocessing import image_worker
from video_research_mcp.media_snapshot import snapshot
from video_research_mcp import segmentation_images as images


def encode(image):
    """Encode an independently constructed first-party PNG without metadata."""
    with io.BytesIO() as buffer:
        image.save(buffer, format="PNG")
        return buffer.getvalue()


def fixture_pngs():
    """Use the frozen 32x24 source/mask/overlay grid and exact pixel oracles."""
    bodies = {}
    for name, mode, color, rectangle in [("source", "RGB", (40, 60, 80), (200, 100, 50)),
                                        ("mask", "L", 0, 255), ("overlay", "RGB", (40, 60, 80), (225, 55, 28))]:
        with Image.new(mode, (32, 24), color) as image:
            image.paste(rectangle, (8, 6, 24, 18))
            bodies[name] = encode(image)
    return bodies


def response_fixture():
    """Declare mock score/corners; these carry no model semantic truth."""
    bodies = fixture_pngs()
    return {"prompt": "rectangle", "num_masks": 1, "results": [{"score": 0.875, "box": [8, 6, 24, 18],
            "mask_b64": base64.b64encode(bodies["mask"]).decode()}], "image_b64": base64.b64encode(bodies["overlay"]).decode()}


@pytest.fixture(autouse=True)
def image_fence(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


async def test_prepared_rgb_preserves_fixed_pixels_exact_wire_and_original(tmp_path):
    bodies = fixture_pngs()
    source = tmp_path / "source.png"
    source.write_bytes(bodies["source"])
    sha = hashlib.sha256(bodies["source"]).hexdigest()
    async with snapshot(str(source), sha) as owned:
        original, prepared, wire = await image_worker(images.prepare, owned, deadline=owned.deadline)
        assert wire == bodies["source"] and prepared["sha256"] == sha
        assert original["sha256"] == sha and original["exif_orientation"] == 1
        assert (original["stored_width"], original["stored_height"]) == (32, 24)
        assert prepared["pixel_sha256"] == "95f0a6b3bd90d42054df1ba37f3220539cbedd37eed8bb96b21815f27bb0dd3f"
        assert original["resize"] is None and original["crop"] is None
    assert source.read_bytes() == bodies["source"]


def test_real_mask_overlay_pixels_and_full_precision_are_retained():
    payload = response_fixture()
    payload["results"][0]["score"] = 0.875123456789
    payload["results"][0]["box"] = [8.125123456789, 6, 24, 18]
    masks, overlay = images.validate_response(payload, "rectangle", (32, 24), threading.Event(), time.monotonic() + 10)
    body, record = masks[0]
    assert body == fixture_pngs()["mask"] and overlay[0] == fixture_pngs()["overlay"]
    assert record["foreground_pixels"] == 192 and record["total_pixels"] == 768 and record["coverage"] == 0.25
    assert record["pixel_sha256"] == "49de19a279f43d5777d796d964b1a81e962f86ba1ac6abe8e32db1aafdb2ea13"
    assert overlay[1]["pixel_sha256"] == "b44aaf00dc0e0f2c5bb015962b786cf64defe296b758eddfb28c6c24143e179a"
    assert record["score"] == 0.875123456789 and record["box_xyxy"][0] == 8.125123456789


@pytest.mark.parametrize("damage", ["base64", "not_png", "truncated", "trailing", "crc", "rgb", "palette", "nonbinary", "empty", "size", "animated"])
def test_invalid_mask_cannot_become_a_proposal(damage):
    body = fixture_pngs()["mask"]
    value = base64.b64encode(body).decode()
    if damage == "base64":
        value += "!"
    elif damage == "not_png":
        body = b"not png"
    elif damage in {"truncated", "trailing", "crc"}:
        body = body[:-1] if damage == "truncated" else body + b"extra" if damage == "trailing" else body[:29] + bytes([body[29] ^ 1]) + body[30:]
    else:
        mode = "RGB" if damage == "rgb" else "P" if damage == "palette" else "L"
        size = (33, 24) if damage == "size" else (32, 24)
        with Image.new(mode, size, 127 if damage == "nonbinary" else 0 if damage == "empty" else 255) as image:
            if damage == "animated":
                with io.BytesIO() as buffer:
                    image.save(buffer, format="PNG", save_all=True, append_images=[Image.new("L", size, 0)])
                    body = buffer.getvalue()
            else:
                body = encode(image)
    if damage != "base64":
        value = base64.b64encode(body).decode()
    with pytest.raises((ValueError, OSError)):
        images.decoded_png(value, (32, 24), True, threading.Event(), time.monotonic() + 10)


@pytest.mark.parametrize("damage", ["null", "list", "missing", "prompt", "bool_count", "float_count", "negative", "large", "count", "result", "mask", "overlay"])
def test_response_population_requires_complete_matching_schema(damage):
    payload = deepcopy(response_fixture())
    if damage in {"null", "list", "missing"}:
        payload = None if damage == "null" else [] if damage == "list" else {}
    elif damage == "prompt":
        payload["prompt"] = "other"
    elif damage in {"bool_count", "float_count", "negative", "large", "count"}:
        payload["num_masks"] = {"bool_count": True, "float_count": 1.0, "negative": -1, "large": 17, "count": 0}[damage]
    elif damage == "result":
        payload["results"] = [None]
    elif damage == "mask":
        del payload["results"][0]["mask_b64"]
    else:
        del payload["image_b64"]
    with pytest.raises((ValueError, KeyError)):
        images.validate_response(payload, "rectangle", (32, 24), threading.Event(), time.monotonic() + 10)


@pytest.mark.parametrize("field,value", [("score", True), ("score", "0.5"), ("score", float("nan")), ("score", float("inf")),
                                        ("score", -0.1), ("score", 1.1), ("box", [True, 6, 24, 18]),
                                        ("box", [8, 6, float("nan"), 18]), ("box", [8, 6, 33, 18]),
                                        ("box", [8, 18, 24, 6]), ("box", [8, 6, 8, 18]), ("box", [8, 6, 24])])
def test_score_and_original_corner_bounds_refuse_coercion(field, value):
    payload = response_fixture()
    payload["results"][0][field] = value
    with pytest.raises(ValueError):
        images.validate_response(payload, "rectangle", (32, 24), threading.Event(), time.monotonic() + 10)


def test_four_megapixel_mask_bound_and_empty_abstention_are_explicit():
    with pytest.raises(ValueError, match="4 megapixel"):
        images.validate_response({"prompt": "rectangle", "num_masks": 5, "results": [{}] * 5}, "rectangle", (1000, 1000), threading.Event(), time.monotonic() + 10)
    assert images.validate_response({"prompt": "rectangle", "num_masks": 0, "results": []}, "rectangle", (32, 24), threading.Event(), time.monotonic() + 10) == ([], None)


@pytest.mark.parametrize("damage", ["orientation", "pixels", "animation"])
async def test_source_grid_is_refused_without_normalization_or_resize(tmp_path, damage):
    source = tmp_path / "source.png"
    with Image.new("RGB", (1001, 1000) if damage == "pixels" else (32, 24), "white") as image:
        if damage == "orientation":
            exif = image.getexif()
            exif[274] = 6
            image.save(source, exif=exif)
        elif damage == "animation":
            image.save(source, save_all=True, append_images=[Image.new("RGB", image.size, "black")])
        else:
            image.save(source)
    with pytest.raises(ValueError):
        async with snapshot(str(source), hashlib.sha256(source.read_bytes()).hexdigest()) as owned:
            await image_worker(images.prepare, owned, deadline=owned.deadline)
    assert not list((tmp_path / "cache/media/views").glob("*"))
