"""Independent original-pixel and actual-clock controls for prepared model vision."""

import asyncio
import base64
import io
import json
import os
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from PIL import Image

from tests.native_media_fixtures import (
    build_fixtures, crop_pixels, digest, frame_index, frame_pixels, rotate_ccw,
)
from video_research_mcp.config import update_config
from video_research_mcp.models.vision import VisionRequest
from video_research_mcp.vision_analysis import analyze_vision


@pytest.fixture(autouse=True)
def configured_vision(tmp_path, clean_config, monkeypatch):
    """Isolate preparations and select an owned HTTP-boundary mock profile."""
    monkeypatch.setenv("GEOMETRY_TEST_API_KEY", "owned-geometry-mock-key")
    update_config(cache_dir=str(tmp_path / "cache"), local_file_access_root="",
                  vision_backends={"geometry": {
                      "base_url": "http://127.0.0.1:8123/v1", "model": "owned-geometry-model",
                      "local": True, "api_key_env": "GEOMETRY_TEST_API_KEY",
                      "capabilities": ["images", "video", "structured_json"],
                  }})


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def fixed_media(tmp_path_factory):
    """Reuse frozen development fixtures or build their unchanged portable declaration once."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Native media checks require independently installed FFmpeg/ffprobe")
    if supplied := os.getenv("NATIVE_MEDIA_FIXTURE_MANIFEST"):
        path = Path(supplied)
        assert digest(path) == "e850edfe4da72f54ebf7b533dd715606998cd0d96aa4b0479af80d80bdfc60eb"
        manifest = json.loads(path.read_text())
    else:
        manifest = await build_fixtures(tmp_path_factory.mktemp("vision-geometry-media"))
    for record in manifest["fixtures"].values():
        assert digest(Path(record["path"])) == record["sha256"]
    return manifest["fixtures"]


def source(path, **values):
    """Commit source bytes before the workflow prepares or transmits them."""
    return {"file_path": str(path), "expected_source_sha256": digest(Path(path)), **values}


def grounding_request(path, **values):
    """Use a fixed normalized box response on declared local crop/resize inputs."""
    return VisionRequest(sources=[source(path, **values)], instruction="Locate the owned colored region",
                         backend="geometry", dry_run=False, authorize_submission=True, export_crops=True)


@pytest.fixture
def grounding_wire(monkeypatch):
    """Capture real compatible payload bytes and replace only the HTTP exchange boundary."""
    calls = []

    async def exchange(url, **values):
        assert url == "http://127.0.0.1:8123/v1/chat/completions"
        assert values["method"] == "POST" and values["local"] is True
        assert values["headers"]["Authorization"] == "Bearer owned-geometry-mock-key"
        calls.append(json.loads(values["content"]))
        answer = {"answer": "Owned mock region; object correctness unverified", "regions": [
            {"source_index": 0, "label": "owned region", "bbox": [250, 250, 750, 750]}]}
        return 200, json.dumps({"choices": [{"finish_reason": "stop", "message": {
            "content": json.dumps(answer)}}]}).encode()

    monkeypatch.setattr("video_research_mcp.vision_http.exchange", exchange)
    return calls


def prepared_wire_pixels(calls, result):
    """Bind captured prepared PNG bytes to the actual result commitment."""
    assert len(calls) == 1
    images = [part for part in calls[0]["messages"][0]["content"] if part["type"] == "image_url"]
    assert len(images) == 1
    encoded = base64.b64decode(images[0]["image_url"]["url"].split(",", 1)[1], validate=True)
    artifact = result["preparations"][0]["artifact"]
    assert encoded == Path(artifact["path"]).read_bytes()
    assert digest(Path(artifact["path"])) == result["payload_receipt"][0]["sha256"]
    return Image.open(io.BytesIO(encoded)).convert("RGB")


def rows(image):
    """Read deterministic pixels without using production transform functions."""
    return [[image.getpixel((x, y)) for x in range(image.width)] for y in range(image.height)]


@pytest.mark.parametrize("orientation, transform, stored_corners", [
    (6, Image.Transpose.ROTATE_270, [[7, 8], [7, 4], [13, 4], [13, 8]]),
    (8, Image.Transpose.ROTATE_90, [[13, 4], [13, 8], [7, 8], [7, 4]]),
])
async def test_exif_grounding_maps_prepared_box_to_oriented_and_stored_original_pixels(
        orientation, transform, stored_corners, tmp_path, grounding_wire):
    """EXIF rotation, declared crop/resize and model box map back to exact original pixels."""
    path = tmp_path / "owned-exif.png"
    stored = Image.new("RGB", (20, 12))
    for y in range(12):
        for x in range(20):
            stored.putpixel((x, y), (x * 10, y * 20, (x + y) * 5))
    exif = Image.Exif()
    exif[274] = orientation
    stored.save(path, exif=exif)
    original = path.read_bytes()
    result = await analyze_vision(grounding_request(path, crop={"coordinates": [2, 4, 8, 12]},
                                  resize={"width": 16, "height": 24}), "grounding")
    assert result["status"] == "complete"
    prepared = result["preparations"][0]
    assert prepared["source"]["exif_orientation"] == orientation
    assert (prepared["source"]["stored_width"], prepared["source"]["stored_height"]) == (20, 12)
    assert (prepared["source"]["oriented_width"], prepared["source"]["oriented_height"]) == (12, 20)
    with prepared_wire_pixels(grounding_wire, result) as transmitted:
        assert transmitted.size == (16, 24)
    region = result["regions"][0]
    assert region["prepared_corners"] == [[4, 6], [12, 6], [12, 18], [4, 18]]
    assert region["original_oriented_corners"] == [[4, 7], [8, 7], [8, 13], [4, 13]]
    assert region["original_stored_corners"] == stored_corners
    assert region["original_crop_xywh"] == [4, 7, 4, 6]
    expected = stored.transpose(transform).crop((4, 7, 8, 13))
    with Image.open(region["crop"]["artifact"]["path"]) as exported:
        assert rows(exported.convert("RGB")) == rows(expected)
    assert region["crop_parent"]["prepared_sha256"] == prepared["artifact"]["sha256"]
    assert region["crop"]["source"]["sha256"] == digest(path)
    assert region["crop_parent"]["pixel_extraction_verified"] is True
    assert region["object_correctness_verified"] is False
    assert result["provenance"]["human_review"] == "pending"
    assert path.read_bytes() == original


async def test_rotated_audio_frame_grounding_binds_actual_pts_and_original_display_crop(fixed_media, grounding_wire):
    """A .51 request selects actual .6 frame, then maps declared crop/resize back to original pixels."""
    path = Path(fixed_media["rotated"]["path"])
    result = await analyze_vision(grounding_request(path, kind="frame", time_seconds=0.51,
                                  crop={"coordinates": [36, 32, 24, 96]},
                                  resize={"width": 48, "height": 96}), "grounding")
    assert result["status"] == "complete"
    prepared = result["preparations"][0]
    frame = prepared["frame"]
    assert frame["requested_seconds"] == 0.51
    assert frame["actual_seconds"] == pytest.approx(0.6)
    assert frame["delta_seconds"] == pytest.approx(0.09)
    assert frame["original_pts"] == 6144 and frame["time_base"] == "1/10240"
    assert frame["approximate"] is False
    assert any(s["codec_type"] == "audio" for s in prepared["source"]["streams"])
    region = result["regions"][0]
    assert region["original_oriented_corners"] == [[42, 56], [54, 56], [54, 104], [42, 104]]
    assert region["original_stored_corners"] == [[104, 42], [104, 54], [56, 54], [56, 42]]
    assert region["original_crop_xywh"] == [42, 56, 12, 48]
    assert region["crop"]["frame"]["original_pts"] == frame["original_pts"]
    assert region["crop"]["frame"]["time_base"] == frame["time_base"]
    expected = crop_pixels(rotate_ccw(frame_pixels(6)), 96, [42, 56, 12, 48])
    with Image.open(region["crop"]["artifact"]["path"]) as crop:
        assert crop.size == (12, 48) and crop.convert("RGB").tobytes() == expected
    with prepared_wire_pixels(grounding_wire, result) as transmitted:
        assert transmitted.size == (48, 96)
    receipt = result["payload_receipt"][0]
    assert receipt["actual_seconds"] == frame["actual_seconds"]
    assert receipt["original_pts"] == frame["original_pts"]
    assert receipt["time_base"] == frame["time_base"]
    labels = [p["text"] for p in grounding_wire[0]["messages"][0]["content"] if p["type"] == "text"]
    assert any("decoded source time 0.6 seconds, PTS 6144" in label for label in labels)
    assert result["execution"]["continuous_watched_coverage"] is False
    assert result["provenance"]["factual_correctness_verified"] is False
    assert digest(path) == fixed_media["rotated"]["sha256"]


@pytest.mark.parametrize("name, start, end, fps, maximum, expected_ms, partial", [
    ("cfr", 0.51, 1.01, 10, 2, [600, 700], True),
    ("offset", 0.21, 0.91, 2, 3, [300, 800], False),
    ("vfr", 0.1, 1.0, 5, 3, [120, 520, 920], True),
])
async def test_sampled_video_dry_run_commits_real_source_pts_frame_hashes_and_cap(
        name, start, end, fps, maximum, expected_ms, partial, fixed_media, monkeypatch):
    """Dry preparation retains measured source clocks/hash and a bounded honest sample denominator."""
    wire = AsyncMock(side_effect=AssertionError("Dry run must not perform HTTP exchange"))
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    record = fixed_media[name]
    request = VisionRequest(sources=[source(Path(record["path"]), kind="video", start_seconds=start,
                                           end_seconds=end, fps=fps, max_frames=maximum)],
                            instruction="Describe these sampled frames", backend="geometry")
    result = await analyze_vision(request, "vision_chat")
    assert result["status"] == "planned" and result["model_output"] is None
    assert result["execution"]["provider_calls"] == 0 and not wire.called
    assert result["execution"]["continuous_watched_coverage"] is False
    prepared = result["preparations"][0]
    assert prepared["source"]["path"] == record["path"]
    assert prepared["source"]["sha256"] == record["sha256"] == digest(Path(record["path"]))
    assert prepared["source"]["source_revision"] == "sha256:" + record["sha256"]
    assert len(prepared["frames"]) <= maximum
    assert prepared["coverage"]["sampled_points"] == pytest.approx([ms / 1000 for ms in expected_ms])
    assert prepared["coverage"]["watched_intervals"] == []
    assert (prepared["status"] == "partial") is partial
    assert prepared["coverage"]["complete"] is not partial
    expected_indices = [record["frame_ms"].index(ms) for ms in expected_ms]
    oracle = [frame for frame in record["oracle"]["frames"] if frame["media_type"] == "video"]
    assert [frame["original_pts"] for frame in prepared["frames"]] == [int(oracle[i]["pts"]) for i in expected_indices]
    for frame, receipt, index in zip(prepared["frames"], result["payload_receipt"], expected_indices):
        assert start <= frame["actual_seconds"] < end
        assert receipt["sha256"] == frame["sha256"] == digest(Path(frame["path"]))
        assert receipt["original_pts"] == frame["original_pts"]
        assert receipt["time_base"] == frame["time_base"]
        assert receipt["actual_seconds"] == frame["actual_seconds"]
        with Image.open(frame["path"]) as output:
            assert frame_index(output.convert("RGB").tobytes(), output.width) == index


async def test_sampled_video_wrong_sha_fails_before_any_subprocess_or_http(fixed_media, monkeypatch):
    """A stale source commitment stops before media probing, decoding or inferred submission."""
    process = AsyncMock(side_effect=AssertionError("Wrong revision reached a subprocess"))
    wire = AsyncMock(side_effect=AssertionError("Wrong revision reached HTTP"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", process)
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", wire)
    record = fixed_media["cfr"]
    request = VisionRequest(sources=[{"file_path": record["path"], "kind": "video",
                                     "expected_source_sha256": "0" * 64, "max_frames": 2}],
                            instruction="Do not process a stale source", backend="geometry")
    result = await analyze_vision(request, "vision_chat")
    assert "error" in result and "SHA256" in result["error"]
    assert result["payload_receipt"] == [] and result["execution"]["provider_calls"] == 0
    assert not process.called and not wire.called
