"""Exact-byte bounded image editing journeys through the public engine contract."""

import hashlib
from pathlib import Path

import pytest
from PIL import Image

from video_research_mcp.image_edit import edit_image
from video_research_mcp.image_manifest import read_manifest
from video_research_mcp.models.image_edit import ImageEditRequest


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@pytest.fixture(autouse=True)
def isolate_image_views(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


@pytest.fixture
def owned_image(tmp_path):
    path = tmp_path / "original.png"
    image = Image.new("RGBA", (20, 12), (10, 20, 30, 128))
    image.putpixel((3, 4), (250, 0, 0, 255))
    image.save(path)
    return path


async def test_default_prepare_preserves_pixels_and_verifies_manifest(owned_image):
    before = owned_image.read_bytes()
    result = await edit_image(ImageEditRequest(file_path=str(owned_image)))
    with Image.open(result["artifact"]["path"]) as output:
        assert output.size == (20, 12) and output.getpixel((3, 4)) == (250, 0, 0, 255)
        assert output.getpixel((0, 0)) == (10, 20, 30, 128)
    assert result["artifact"]["sha256"] == digest(result["artifact"]["path"])
    assert result["source"]["sha256"] == hashlib.sha256(before).hexdigest()
    assert result["source"]["stored_width"] == result["source"]["oriented_width"] == 20
    assert result["transforms"]["output_to_source"] == [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert result["artifacts"] == [result["artifact"]] and result["frame"] is None
    restored = await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])
    assert restored["verified"] and restored["artifact"] == result["artifact"]
    assert owned_image.read_bytes() == before
    assert not list(Path(result["artifact"]["path"]).parent.glob("source.*"))


async def test_all_annotation_kinds_and_automatic_closeups(tmp_path):
    source = tmp_path / "labels.png"
    Image.new("RGBA", (160, 96), "white").save(source)
    annotations = [
        {"kind": "box", "coordinates": [10, 10, 40, 30]},
        {"kind": "circle", "space": "normalized1000", "coordinates": [375, 100, 562.5, 312.5]},
        {"kind": "arrow", "coordinates": [10, 60, 60, 60]},
        {"kind": "number", "coordinates": [110, 30], "text": "3", "font_size": 12},
        {"kind": "text", "coordinates": [10, 75], "text": "TAG", "font_size": 12}]
    result = await edit_image(ImageEditRequest(file_path=str(source), annotations=annotations))
    assert len(result["artifacts"]) == 3
    with Image.open(result["artifact"]["path"]) as output:
        assert output.getpixel((10, 10))[:3] == (229, 57, 53)
        assert output.getpixel((60, 60))[:3] == (229, 57, 53)
        assert output.getpixel((110, 23))[:3] == (229, 57, 53)
    closeup = result["artifacts"][1]
    assert closeup["role"] == "closeup" and closeup["annotation_index"] == 0
    assert closeup["output_box"] == [7, 8, 43, 32]
    assert closeup["output_to_source"] == [[1, 0, 7], [0, 1, 8], [0, 0, 1]]


@pytest.mark.parametrize("orientation,rows", [
    (2, [[2, 1, 0], [5, 4, 3]]), (3, [[5, 4, 3], [2, 1, 0]]),
    (4, [[3, 4, 5], [0, 1, 2]]), (5, [[0, 3], [1, 4], [2, 5]]),
    (6, [[3, 0], [4, 1], [5, 2]]), (7, [[5, 2], [4, 1], [3, 0]]),
    (8, [[2, 5], [1, 4], [0, 3]])])
