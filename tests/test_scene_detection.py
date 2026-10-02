"""Fixed owned visual cuts with independent source-relative PTS expectations."""

import json
import os
import shutil
from pathlib import Path

import pytest
import pytest_asyncio

from tests.native_media_fixtures import build_fixtures, digest
from video_research_mcp.config import get_config
from video_research_mcp.media_probe import binary
from video_research_mcp.media_process import run_media_process
from video_research_mcp.media_scenes import detect_scenes
from video_research_mcp.models.scene_assets import SceneRequest


@pytest.fixture(autouse=True)
def isolated_views(tmp_path, clean_config, monkeypatch):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("LOCAL_FILE_ACCESS_ROOT", raising=False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def scene_sources(tmp_path_factory):
    """Declare clocks before encoding two original static/change fixtures and one offset copy."""
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Owned visual-cut fixtures require installed FFmpeg/ffprobe")
    root = os.getenv("VISUAL_OWNER_FIXTURE_ROOT")
    directory = Path(root) / "scenes" if root else tmp_path_factory.mktemp("owned-scenes")
    directory.mkdir(parents=True, exist_ok=True)
    labels = {"frame_seconds": [i / 5 for i in range(16)], "cut_seconds": [0.8, 1.6, 2.4],
              "extent_seconds": 3.2, "source_offset_seconds": 3}
    (directory / "expected-before-generation.json").write_text(json.dumps(labels))
    for name in ("static", "changes", "subtle"):
        level = 20 if name == "subtle" else 255
        pixels = b"".join(bytes((level if name != "static" and i // 4 % 2 else 0,)) * (64 * 40 * 3)
                          for i in range(16))
        raw = directory / (name + ".rgb")
        raw.write_bytes(pixels)
        command = [binary("ffmpeg"), "-v", "error", "-nostdin", "-n", "-threads", "1",
                   "-protocol_whitelist", "file", "-f", "rawvideo", "-pixel_format", "rgb24",
                   "-video_size", "64x40", "-framerate", "5", "-i", str(raw), "-an",
                   "-c:v", "libx264rgb", "-threads", "1", "-crf", "0", "-preset", "ultrafast",
                   "-map_metadata", "-1", str(directory / (name + ".mp4"))]
        await run_media_process(command, 20)
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-n", "-protocol_whitelist", "file",
                             "-i", str(directory / "changes.mp4"), "-c", "copy", "-output_ts_offset", "3",
                             "-map_metadata", "-1", str(directory / "offset.mp4")], 20)
    return directory


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def fixed_native(tmp_path_factory):
    """Use accepted original VFR fixtures, keeping their independent clock declaration."""
    if supplied := os.getenv("NATIVE_MEDIA_FIXTURE_MANIFEST"):
        path = Path(supplied)
        assert digest(path) == "e850edfe4da72f54ebf7b533dd715606998cd0d96aa4b0479af80d80bdfc60eb"
        return json.loads(path.read_text())["fixtures"]
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Native media binaries required")
    return (await build_fixtures(tmp_path_factory.mktemp("visual-native-fixtures")))["fixtures"]


def request(directory, name="changes", **values):
    path = directory / (name + ".mp4")
    return SceneRequest(file_path=str(path), expected_source_sha256=digest(path), **values)


async def test_actual_static_source_has_one_contiguous_unwatched_visual_interval(scene_sources):
    result = await detect_scenes(request(scene_sources, "static"))
    assert result["status"] == "complete" and result["raw_cuts"] == []
    assert [(s["start_seconds"], s["end_seconds"]) for s in result["scenes"]] == [(0, 3.2)]
    assert result["coverage"]["watched_intervals"] == []
    assert result["provenance"]["semantic_scenes_verified"] is False


@pytest.mark.parametrize("name, offset", [("changes", 0), ("offset", 3)])
async def test_hard_changes_use_actual_original_pts_and_contiguous_intervals(scene_sources, name, offset):
    path = scene_sources / (name + ".mp4")
    before = path.read_bytes()
    result = await detect_scenes(request(scene_sources, name, min_scene_seconds=0.4))
    assert [cut["actual_seconds"] for cut in result["cuts"]] == pytest.approx([0.8, 1.6, 2.4])
    assert [cut["original_pts"] for cut in result["cuts"]] == [round((t + offset) * 10240) for t in [0.8, 1.6, 2.4]]
    assert all(cut["time_base"] == "1/10240" for cut in result["cuts"])
    assert [s["start_seconds"] for s in result["scenes"]] == pytest.approx([0, 0.8, 1.6, 2.4])
    assert [s["end_seconds"] for s in result["scenes"]] == pytest.approx([0.8, 1.6, 2.4, 3.2])
    assert all(left["end_seconds"] == right["start_seconds"] for left, right in zip(result["scenes"], result["scenes"][1:]))
    assert path.read_bytes() == before


@pytest.mark.parametrize("minimum, expected", [(1, [1.6]), (1.7, [])])
async def test_minimum_duration_merges_short_internal_and_tail_intervals(scene_sources, minimum, expected):
    result = await detect_scenes(request(scene_sources, min_scene_seconds=minimum))
    assert len(result["raw_cuts"]) == 3
    assert [cut["actual_seconds"] for cut in result["cuts"]] == pytest.approx(expected)
    assert result["scenes"][0]["start_seconds"] == 0
    assert result["scenes"][-1]["end_seconds"] == 3.2


async def test_exact_half_open_requested_window_does_not_become_nominal_cut_time(scene_sources):
    result = await detect_scenes(request(scene_sources, start_seconds=0.3, end_seconds=2.4, min_scene_seconds=0.1))
    assert [cut["actual_seconds"] for cut in result["cuts"]] == pytest.approx([0.8, 1.6])
    assert result["scenes"][0]["start_seconds"] == 0.3
    assert result["scenes"][-1]["end_seconds"] == 2.4
    assert all(0.3 < c["actual_seconds"] < 2.4 for c in result["raw_cuts"])


async def test_cut_budget_overflow_never_returns_complete_partition(scene_sources):
    with pytest.raises(ValueError, match="cut budget"):
        await detect_scenes(request(scene_sources, max_cuts=1, min_scene_seconds=0.1))
    assert not list((Path(get_config().cache_dir) / "media" / "views").iterdir())


async def test_adjustable_threshold_changes_measured_small_visual_cut_population(scene_sources):
    low = await detect_scenes(request(scene_sources, "subtle", threshold=0.01, min_scene_seconds=0.1))
    default = await detect_scenes(request(scene_sources, "subtle", min_scene_seconds=0.1))
    assert [cut["actual_seconds"] for cut in low["cuts"]] == pytest.approx([0.8, 1.6, 2.4])
    assert default["raw_cuts"] == []
    assert low["algorithm"]["threshold"] == 0.01 and default["algorithm"]["threshold"] == 0.3


async def test_vfr_cuts_bind_only_known_original_pts_and_do_not_round_to_nominal_grid(fixed_native):
    record = fixed_native["vfr"]
    result = await detect_scenes(SceneRequest(file_path=record["path"], expected_source_sha256=record["sha256"],
                                             threshold=0.001, min_scene_seconds=0.01))
    assert result["raw_cuts"]
    assert all(cut["original_pts"] in record["frame_ms"] for cut in result["raw_cuts"])
    for cut in result["raw_cuts"]:
        assert cut["time_base"] == "1/1000" and cut["actual_seconds"] == cut["original_pts"] / 1000
    assert digest(Path(record["path"])) == record["sha256"]


async def test_120_second_window_limit_precedes_scene_decode(scene_sources, monkeypatch):
    from video_research_mcp import media_scenes as engine
    from unittest.mock import AsyncMock

    probe = engine.probe_snapshot

    async def metadata(owned):
        source = await probe(owned)
        source["presentation_end_seconds"] = 121
        return source

    process = AsyncMock(side_effect=AssertionError("Unbounded scene window reached decode"))
    monkeypatch.setattr(engine, "probe_snapshot", metadata)
    monkeypatch.setattr(engine, "run_media_process", process)
    with pytest.raises(ValueError, match="120-second"):
        await detect_scenes(request(scene_sources))
    assert not process.called


@pytest.mark.parametrize("values", [{"end_seconds": 4}, {"start_seconds": 3.2}])
async def test_source_extent_is_rejected_without_silent_clamping(scene_sources, values):
    with pytest.raises(ValueError, match="outside"):
        await detect_scenes(request(scene_sources, **values))


async def test_wrong_digest_stops_before_any_subprocess(scene_sources, monkeypatch):
    import asyncio
    from unittest.mock import AsyncMock

    process = AsyncMock(side_effect=AssertionError("Stale source reached subprocess"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", process)
    value = request(scene_sources).model_copy(update={"expected_source_sha256": "0" * 64})
    with pytest.raises(ValueError, match="SHA256"):
        await detect_scenes(value)
    assert not process.called
