"""Native frame behavior against frozen original development media, never heldout."""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
from fractions import Fraction
import shutil

import pytest
import pytest_asyncio

from tests.native_media_fixtures import (
    CROP, build_fixtures, crop_pixels, decoded_rgb, digest, frame_index, frame_pixels, rotate_ccw,
)


def capture_result(name, result):
    """Optionally retain exact development outputs for the coordinator's inspection."""
    directory = os.getenv("NATIVE_MEDIA_RESULT_DIR")
    if not directory:
        return
    target = Path(directory) / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    artifacts = result.get("frames", []) + ([result["artifact"]] if "artifact" in result else [])
    for index, artifact in enumerate(artifacts):
        shutil.copyfile(artifact["path"], target / f"artifact-{index}.png")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def corpus(tmp_path_factory):
    """Freeze fixture labels before the first candidate operation in this module."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Native fixture integration requires independently installed FFmpeg/ffprobe")
    retained = os.getenv("NATIVE_MEDIA_FIXTURE_MANIFEST")
    if retained:
        manifest = json.loads(Path(retained).read_text())
        for item in manifest["fixtures"].values():
            assert digest(Path(item["path"])) == item["sha256"]
        return manifest
    return await build_fixtures(tmp_path_factory.mktemp("original-native-media"))


@pytest.fixture(autouse=True)
def isolated_local_media(tmp_path, monkeypatch, clean_config, mock_weaviate_disabled):
    """Use isolated output storage and deny network/provider operations."""
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("LOCAL_FILE_ACCESS_ROOT", raising=False)

    def denied(*args, **kwargs):
        raise AssertionError("Native media fixtures must not call network or provider services")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr("video_research_mcp.client.GeminiClient.get", denied)


def assert_original(item, source):
    """The returned source commitment must match preserved original bytes."""
    assert source["sha256"] == item["sha256"]
    assert source["source_revision"] == "sha256:" + item["sha256"]
    assert source["bytes"] == Path(item["path"]).stat().st_size
    assert digest(Path(item["path"])) == item["sha256"]


@pytest.mark.parametrize("name", ["cfr", "vfr", "offset", "rotated"])
async def test_inspection_preserves_source_clock_rotation_audio(corpus, name):
    """Given known streams, metadata retains source clocks and display geometry."""
    from video_research_mcp.media_probe import inspect_media

    item = corpus["fixtures"][name]
    source = await inspect_media(item["path"])
    capture_result("metadata-" + name, source)
    assert_original(item, source)
    assert source["stored_width"] == 160
    assert source["stored_height"] == 96
    assert source["container_start_seconds"] == pytest.approx(item["offset_ms"] / 1000)
    video = next(stream for stream in item["oracle"]["streams"] if stream["codec_type"] == "video")
    assert source["time_base"] == video["time_base"]
    if name == "rotated":
        assert source["rotation_degrees"] == 90
        assert (source["display_width"], source["display_height"]) == (96, 160)
        audio = next(stream for stream in source["streams"] if stream["codec_type"] == "audio")
        assert int(audio["sample_rate"]) == 8000
        assert audio["channels"] == 1
    else:
        assert source["rotation_degrees"] == 0
        assert (source["display_width"], source["display_height"]) == (160, 96)
        assert not any(stream["codec_type"] == "audio" for stream in source["streams"])
    assert source["duration_seconds"] > item["frame_ms"][-1] / 1000
    assert source["duration_seconds"] < 1.5


def assert_frame_binding(item, source, frame):
    """Compare reported time/identity to the frozen independently probed frame."""
    frames = [value for value in item["oracle"]["frames"] if value["media_type"] == "video"]
    ordinal = item["frame_ms"].index(round(frame["actual_seconds"] * 1000))
    assert frame["original_pts"] == frames[ordinal]["pts"]
    video = next(stream for stream in item["oracle"]["streams"] if stream["codec_type"] == "video")
    assert Fraction(frame["time_base"]) == Fraction(video["time_base"])
    original_seconds = frame["original_pts"] * Fraction(frame["time_base"])
    assert float(original_seconds) == pytest.approx(frame["actual_seconds"] + source["container_start_seconds"])
    assert frame["sha256"] == digest(Path(frame["path"]))
    assert frame["bytes"] == Path(frame["path"]).stat().st_size
    assert_original(item, source)
    return ordinal


@pytest.mark.parametrize("name,actual", [("cfr", 0.2), ("vfr", 0.28), ("offset", 0.2)])
async def test_precise_frame_reports_original_pts_and_visible_index(corpus, name, actual):
    """A non-frame request returns a real following source frame with honest delta."""
    from video_research_mcp.media_frames import frame_at

    item = corpus["fixtures"][name]
    result = await frame_at(item["path"], time_seconds=0.15)
    capture_result("precise-" + name, result)
    assert len(result["frames"]) == 1
    frame = result["frames"][0]
    assert frame["requested_seconds"] == 0.15
    assert frame["actual_seconds"] == pytest.approx(actual)
    assert frame["delta_seconds"] == pytest.approx(actual - 0.15)
    assert frame["approximate"] is False
    ordinal = assert_frame_binding(item, result["source"], frame)
    pixels = await decoded_rgb(Path(frame["path"]))
    assert frame_index(pixels, frame["width"]) == ordinal
    if name != "vfr":
        assert pixels == frame_pixels(ordinal)
    assert result["coverage"]["watched_intervals"] == []


@pytest.mark.parametrize("name", ["cfr", "vfr"])
async def test_window_sampling_contains_only_real_in_window_frames(corpus, name):
    """Window samples preserve distinct original frame points within exact bounds."""
    from video_research_mcp.media_frames import sample_frames

    item = corpus["fixtures"][name]
    result = await sample_frames(item["path"], start_seconds=0.11, end_seconds=0.95,
                                 fps=8, max_frames=6, max_pixels=160 * 96)
    capture_result("window-" + name, result)
    assert 1 < len(result["frames"]) <= 6
    points = [frame["actual_seconds"] for frame in result["frames"]]
    assert points == sorted(set(points))
    assert all(0.11 <= point < 0.95 for point in points)
    assert result["coverage"]["sampled_points"] == points
    assert result["coverage"]["decoded_count"] == len(points)
    assert result["coverage"]["requested_window"] == {"start_seconds": 0.11, "end_seconds": 0.95}
    assert result["limits"]["requested_fps"] == 8
    assert result["limits"]["effective_frame_limit"] <= 6
    assert sum(frame["bytes"] for frame in result["frames"]) <= result["limits"]["max_artifact_bytes"]
    for frame in result["frames"]:
        ordinal = assert_frame_binding(item, result["source"], frame)
        assert frame["width"] * frame["height"] <= 160 * 96
        assert frame_index(await decoded_rgb(Path(frame["path"])), frame["width"]) == ordinal
    assert result["coverage"]["watched_intervals"] == []


async def cropped_burst(corpus):
    """Request the known 400 ms window with a 200 ms authored text/state change."""
    from video_research_mcp.media_frames import sample_frames

    return await sample_frames(corpus["fixtures"]["cfr"]["path"], start_seconds=0.4,
                               end_seconds=0.8, fps=10, max_frames=4, max_pixels=96 * 24,
                               crop_box=CROP)


async def test_crop_burst_preserves_brief_bitmap_text_change(corpus):
    """The crop shows the authored OFF/ON/OFF transition below one second."""
    item = corpus["fixtures"]["cfr"]
    result = await cropped_burst(corpus)
    capture_result("brief-crop", result)
    assert [round(frame["actual_seconds"] * 1000) for frame in result["frames"]] == [400, 500, 600, 700]
    for frame in result["frames"]:
        ordinal = assert_frame_binding(item, result["source"], frame)
        assert frame["crop_box"] == CROP
        assert (frame["width"], frame["height"]) == (96, 24)
        assert await decoded_rgb(Path(frame["path"])) == crop_pixels(frame_pixels(ordinal), 160, CROP)
    assert result["frames"][0]["sha256"] != result["frames"][1]["sha256"]
    assert result["frames"][1]["sha256"] != result["frames"][3]["sha256"]
    assert result["coverage"]["watched_intervals"] == []


async def test_keyframe_selection_is_explicit_source_bound_approximation(corpus):
    """Indexed keyframe selection exposes its approximation and actual source clock."""
    from video_research_mcp.media_frames import frame_at

    item = corpus["fixtures"]["cfr"]
    result = await frame_at(item["path"], time_seconds=0.45, selection="keyframe")
    capture_result("keyframe", result)
    frame = result["frames"][0]
    assert_frame_binding(item, result["source"], frame)
    assert frame["requested_seconds"] == 0.45
    assert frame["approximate"] is True
    assert frame["selection_method"] == "nearest_of_first_two_keyframes_after_index_seek"
    keys = [float(value["pts_time"]) for value in item["oracle"]["frames"] if value.get("key_frame") == 1]
    assert frame["actual_seconds"] in keys
    assert frame["delta_seconds"] == pytest.approx(frame["actual_seconds"] - 0.45)


@pytest.mark.parametrize("columns", [2, 4])
async def test_contact_sheet_maps_every_tile_to_original_frame_and_pixels(corpus, columns):
    """A sheet or filmstrip retains clock, source-frame hash and exact crop pixels."""
    from video_research_mcp.media_frame_views import contact_sheet

    burst = await cropped_burst(corpus)
    sheet = await contact_sheet(burst, columns=columns)
    capture_result("brief-contact-sheet-" + str(columns), sheet)
    artifact = sheet["artifact"]
    assert (artifact["width"], artifact["height"]) == (96 * columns, 24 * (4 // columns))
    assert artifact["sha256"] == digest(Path(artifact["path"]))
    pixels = await decoded_rgb(Path(artifact["path"]))
    assert len(sheet["tiles"]) == 4
    for index, tile in enumerate(sheet["tiles"]):
        frame = burst["frames"][index]
        assert tile["frame_index"] == index
        assert tile["actual_seconds"] == frame["actual_seconds"]
        assert tile["original_pts"] == frame["original_pts"]
        assert tile["time_base"] == frame["time_base"]
        assert tile["source_frame_sha256"] == frame["sha256"]
        assert (tile["x"], tile["y"], tile["width"], tile["height"]) == (index % columns * 96, index // columns * 24, 96, 24)
        actual = crop_pixels(pixels, 96 * columns, [tile["x"], tile["y"], 96, 24])
        assert actual == await decoded_rgb(Path(frame["path"]))
    assert sheet["coverage"] == burst["coverage"]


async def test_rotation_display_crop_matches_original_stored_pixel_transform(corpus):
    """Rotation changes display coordinates while preserving original source identity."""
    from video_research_mcp.media_frames import frame_at

    item = corpus["fixtures"]["rotated"]
    result = await frame_at(item["path"], time_seconds=0.2)
    capture_result("rotation-display", result)
    frame = result["frames"][0]
    ordinal = assert_frame_binding(item, result["source"], frame)
    assert (frame["width"], frame["height"]) == (96, 160)
    expected = rotate_ccw(frame_pixels(ordinal))
    assert await decoded_rgb(Path(frame["path"])) == expected
    box = [0, 0, 48, 80]
    cropped = await frame_at(item["path"], time_seconds=0.2, crop_box=box)
    capture_result("rotation-crop", cropped)
    assert_frame_binding(item, cropped["source"], cropped["frames"][0])
    assert await decoded_rgb(Path(cropped["frames"][0]["path"])) == crop_pixels(expected, 96, box)


async def test_native_image_read_preserves_authored_pixels_and_byte_identity(corpus):
    """A native image result remains bound to the owned original bitmap."""
    from video_research_mcp.media_image_read import read_image

    item = corpus["fixtures"]["image"]
    result = await read_image(item["path"], max_pixels=160 * 96)
    capture_result("image-read", result)
    assert_original(item, result["source"])
    frame = result["frames"][0]
    assert (frame["width"], frame["height"]) == (160, 96)
    assert frame["sha256"] == digest(Path(frame["path"]))
    assert await decoded_rgb(Path(frame["path"])) == frame_pixels(3)
    assert result["coverage"]["watched_intervals"] == []
