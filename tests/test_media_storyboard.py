"""Actual storyboard pixels and omitted-endpoint clip controls on fixed development media."""

import asyncio
import json
import os
import shutil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
import pytest
import pytest_asyncio
from pydantic import ValidationError

from tests.native_media_fixtures import build_fixtures, digest
from video_research_mcp import media_storyboard as engine
from video_research_mcp.config import get_config
from video_research_mcp.image_manifest import read_manifest
from video_research_mcp.media_clip_export import export_selected_clip
from video_research_mcp.media_image_read import geometry
from video_research_mcp.models.scene_assets import ClipSelectionRequest, StoryboardRequest


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def fixed_media(tmp_path_factory):
    """Use unchanged sealed development bytes or the same portable owned fixtures."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Independently installed FFmpeg/ffprobe are required")
    if supplied := os.getenv("NATIVE_MEDIA_FIXTURE_MANIFEST"):
        path = Path(supplied)
        assert digest(path) == "e850edfe4da72f54ebf7b533dd715606998cd0d96aa4b0479af80d80bdfc60eb"
        manifest = json.loads(path.read_text())
    else:
        manifest = await build_fixtures(tmp_path_factory.mktemp("storyboard-fixtures"))
    for fixture in manifest["fixtures"].values():
        assert digest(Path(fixture["path"])) == fixture["sha256"]
    return manifest["fixtures"]


@pytest.fixture(autouse=True)
def isolated_outputs(tmp_path, monkeypatch, clean_config):
    """Isolate owned views and preserve every fixed input file."""
    root = Path(os.getenv("SCENE_ASSETS_OUTPUT_ROOT", str(tmp_path))) / tmp_path.name
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(root / "cache"))
    monkeypatch.delenv("LOCAL_FILE_ACCESS_ROOT", raising=False)


def source_request(fixture, **values):
    """Bind the exact fixture revision for each operation."""
    return {"file_path": fixture["path"], "expected_source_sha256": fixture["sha256"], **values}


def retained(result):
    """Retain actual JSON beside the test's own artifacts when an output root is supplied."""
    Path(result["manifest"]["path"]).with_name("test-result.json").write_text(
        json.dumps(result, indent=2, allow_nan=False) + "\n"
    )


@pytest.mark.parametrize("width,height,budget", [(1, 16384, 1), (16384, 1, 1), (2, 9, 2)])
def test_minimum_dimension_rounding_cannot_exceed_a_requested_pixel_limit(width, height, budget):
    """The shared decoder rejects impossible tight aspect-ratio budgets before allocating pixels."""
    with pytest.raises(ValueError, match="Pixel budget"):
        geometry({"display_width": width, "display_height": height}, budget, None)


@pytest.mark.parametrize("name, labels", [
    ("cfr", ["00:00:00.200", "00:00:00.400", "00:00:00.600", "00:00:00.800"]),
    ("offset", ["00:00:00.200", "00:00:00.400", "00:00:00.600", "00:00:00.800"]),
    ("vfr", ["00:00:00.280", "00:00:00.520", "00:00:00.920"]),
])
async def test_burned_labels_match_actual_absolute_source_points_and_pixels(name, labels, fixed_media):
    """A nonzero window uses original PTS labels and exact sampled pixels, including VFR gaps."""
    fixture = fixed_media[name]
    result = await engine.create_storyboard(StoryboardRequest(**source_request(
        fixture, start_seconds=0.2, end_seconds=1.0, columns=2, rows=2
    )))
    retained(result)
    assert [tile["label"] for tile in result["tiles"]] == labels
    assert result["labels"]["burned"] is True
    assert result["labels"]["human_verified"] is False
    assert result["coverage"]["watched_intervals"] == []
    font = ImageFont.load_default(size=12)
    with Image.open(result["artifact"]["path"]) as sheet:
        for tile, frame, label in zip(result["tiles"], result["frames"], labels):
            x, y, width, height = tile["label_rectangle"]
            with Image.new("RGB", (width, height), "black") as expected:
                bbox = font.getbbox(label)
                ImageDraw.Draw(expected).text((4 - bbox[0], 4 - bbox[1]), label, font=font, fill="white")
                with sheet.crop((x, y, x + width, y + height)) as actual:
                    assert actual.tobytes() == expected.tobytes()
                    assert any(actual.tobytes())
            with Image.open(frame["path"]) as original:
                with sheet.crop((tile["x"], tile["y"], tile["x"] + frame["width"],
                                 tile["y"] + frame["height"])) as actual:
                    assert actual.tobytes() == original.convert("RGB").tobytes()
            assert tile["source_frame_sha256"] == digest(Path(frame["path"]))
            assert tile["original_pts"] == frame["original_pts"]
    assert result["artifact"]["sha256"] == digest(Path(result["artifact"]["path"]))
    assert digest(Path(fixture["path"])) == fixture["sha256"]


