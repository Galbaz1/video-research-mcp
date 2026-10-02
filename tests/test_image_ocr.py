"""Bounded OCR protocols with real preparation/manifest geometry and mocked local engines."""

import asyncio
import hashlib
import json
import struct
import zlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from video_research_mcp.image_ocr import locate_text, map_observation, parse_tsv, recognize_image
from video_research_mcp.models.image_ocr import ImageOCRRequest

HEADER = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))


def tsv(words):
    return (HEADER + "".join(
        f"5\t1\t1\t1\t1\t{i+1}\t{i*20}\t10\t15\t12\t95\t{text}\n"
        for i, text in enumerate(words)
    )).encode()


def native_payload(width, height):
    value = {"kind": "line", "text": "OWNED line", "confidence": 0.75,
             "raw_box": [0.25, 0.25, 0.5, 0.5],
             "raw_points": [[0.25, 0.75], [0.75, 0.75], [0.75, 0.25], [0.25, 0.25]]}
    data = {"protocol": 1, "width": width, "height": height,
            "coordinate_space": "normalized_bottom_left", "observations": [value]}
    return json.dumps(data).encode(), data, {"engine": "vision", "test_runtime": "mocked"}


@pytest.mark.parametrize("changes", [
    {"engine": "cloud"}, {"max_pixels": True}, {"max_pixels": 1_000_001},
    {"time_seconds": float("nan")}, {"time_seconds": True}, {"languages": ["--arbitrary"]},
    {"engine": "tesseract", "detect_barcodes": True}, {"max_matches": False},
])
def test_request_rejects_invalid_engine_flags_and_bounds(changes):
    with pytest.raises(ValueError):
        ImageOCRRequest.model_validate({"file_path": "/owned.png", "engine": "vision", **changes})


def test_tsv_words_lines_cjk_join_casefold_and_exact_match_denominator():
    values = parse_tsv(tsv(["你", "好", "HELLO", "hello"]))
    assert [value["text"] for value in values if value["kind"] == "word"] == ["你", "好", "HELLO", "hello"]
    assert values[-1]["text"] == "你好 HELLO hello" and values[-1]["confidence"] is None
    matches, total = locate_text(values, "hello", 1)
    assert total == 2 and len(matches) == 1
    assert matches[0]["observation_index"] == 4
    assert matches[0]["geometry_scope"] == "whole_line_observation"
    assert locate_text(values, "你好", 3)[1] == 1


@pytest.mark.parametrize("raw", [
    b"bad header\n", (HEADER + "5\t1\n").encode(), tsv(["x"]) + b"extra\trow\n",
    tsv(["x"]).replace(b"\t95\t", b"\tnan\t"), tsv(["x"]).replace(b"\t95\t", b"\t101\t"),
    b"a" * (256 * 1024 + 1), tsv(["word"] * 129),
])
def test_tsv_rejects_malformed_nonfinite_and_overfull_payload(raw):
    with pytest.raises((ValueError, KeyError)):
        parse_tsv(raw)


async def test_missing_tesseract_has_no_preparation_or_model_fallback():
    with patch("video_research_mcp.image_ocr.shutil.which", return_value=None), patch(
        "video_research_mcp.image_edit.edit_image", new_callable=AsyncMock
    ) as prepare:
        with pytest.raises(ImportError, match="optional installed Tesseract"):
            await recognize_image(ImageOCRRequest(file_path="/absent.png", engine="tesseract"))
    prepare.assert_not_awaited()


async def test_one_tesseract_tsv_invocation_and_exact_raw_manifest(tmp_path):
    from PIL import Image
    from video_research_mcp.image_manifest import read_manifest

    source = tmp_path / "owned.png"
    Image.new("RGB", (100, 80), "white").save(source)
    raw = tsv(["HELLO", "hello"])
    with patch("video_research_mcp.image_ocr.shutil.which", return_value="/owned/tesseract"), patch(
        "video_research_mcp.image_ocr.run_media_process", new=AsyncMock(return_value=(raw, b""))
    ) as process:
        result = await recognize_image(ImageOCRRequest(
            file_path=str(source), engine="tesseract", languages=["eng"], locate="hello", max_matches=1
        ))
    assert process.await_count == 1
    command = process.await_args.args[0]
    assert command[0] == "/owned/tesseract" and command[2:] == ["stdout", "--psm", "6", "-l", "eng", "tsv"]
    assert result["match_count"] == 2 and result["matches_truncated"]
    assert Path(result["raw_backend_artifact"]["path"]).read_bytes() == raw
    assert result["runtime"]["version"] == "unverified"
    readback = await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])
    assert readback["observations"] == result["observations"] and readback["verified"]


