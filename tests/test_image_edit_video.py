"""Owned FFmpeg source clocks, rotated original grids and bounded frame edits."""

from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from video_research_mcp.image_edit import edit_image
from video_research_mcp.media_probe import binary
from video_research_mcp.media_process import run_media_process
from video_research_mcp.models.image_edit import ImageEditRequest


@pytest.fixture(autouse=True)
def isolate_image_views(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


async def test_rotated_video_downscale_crop_uses_original_grid_and_actual_pts(tmp_path):
    still, video, rotated = (tmp_path / name for name in ("quadrants.png", "source.mp4", "rotated.mp4"))
    image = Image.new("RGB", (160, 96), "red")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 0, 159, 47), fill=(0, 255, 0))
    draw.rectangle((0, 48, 79, 95), fill="blue")
    draw.rectangle((80, 48, 159, 95), fill="yellow")
    image.save(still)
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-loop", "1",
        "-i", str(still), "-t", "0.4", "-r", "10", "-an", "-c:v", "libx264",
        "-pix_fmt", "yuv420p", "-threads", "1", str(video)], 10)
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-display_rotation", "90",
        "-i", str(video), "-c", "copy", str(rotated)], 10)
    before = rotated.read_bytes()
    result = await edit_image(ImageEditRequest(file_path=str(rotated), time_seconds=0.15,
        crop={"coordinates": [10, 20, 60, 100]}, max_pixels=800))
    source, frame = result["source"], result["frame"]
    assert (source["stored_width"], source["stored_height"]) == (160, 96)
    assert (source["oriented_width"], source["oriented_height"]) == (96, 160)
    assert source["rotation_degrees"] == 90 and source["native_crop_xywh"] == [10, 20, 60, 100]
    assert (frame["decoded_width"], frame["decoded_height"]) == (21, 36)
    assert frame["requested_seconds"] == 0.15 and frame["actual_seconds"] == pytest.approx(0.2)
    assert float(frame["original_pts"] * Fraction(frame["time_base"])) - source["container_start_seconds"] == pytest.approx(0.2)
    assert result["transforms"]["stored_to_oriented"] == [[0, 1, 0], [-1, 0, 160], [0, 0, 1]]
    assert result["transforms"]["oriented_to_output"][0] == pytest.approx([0.35, 0, -3.5])
    assert result["transforms"]["oriented_to_output"][1] == pytest.approx([0, 0.36, -7.2])
    with Image.open(result["artifact"]["path"]) as output:
        assert output.size == (21, 36)
        top, bottom = output.getpixel((1, 1)), output.getpixel((1, 34))
        assert top[1] > 200 and top[0] < 30 and bottom[0] > 200 and bottom[1] < 30
    assert rotated.read_bytes() == before and result["provenance"]["output_class"] == "extracted_source_frame"
    assert not list(Path(result["artifact"]["path"]).parent.glob("decoded.*"))
