"""Native still image view validation."""

import struct
import shutil
import zlib
from unittest.mock import AsyncMock

import pytest


async def test_image_pixel_limit_fails_before_source_read():
    from video_research_mcp.media_image_read import read_image

    with pytest.raises(ValueError, match="max_pixels"):
        await read_image("/missing.png", max_pixels=1_000_001)


def test_non_square_video_geometry_requires_normalized_source():
    from video_research_mcp.media_image_read import geometry

    source = {"display_width": 160, "display_height": 96,
              "display_geometry_supported": False, "sample_aspect_ratio": "2:1"}
    with pytest.raises(ValueError, match="square"):
        geometry(source, 1_000_000, [0, 0, 100, 50])


def make_png(path, width=32, height=24):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    rows = b"".join(b"\0" + bytes([32, 128, 224]) * width for _ in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


@pytest.fixture
def native_env(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    path = tmp_path / "original.png"
    make_png(path)
    return path


@pytest.mark.parametrize("extension", ["png", "jpg", "webp", "bmp", "gif", "tiff"])
async def test_actual_owned_native_still_formats_have_no_video_pts(native_env, extension):
    from video_research_mcp.media_image_read import read_image
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    path = native_env
    if extension != "png":
        path = native_env.with_name("converted." + extension)
        if extension == "webp":
            encoder = shutil.which("cwebp")
            if not encoder:
                pytest.skip("Owned WebP fixture encoding requires separately installed cwebp")
            command = [encoder, "-quiet", "-lossless", str(native_env), "-o", str(path)]
        else:
            command = [binary("ffmpeg"), "-v", "error", "-nostdin", "-y",
                       "-threads", "1", "-i", str(native_env), "-frames:v", "1",
                       "-threads", "1", str(path)]
        await run_media_process(command, 5)
    before = path.read_bytes()
    result = await read_image(str(path), max_pixels=200)
    frame = result["frames"][0]
    assert frame["width"] * frame["height"] <= 200
    assert frame["actual_seconds"] is None
    assert frame["original_pts"] is None
    assert frame["time_base"] is None
    assert frame["requested_seconds"] is None
    assert result["source"]["duration_seconds"] is None
    assert result["source"]["stream_index"] is None
    assert result["coverage"]["sampled_points"] == []
    assert result["coverage"]["watched_intervals"] == []
    assert result["limits"]["animation_traversed"] is False
    assert path.read_bytes() == before


async def test_oversized_header_is_rejected_before_render(native_env, monkeypatch):
    from video_research_mcp import media_image_read, media_probe

    probe = AsyncMock(return_value=(b'{"streams": [{"codec_type": "video", "width": 4000, "height": 3000}], "format": {}}', b""))
    render = AsyncMock()
    monkeypatch.setattr(media_probe, "run_media_process", probe)
    monkeypatch.setattr(media_image_read, "run_media_process", render)
    with pytest.raises(ValueError, match="8 megapixel"):
        await media_image_read.read_image(str(native_env))
    assert probe.await_count == 1
    render.assert_not_awaited()


async def test_frame_mutation_fails_sheet_before_native_composition(native_env, monkeypatch):
    from pathlib import Path
    from video_research_mcp import media_frame_views
    from video_research_mcp.media_image_read import read_image

    result = await read_image(str(native_env))
    frame = result["frames"][0]
    Path(frame["path"]).write_bytes(native_env.read_bytes() + b"tampered")
    before_dirs = set(Path(frame["path"]).parent.parent.iterdir())
    render = AsyncMock()
    monkeypatch.setattr(media_frame_views, "run_media_process", render)
    with pytest.raises(ValueError, match="changed"):
        await media_frame_views.contact_sheet(result)
    render.assert_not_awaited()
    assert set(Path(frame["path"]).parent.parent.iterdir()) == before_dirs


async def test_actual_still_sheet_maps_original_digest_without_temporal_labels(native_env):
    from video_research_mcp.media_frame_views import contact_sheet
    from video_research_mcp.media_image_read import read_image

    result = await read_image(str(native_env))
    sheet = await contact_sheet(result)
    assert sheet["tiles"][0]["source_frame_sha256"] == result["frames"][0]["sha256"]
    assert sheet["tiles"][0]["actual_seconds"] is None
    assert sheet["tiles"][0]["original_pts"] is None
    assert sheet["coverage"] == result["coverage"]
    assert sheet["artifact"]["width"] == 32
    assert sheet["artifact"]["height"] == 24