async def test_actual_exif_crop_resize_inverse_and_separate_ocr_manifest(tmp_path):
    """GIVEN EXIF6 plus crop/resize WHEN native points map THEN both original pixel grids are retained."""
    from PIL import Image
    from video_research_mcp.image_manifest import read_manifest

    source = tmp_path / "owned.jpg"
    image = Image.new("RGB", (100, 200), "white")
    exif = image.getexif()
    exif[274] = 6
    image.save(source, exif=exif)
    original = source.read_bytes()
    with patch("video_research_mcp.image_ocr.run_vision", new=AsyncMock(
        return_value=native_payload(200, 120)
    )):
        result = await recognize_image(ImageOCRRequest(
            file_path=str(source), engine="vision", expected_source_sha256=hashlib.sha256(original).hexdigest(),
            crop={"coordinates": [20, 10, 100, 60]}, resize={"width": 200, "height": 120}, locate="owned"
        ))
    value = result["observations"][0]
    assert value["prepared_points"] == [[50, 30], [150, 30], [150, 90], [50, 90]]
    assert value["oriented_points"] == [[45, 25], [95, 25], [95, 55], [45, 55]]
    assert value["stored_points"] == [[25, 155], [25, 105], [55, 105], [55, 155]]
    assert result["source"]["exif_orientation"] == 6 and source.read_bytes() == original
    assert result["manifest"]["path"] != result["preparation"]["manifest"]["path"]
    assert result["provenance"]["semantic_table_structure"] == "unknown"
    readback = await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])
    assert readback["observations"] == result["observations"]
    Path(result["raw_backend_artifact"]["path"]).write_bytes(b"later changed raw result")
    with pytest.raises(ValueError, match="identity changed"):
        await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])


@pytest.mark.parametrize("kind", ["malformed", "overpixel", "symlink", "unsupported"])
async def test_invalid_static_sources_reject_before_ocr(tmp_path, kind):
    from PIL import Image

    source = tmp_path / "owned.png"
    Image.new("RGB", (1, 1), "white").save(source)
    if kind == "malformed":
        source.write_bytes(b"invalid PNG")
    elif kind == "overpixel":
        data = bytearray(source.read_bytes())
        data[16:24] = struct.pack(">II", 4000, 3000)
        data[29:33] = struct.pack(">I", zlib.crc32(data[12:29]))
        source.write_bytes(data)
    elif kind == "symlink":
        other = tmp_path / "linked.png"
        other.symlink_to(source)
        source = other
    else:
        source = tmp_path / "unsupported.svg"
        source.write_text("<svg/>")
    with patch("video_research_mcp.image_ocr.run_vision", new_callable=AsyncMock) as engine:
        with pytest.raises((ValueError, OSError)):
            await recognize_image(ImageOCRRequest(file_path=str(source), engine="vision"))
    engine.assert_not_awaited()


async def test_ocr_timeout_cleans_preparation_and_its_owned_stage(tmp_path):
    from PIL import Image
    from video_research_mcp.config import update_config

    source = tmp_path / "owned.png"
    Image.new("RGB", (20, 20), "white").save(source)
    update_config(media_acquire_timeout_seconds=1)

    async def delayed(*args):
        await asyncio.sleep(2)

    with patch("video_research_mcp.image_ocr.run_vision", side_effect=delayed):
        with pytest.raises(TimeoutError):
            await recognize_image(ImageOCRRequest(file_path=str(source), engine="vision"))
    assert source.exists()
    paths = list((tmp_path / "cache" / "media" / "views").glob("*"))
    assert paths == []


async def test_source_mutation_during_ocr_cannot_publish_manifest(tmp_path):
    from PIL import Image

    source = tmp_path / "owned.png"
    Image.new("RGB", (100, 80), "white").save(source)

    async def changed_source(*args):
        source.write_bytes(b"later source edit")
        return native_payload(100, 80)

    with patch("video_research_mcp.image_ocr.run_vision", side_effect=changed_source):
        with pytest.raises(ValueError, match="identity changed"):
            await recognize_image(ImageOCRRequest(file_path=str(source), engine="vision"))
    assert source.read_bytes() == b"later source edit"
    assert not list((tmp_path / "cache" / "media" / "views").rglob("ocr-raw.*"))


async def test_changed_prepared_bytes_block_before_engine(tmp_path):
    from PIL import Image
    from video_research_mcp.image_edit import edit_image

    source = tmp_path / "owned.png"
    Image.new("RGB", (100, 80), "white").save(source)

    async def changed_prepared(request):
        prepared = await edit_image(request)
        Path(prepared["artifact"]["path"]).write_bytes(b"substituted prepared bytes")
        return prepared

    with patch("video_research_mcp.image_edit.edit_image", side_effect=changed_prepared), patch(
        "video_research_mcp.image_ocr.run_vision", new_callable=AsyncMock
    ) as engine:
        with pytest.raises(ValueError, match="differs"):
            await recognize_image(ImageOCRRequest(file_path=str(source), engine="vision"))
    engine.assert_not_awaited()


def test_native_outside_or_malformed_points_reject_before_mapping():
    preparation = {"artifact": {"width": 100, "height": 100}, "transforms": {
        "oriented_to_output": [[1,0,0],[0,1,0],[0,0,1]],
        "output_to_source": [[1,0,0],[0,1,0],[0,0,1]],
    }}
    value = native_payload(100, 100)[1]["observations"][0]
    value["raw_points"][0][0] = 1.1
    with pytest.raises(ValueError, match="outside"):
        map_observation(value, preparation, native=True)