async def test_exif_2_to_8_pixels_and_inverse_stored_geometry(tmp_path, orientation, rows):
    source = tmp_path / "orientation.png"
    image = Image.new("RGB", (3, 2))
    for index in range(6):
        image.putpixel((index % 3, index // 3), (index * 30, 10, 20))
    exif = Image.Exif()
    exif[274] = orientation
    image.save(source, exif=exif)
    result = await edit_image(ImageEditRequest(file_path=str(source)))
    with Image.open(result["artifact"]["path"]) as output:
        assert output.size == (len(rows[0]), len(rows))
        for y, row in enumerate(rows):
            for x, index in enumerate(row):
                assert output.getpixel((x, y))[0] == index * 30
                matrix = result["transforms"]["output_to_source"]
                stored_x = matrix[0][0] * (x + 0.5) + matrix[0][1] * (y + 0.5) + matrix[0][2]
                stored_y = matrix[1][0] * (x + 0.5) + matrix[1][1] * (y + 0.5) + matrix[1][2]
                assert (int(stored_x), int(stored_y)) == (index % 3, index // 3)
        assert not output.getexif()
    assert result["source"]["exif_orientation"] == orientation


@pytest.mark.parametrize("crop", [
    {"space": "pixel", "coordinates": [2, 2, 10, 8]},
    {"space": "normalized1000", "coordinates": [100, 166.666666667, 600, 833.333333333]}])
async def test_crop_resize_retains_exact_forward_inverse_and_roundtrip(owned_image, crop):
    request = ImageEditRequest(file_path=str(owned_image), crop=crop, resize={"width": 5, "height": 4})
    request = ImageEditRequest.model_validate(request.model_dump(mode="json"))
    result = await edit_image(request)
    assert result["provenance"]["crop_xywh"] == [2, 2, 10, 8]
    assert result["transforms"]["source_to_output"] == [[0.5, 0, -1], [0, 0.5, -1], [0, 0, 1]]
    assert result["transforms"]["output_to_source"] == [[2, 0, 2], [0, 2, 2], [0, 0, 1]]
    assert (result["artifact"]["width"], result["artifact"]["height"]) == (5, 4)


@pytest.mark.parametrize("format,mime", [("png", "image/png"), ("jpeg", "image/jpeg"),
    ("webp", "image/webp"), ("bmp", "image/bmp"), ("gif", "image/gif")])
async def test_actual_five_output_encoders_and_transparency_boundary(owned_image, format, mime):
    result = await edit_image(ImageEditRequest(file_path=str(owned_image), output_format=format, quality=75))
    with Image.open(result["artifact"]["path"]) as output:
        assert output.format == format.upper() and output.size == (20, 12)
        if format in {"png", "webp"}:
            assert output.convert("RGBA").getpixel((0, 0))[3] == 128
        elif format in {"jpeg", "bmp"}:
            assert output.mode == "RGB" and any("flattened" in note for note in result["warnings"])
        else:
            assert output.mode == "P" and any("one bit" in note for note in result["warnings"])
    assert result["artifact"]["mime"] == mime
    assert result["artifact"]["sha256"] == digest(result["artifact"]["path"])


async def test_optional_exif_is_bounded_and_profiles_are_explicitly_stripped(tmp_path):
    source = tmp_path / "metadata.png"
    exif = Image.Exif()
    exif[270] = "A" * 1000
    exif[34853] = {1: "N", 2: (1, 2, 3)}
    profile = b"owned uninterpreted ICC metadata"
    Image.new("RGB", (12, 12), "blue").save(source, exif=exif, icc_profile=profile)
    without = await edit_image(ImageEditRequest(file_path=str(source)))
    result = await edit_image(ImageEditRequest(file_path=str(source), include_exif=True))
    assert without["source"]["exif_tags"] == []
    assert result["source"]["exif_truncated"] and result["source"]["exif_gps_present"]
    assert len(next(t["value"] for t in result["source"]["exif_tags"] if t["tag"] == 270)) == 256
    assert result["source"]["icc_profile_sha256"] == hashlib.sha256(profile).hexdigest()
    assert any("GPS" in note for note in result["warnings"])
    with Image.open(result["artifact"]["path"]) as output:
        assert "icc_profile" not in output.info and not output.getexif()


async def test_unsupported_font_glyph_is_reported_without_literal_claim(tmp_path):
    source = tmp_path / "font.png"
    Image.new("RGB", (160, 96), "white").save(source)
    result = await edit_image(ImageEditRequest(file_path=str(source), annotations=[
        {"kind": "text", "coordinates": [5, 5], "text": "中文", "font_size": 12}]))
    assert any("unsupported glyphs" in note and "not literal text verification" in note for note in result["warnings"])
    assert result["provenance"]["output_class"] == "source_annotated_image"
