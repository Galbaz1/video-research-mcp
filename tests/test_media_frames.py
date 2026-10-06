"""Native frame parameter and source revision boundaries."""

from unittest.mock import AsyncMock

import pytest


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf")])
async def test_invalid_point_fails_before_source_read(value, monkeypatch):
    from video_research_mcp import media_frames

    probe = AsyncMock()
    monkeypatch.setattr(media_frames, "probe_snapshot", probe)
    with pytest.raises(ValueError):
        await media_frames.frame_at("/missing.mp4", time_seconds=value)
    probe.assert_not_awaited()


@pytest.fixture
def native_env(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    path = tmp_path / "source.mp4"
    path.write_bytes(b"owned deterministic input")
    return path


def source_metadata(owned):
    return {"path": str(owned.original), "sha256": owned.sha256, "bytes": owned.size,
            "source_revision": "sha256:" + owned.sha256, "duration_seconds": 2.0,
            "container_start_seconds": 0.0, "time_base": "1/1000", "stream_index": 0,
            "display_width": 32, "display_height": 24}


async def test_expected_source_revision_mismatch_never_probes(native_env, monkeypatch):
    from video_research_mcp import media_frames

    probe = AsyncMock()
    monkeypatch.setattr(media_frames, "probe_snapshot", probe)
    with pytest.raises(ValueError, match="SHA256"):
        await media_frames.frame_at(str(native_env), time_seconds=0, expected_source_sha256="0" * 64)
    probe.assert_not_awaited()
    assert list((native_env.parent / "cache/media/views").iterdir()) == []


@pytest.mark.parametrize("kwargs", [
    {"time_seconds": 2}, {"time_seconds": 3},
    {"time_seconds": 1, "crop_box": [0, 0, 33, 24]},
    {"time_seconds": 1, "crop_box": [0.5, 0, 1, 1]},
])
async def test_out_of_range_and_bad_crop_never_render(native_env, monkeypatch, kwargs):
    from video_research_mcp import media_frames

    monkeypatch.setattr(media_frames, "probe_snapshot", AsyncMock(side_effect=source_metadata))
    render = AsyncMock()
    monkeypatch.setattr(media_frames, "run_media_process", render)
    with pytest.raises(ValueError):
        await media_frames.frame_at(str(native_env), **kwargs)
    render.assert_not_awaited()


@pytest.mark.parametrize("kwargs", [
    {"fps": 31}, {"fps": 0}, {"fps": float("nan")},
    {"max_frames": 49}, {"max_frames": 0}, {"max_frames": True},
    {"max_pixels": 1_000_001}, {"selection": "deduplicate"},
    {"start_seconds": -0.1}, {"end_seconds": float("inf")},
])
async def test_sampling_budgets_reject_before_source_read(kwargs, monkeypatch):
    from video_research_mcp import media_frames

    probe = AsyncMock()
    monkeypatch.setattr(media_frames, "probe_snapshot", probe)
    with pytest.raises(ValueError):
        await media_frames.sample_frames("/missing.mp4", **kwargs)
    probe.assert_not_awaited()


def test_pts_parser_never_substitutes_requested_or_zero_time():
    from video_research_mcp.media_frames import _pts

    with pytest.raises(ValueError, match="time base"):
        _pts(b"n:0 pts:0 pts_time:0", "1/1000")
    base, points = _pts(b"[Parsed_showinfo_1 @ 1] config in time_base: 1/1000, frame_rate: 0/0\n"
                        b"[Parsed_showinfo_1 @ 1] n: 0 pts: 520 pts_time:0.52\n"
                        b"[Parsed_showinfo_1 @ 1] n: 1 pts: 640 pts_time:0.64\n", "1/1000")
    assert base == "1/1000"
    assert points == {0: 520, 1: 640}


@pytest.mark.parametrize("separator", [b"\n                    : ", "\u2028".encode()])
def test_metadata_showinfo_lookalikes_cannot_define_time_base_or_pts(separator):
    from video_research_mcp.media_frames import _pts

    text = (b"    comment : harmless" + separator + b"[Parsed_showinfo_1 @ 1] config in time_base: 1/1, frame_rate: 0/0\n"
            b"    comment : harmless" + separator + b"[Parsed_showinfo_1 @ 1] n: 0 pts: 999999 pts_time:999999\n"
            b"[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1000, frame_rate: 10/1\n"
            b"[Parsed_showinfo_1 @ 0xabc] n: 0 pts: 200 pts_time:0.2\n"
            b"    comment : harmless" + separator + b"[Parsed_showinfo_1 @ 1] n: 0 pts: 999999 pts_time:999999\n")
    base, points = _pts(text, "1/1000")
    assert base == "1/1000"
    assert points == {0: 200}


def test_duplicate_showinfo_frame_index_is_ambiguous():
    from video_research_mcp.media_frames import _pts

    text = (b"[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1000, frame_rate: 10/1\n"
            b"[Parsed_showinfo_1 @ 0xabc] n: 0 pts: 200 pts_time:0.2\n"
            b"[Parsed_showinfo_1 @ 0xabc] n: 0 pts: 300 pts_time:0.3\n")
    with pytest.raises(ValueError, match="Ambiguous"):
        _pts(text, "1/1000")


@pytest.mark.parametrize("text", [
    b"[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1, frame_rate: 10/1\n",
    b"    comment : [Parsed_showinfo_1 @ 1] config in time_base: 1/1000, frame_rate: 10/1\n",
    (b"[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1000, frame_rate: 10/1\n"
     b"[Parsed_showinfo_2 @ 0xdef] config in time_base: 1/1000, frame_rate: 10/1\n"),
    (b"[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1000, frame_rate: 10/1\n"
     b"[Parsed_showinfo_1 @ 0xabc] n: 0 pts: NOPTS pts_time:NOPTS\n"),
    (b"[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1000, frame_rate: 10/1\n"
     b"[Parsed_showinfo_1 @ 0xabc] n: 0 pts: 200 pts_time:0.4\n"),
])
def test_unverified_or_inconsistent_decoded_clock_fails_closed(text):
    from video_research_mcp.media_frames import _pts

    with pytest.raises(ValueError):
        _pts(text, "1/1000")


def test_conservative_aggregate_reservation_bounds_actual_render_count():
    from video_research_mcp.media_frames import _render_count

    count, reason = _render_count(1000, 1000, 48)
    assert count == 2
    assert reason == "artifact_byte_reservation"
    assert count * (4 * 1_000_000 + 65536) <= 8 * 1024 * 1024


async def test_source_mutation_after_frame_decode_cannot_publish(native_env, monkeypatch):
    from pathlib import Path
    from video_research_mcp import media_frames
    from tests.test_media_image_read import make_png

    monkeypatch.setattr(media_frames, "probe_snapshot", AsyncMock(side_effect=source_metadata))

    async def render(command, timeout):
        make_png(Path(command[-1].replace("%03d", "001")))
        native_env.write_bytes(b"source changed while decoding")
        return b"", (b"[Parsed_showinfo_1 @ 1] config in time_base: 1/1000, frame_rate: 1/1\n"
                      b"[Parsed_showinfo_1 @ 1] n: 0 pts: 500 pts_time:0.5\n")

    monkeypatch.setattr(media_frames, "run_media_process", render)
    with pytest.raises(ValueError, match="changed"):
        await media_frames.frame_at(str(native_env), time_seconds=0.5)
    assert native_env.read_bytes() == b"source changed while decoding"
    assert list((native_env.parent / "cache/media/views").iterdir()) == []


async def test_missing_decoded_pts_cannot_publish(native_env, monkeypatch):
    from pathlib import Path
    from video_research_mcp import media_frames
    from tests.test_media_image_read import make_png

    monkeypatch.setattr(media_frames, "probe_snapshot", AsyncMock(side_effect=source_metadata))

    async def render(command, timeout):
        make_png(Path(command[-1].replace("%03d", "001")))
        return b"", b"[Parsed_showinfo_1 @ 1] config in time_base: 1/1000, frame_rate: 1/1\n"

    monkeypatch.setattr(media_frames, "run_media_process", render)
    with pytest.raises(ValueError, match="no verified decoded"):
        await media_frames.frame_at(str(native_env), time_seconds=0)
    assert list((native_env.parent / "cache/media/views").iterdir()) == []


@pytest.mark.parametrize("pts", [100, 2000])
async def test_point_or_source_extent_mismatch_cannot_publish(native_env, monkeypatch, pts):
    from pathlib import Path
    from video_research_mcp import media_frames
    from tests.test_media_image_read import make_png

    monkeypatch.setattr(media_frames, "probe_snapshot", AsyncMock(side_effect=source_metadata))

    async def render(command, timeout):
        make_png(Path(command[-1].replace("%03d", "001")))
        return b"", ("[Parsed_showinfo_1 @ 0xabc] config in time_base: 1/1000, frame_rate: 1/1\n"
                      f"[Parsed_showinfo_1 @ 0xabc] n: 0 pts: {pts} pts_time:{pts / 1000}\n").encode()

    monkeypatch.setattr(media_frames, "run_media_process", render)
    with pytest.raises(ValueError, match="precedes|outside"):
        await media_frames.frame_at(str(native_env), time_seconds=0.5)
    assert list((native_env.parent / "cache/media/views").iterdir()) == []


@pytest.fixture
async def review_original(native_env):
    """Reuse a frozen original CFR when supplied, otherwise encode its authored pixels."""
    import hashlib
    import json
    import os
    from pathlib import Path
    from tests.native_media_fixtures import frame_pixels, write_png
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    manifest = os.getenv("NATIVE_MEDIA_FIXTURE_MANIFEST")
    if manifest:
        original = json.loads(Path(manifest).read_text())["fixtures"]["cfr"]
        data = Path(original["path"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == original["sha256"]
        native_env.write_bytes(data)
    else:
        for index in range(12):
            write_png(native_env.parent / f"frame-{index:02d}.png", frame_pixels(index))
        await run_media_process([binary("ffmpeg"), "-nostdin", "-v", "error", "-y",
                                 "-threads", "1", "-filter_threads", "1", "-framerate", "10",
                                 "-i", str(native_env.parent / "frame-%02d.png"), "-frames:v", "12",
                                 "-c:v", "libx264rgb", "-qp", "0", "-bf", "0", "-g", "6",
                                 "-threads", "1", str(native_env)], 10)
    return native_env


async def test_actual_metadata_injection_preserves_genuine_point_and_window(review_original):
    from fractions import Fraction
    from pathlib import Path
    from video_research_mcp.media_frames import frame_at, sample_frames
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process
    from tests.native_media_fixtures import decoded_rgb, frame_pixels

    path = review_original.with_name("comment-injected.mp4")
    comment = ("[Parsed_showinfo_1 @ 1] config in time_base: 1/1, frame_rate: 0/0\n"
               "[Parsed_showinfo_1 @ 1] n: 0 pts: 999999 pts_time:999999")
    await run_media_process([binary("ffmpeg"), "-nostdin", "-v", "error", "-y",
                             "-protocol_whitelist", "file", "-i", str(review_original),
                             "-c", "copy", "-metadata", "comment=" + comment, str(path)], 10)
    result = await frame_at(str(path), time_seconds=0.15)
    frame = result["frames"][0]
    assert Fraction(frame["time_base"]) == Fraction(result["source"]["time_base"])
    assert frame["original_pts"] == 2048
    assert frame["actual_seconds"] == pytest.approx(0.2)
    assert await decoded_rgb(Path(frame["path"])) == frame_pixels(2)
    window = await sample_frames(str(path), start_seconds=0.11, end_seconds=0.35, fps=10)
    assert window["coverage"]["sampled_points"] == [0.2, 0.3]


@pytest.mark.parametrize("rotation", [0, 90])
async def test_actual_non_square_sar_with_rotation_crop_fails_before_render(review_original, monkeypatch, rotation):
    from video_research_mcp import media_frames
    from video_research_mcp.media_probe import binary, inspect_media
    from video_research_mcp.media_process import run_media_process

    path = review_original.with_name("non-square.mp4")
    await run_media_process([binary("ffmpeg"), "-nostdin", "-v", "error", "-y", "-threads", "1",
                             "-filter_threads", "1", "-protocol_whitelist", "file",
                             "-i", str(review_original), "-vf", "setsar=2", "-c:v", "libx264rgb",
                             "-qp", "0", "-bf", "0", "-g", "6", str(path)], 10)
    if rotation:
        rotated = path.with_name("non-square-rotated.mp4")
        await run_media_process([binary("ffmpeg"), "-nostdin", "-v", "error", "-y",
                                 "-display_rotation", "90", "-i", str(path), "-c", "copy", str(rotated)], 10)
        path = rotated
    source = await inspect_media(str(path))
    assert source["sample_aspect_ratio"] == "2:1"
    assert source["display_geometry_supported"] is False
    assert source["display_width"] is None
    assert source["display_height"] is None
    assert source["rotation_degrees"] == rotation
    render = AsyncMock()
    monkeypatch.setattr(media_frames, "run_media_process", render)
    with pytest.raises(ValueError, match="square pixels"):
        await media_frames.frame_at(str(path), time_seconds=0.15, crop_box=[0, 0, 50, 50])
    render.assert_not_awaited()


async def test_frame_cap_reports_partial_and_preserves_each_artifact(native_env, monkeypatch):
    from pathlib import Path
    from video_research_mcp import media_frames
    from tests.test_media_image_read import make_png

    monkeypatch.setattr(media_frames, "probe_snapshot", AsyncMock(side_effect=source_metadata))

    async def render(command, timeout):
        for number in (1, 2):
            make_png(Path(command[-1].replace("%03d", f"{number:03d}")))
        return b"", (b"[Parsed_showinfo_1 @ 1] config in time_base: 1/1000, frame_rate: 1/1\n"
                      b"[Parsed_showinfo_1 @ 1] n: 0 pts: 0 pts_time:0\n"
                      b"[Parsed_showinfo_1 @ 1] n: 1 pts: 1000 pts_time:1\n")

    monkeypatch.setattr(media_frames, "run_media_process", render)
    result = await media_frames.sample_frames(str(native_env), max_frames=2)
    assert len(result["frames"]) == 2
    assert result["frames"][0]["sha256"] == result["frames"][1]["sha256"]
    assert result["status"] == "partial"
    assert result["coverage"]["complete"] is False
    assert result["coverage"]["stop_reason"] == "frame_budget"
    assert result["coverage"]["sampled_points"] == [0, 1]
    assert result["coverage"]["watched_intervals"] == []


async def test_render_cancellation_preserves_original_and_existing_view(native_env, monkeypatch):
    import asyncio
    from pathlib import Path
    from video_research_mcp import media_frames

    monkeypatch.setattr(media_frames, "probe_snapshot", AsyncMock(side_effect=source_metadata))
    started = asyncio.Event()
    kept = native_env.parent / "cache/media/views/retained"
    kept.mkdir(parents=True)
    (kept / "keep").write_text("keep")

    async def render(command, timeout):
        Path(command[-1].replace("%03d", "001")).write_bytes(b"partial")
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(media_frames, "run_media_process", render)
    task = asyncio.create_task(media_frames.frame_at(str(native_env), time_seconds=0))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert native_env.read_bytes() == b"owned deterministic input"
    assert list(kept.parent.iterdir()) == [kept]


async def test_one_deadline_covers_probe_and_render(native_env, monkeypatch):
    import asyncio
    import math
    from types import SimpleNamespace
    from video_research_mcp import media_frames, media_snapshot
    from video_research_mcp.config import get_config

    loop = asyncio.get_running_loop()
    # Integer-valued start keeps (start + 30) - (start + 20) exactly 10; a fractional
    # host loop.time() can cancel to 9.999999999999972 (CI 3.14, runner uptime ~232 s).
    clock = [float(math.floor(loop.time()))]
    monkeypatch.setattr(loop, "time", lambda: clock[0])
    monkeypatch.setattr(media_snapshot, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    get_config().media_acquire_timeout_seconds = 30
    observed = []

    async def probe(owned):
        clock[0] += 20
        return source_metadata(owned)

    async def render(command, timeout):
        observed.append(timeout)
        clock[0] += 20
        await asyncio.Event().wait()

    monkeypatch.setattr(media_frames, "probe_snapshot", probe)
    monkeypatch.setattr(media_frames, "run_media_process", render)
    with pytest.raises(TimeoutError):
        await media_frames.frame_at(str(native_env), time_seconds=0)
    assert observed == [10]
    assert list((native_env.parent / "cache/media/views").iterdir()) == []


async def test_reversed_window_fails_before_source_read(monkeypatch):
    from video_research_mcp import media_frames

    probe = AsyncMock()
    monkeypatch.setattr(media_frames, "probe_snapshot", probe)
    with pytest.raises(ValueError):
        await media_frames.sample_frames("/missing.mp4", start_seconds=2, end_seconds=1)
    probe.assert_not_awaited()