async def test_manifest_readback_commits_frames_and_burned_labels_then_rejects_tampering(fixed_media):
    result = await engine.create_storyboard(StoryboardRequest(**source_request(
        fixed_media["cfr"], columns=2, rows=1
    )))
    retained(result)
    manifest = result["manifest"]
    restored = await read_manifest(manifest["path"], manifest["sha256"])
    assert restored["verified"] is True
    assert restored["tiles"] == result["tiles"]
    assert restored["labels"] == result["labels"]
    assert len(restored["artifacts"]) == len(result["frames"]) + 1
    Path(result["frames"][0]["path"]).write_bytes(b"changed sampled pixels")
    with pytest.raises(ValueError, match="identity changed"):
        await read_manifest(manifest["path"], manifest["sha256"])


@pytest.mark.parametrize("values", [
    {"columns": 6, "rows": 4}, {"columns": True}, {"rows": 0},
    {"start_seconds": float("nan")}, {"end_seconds": float("inf")},
    {"start_seconds": 1, "end_seconds": 1}, {"output_path": "/unowned.png"},
    {"overwrite": True}, {"max_pixels": True},
])
def test_invalid_grid_window_and_output_policy_reject_before_source_access(values):
    with pytest.raises(ValidationError):
        StoryboardRequest(**source_request({"path": "unused", "sha256": "a" * 64}, **values))


@pytest.mark.parametrize("values, message", [
    ({"end_seconds": 2}, "interval"), ({"expected_source_sha256": "0" * 64}, "SHA256"),
])
async def test_invalid_source_window_leaves_no_owned_output(values, message, fixed_media):
    with pytest.raises(ValueError, match=message):
        await engine.create_storyboard(StoryboardRequest(**source_request(fixed_media["cfr"], **values)))
    base = Path(get_config().cache_dir) / "media" / "views"
    assert not base.exists() or not list(base.iterdir())


@pytest.mark.parametrize("cancel", [False, True])
async def test_composition_failure_or_cancel_joins_cleanup_and_preserves_prior_export(
    cancel, monkeypatch, fixed_media
):
    request = StoryboardRequest(**source_request(fixed_media["cfr"], columns=2, rows=1))
    prior = await engine.create_storyboard(request)
    retained(prior)
    directory = Path(prior["artifact"]["path"]).parent
    before = {p.name: p.read_bytes() for p in directory.iterdir()}
    entered, joined = asyncio.Event(), asyncio.Event()

    async def failed(*args, **kwargs):
        entered.set()
        try:
            if cancel:
                await asyncio.Future()
            raise RuntimeError("controlled composition failure")
        finally:
            joined.set()

    monkeypatch.setattr(engine, "image_worker", failed)
    task = asyncio.create_task(engine.create_storyboard(request))
    await asyncio.wait_for(entered.wait(), 5)
    if cancel:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(RuntimeError, match="composition failure"):
            await task
    assert joined.is_set()
    surviving = set(directory.parent.iterdir())
    expected = {directory, *(Path(f["path"]).parent for f in prior["frames"])}
    assert surviving == expected
    assert {p.name: p.read_bytes() for p in directory.iterdir()} == before


@pytest.mark.parametrize("selection, expected", [
    ({}, (0, 1.2)), ({"start_seconds": 0.3}, (0.3, 1.2)),
    ({"end_seconds": 0.8}, (0, 0.8)),
])
async def test_whole_and_one_sided_video_selection_is_measured_without_overwriting(
    selection, expected, fixed_media
):
    fixture = fixed_media["cfr"]
    request = ClipSelectionRequest(**source_request(fixture, include_audio=False, **selection))
    first = await export_selected_clip(request)
    second = await export_selected_clip(request)
    retained(first)
    retained(second)
    assert first["requested_interval"] == dict(zip(("start_seconds", "end_seconds"), expected))
    assert first["source_frames"][0]["actual_seconds"] == pytest.approx(expected[0])
    assert first["source_frames"][-1]["actual_seconds"] == pytest.approx(expected[1] - 0.1)
    assert first["output"]["frame_count"] == round((expected[1] - expected[0]) * 10)
    assert first["artifacts"][0]["path"] != second["artifacts"][0]["path"]
    for result in (first, second):
        assert result["artifacts"][0]["sha256"] == digest(Path(result["artifacts"][0]["path"]))
        assert (await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"]))["verified"]
    assert digest(Path(fixture["path"])) == fixture["sha256"]
