"""Explicit alpha holes and conservative bounded seeded-background cutouts."""

import hashlib
import pytest
from PIL import Image, ImageDraw

from video_research_mcp.image_edit import edit_image
from video_research_mcp.models.image_edit import ImageEditRequest


@pytest.fixture(autouse=True)
def isolate_image_views(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


async def test_polygon_hole_retains_actual_alpha_mask_and_crop_offset(tmp_path):
    source = tmp_path / "rings.png"
    Image.new("RGBA", (20, 12), (20, 40, 60, 128)).save(source)
    rings = [[(2, 2), (14, 2), (14, 10), (2, 10)], [(6, 4), (10, 4), (10, 8), (6, 8)]]
    result = await edit_image(ImageEditRequest(file_path=str(source),
        cutout={"method": "polygon", "rings": rings}))
    assert result["cutout"]["crop_offset"] == [2, 2]
    assert result["artifact"]["width"] == 13 and result["artifact"]["height"] == 9
    mask_record = result["artifacts"][1]
    assert mask_record["role"] == "alpha_mask"
    with Image.open(result["artifact"]["path"]) as output, Image.open(mask_record["path"]) as mask:
        assert output.getpixel((0, 0))[3] == mask.getpixel((0, 0)) == 128
        assert output.getpixel((5, 4))[3] == mask.getpixel((5, 4)) == 0
        assert result["cutout"]["alpha_bytes_sha256"] == hashlib.sha256(mask.tobytes()).hexdigest()
    assert result["cutout"]["mask_sha256"] == mask_record["sha256"]
    assert result["transforms"]["output_to_source"] == [[1, 0, 2], [0, 1, 2], [0, 0, 1]]
    assert result["cutout"]["polygon_replay_verified"] is False


async def test_seeded_background_flood_keeps_exact_foreground_pixels(tmp_path):
    source = tmp_path / "flood.png"
    image = Image.new("RGB", (40, 30), "white")
    ImageDraw.Draw(image).rectangle((10, 8, 29, 21), fill="red")
    image.save(source)
    result = await edit_image(ImageEditRequest(file_path=str(source),
        cutout={"method": "flood", "seed": [0, 0], "tolerance": 26}))
    with Image.open(result["artifact"]["path"]) as output:
        assert output.size == (20, 14) and output.getpixel((0, 0)) == (255, 0, 0, 255)
    assert result["cutout"]["crop_offset"] == [10, 8]
    assert result["cutout"]["foreground_components"] == 1
    assert result["cutout"]["algorithm"] == "four_connected_seed_L1_RGB_complement"
    assert result["cutout"]["morphology_or_component_removal"] is False


async def test_thin_multiple_components_are_retained_with_conservative_warnings(tmp_path):
    source = tmp_path / "specks.png"
    image = Image.new("RGB", (30, 30), "white")
    for x in range(2, 26, 4):
        image.putpixel((x, 15), (255, 0, 0))
    image.save(source)
    result = await edit_image(ImageEditRequest(file_path=str(source),
        cutout={"method": "flood", "seed": [0, 0], "crop_to_bbox": False}))
    assert result["cutout"]["foreground_components"] == 6
    assert any("all components are retained" in note for note in result["warnings"])
    assert any("coverage is extreme" in note for note in result["warnings"])
    with Image.open(result["artifact"]["path"]) as output:
        assert sum(pixel[3] > 0 for pixel in output.get_flattened_data()) == 6


async def test_wrong_seed_reports_border_ambiguity(tmp_path):
    source = tmp_path / "wrong-seed.png"
    image = Image.new("RGB", (40, 30), "white")
    ImageDraw.Draw(image).rectangle((10, 8, 29, 21), fill="red")
    image.save(source)
    result = await edit_image(ImageEditRequest(file_path=str(source),
        cutout={"method": "flood", "seed": [15, 10]}))
    assert result["cutout"]["border_inside_fraction"] == 1
    assert any("seed may identify foreground" in note for note in result["warnings"])


@pytest.mark.parametrize("color,match", [("white", "no foreground"), ((255, 255, 255, 128), "opaque")])
async def test_difficult_background_refusal_preserves_original_and_cleans_staging(tmp_path, color, match):
    source = tmp_path / "ambiguous.png"
    Image.new("RGBA", (20, 12), color).save(source)
    before = source.read_bytes()
    with pytest.raises(ValueError, match=match):
        await edit_image(ImageEditRequest(file_path=str(source), cutout={"method": "flood", "seed": [0, 0]}))
    assert source.read_bytes() == before
    assert not list((tmp_path / "cache" / "media" / "views").glob("*"))
