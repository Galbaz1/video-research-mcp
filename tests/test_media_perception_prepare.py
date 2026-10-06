"""Exact-byte joint-media preparation, clocks, budgets and invocation-owned cleanup."""

import hashlib
import asyncio
from fractions import Fraction
import io
import json
import math
import os
import struct
import wave

import pytest

from video_research_mcp.models.media_perception import AVPerceptionRequest


@pytest.fixture(autouse=True)
def isolated_preparation(clean_config, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


@pytest.fixture
def source_audio(tmp_path):
    """Freeze two authored seconds of440Hz mono PCM without provider content."""
    path = tmp_path / "owned-audio.wav"
    samples = b"".join(struct.pack("<h", round(10000 * math.sin(2 * math.pi * 440 * n / 16000)))
                       for n in range(32000))
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        writer.writeframes(samples)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


def request_for(source, **changes):
    path, digest = source
    return AVPerceptionRequest(file_path=str(path), expected_source_sha256=digest,
                               instruction="Describe spoken and visible evidence", **changes)


async def test_whole_audio_preparation_clock_bytes_and_success_cleanup(source_audio, tmp_path):
    from video_research_mcp.media_perception_prepare import prepare_media

    path, digest = source_audio
    async with prepare_media(request_for(source_audio, window_seconds=1)) as (source, windows, verify):
        assert source["selected_media_type"] == "audio"
        assert source["container_start_seconds"] is None
        assert source["audio_clock_origin_basis"] == "derived_first_decoded_audio_pts"
        assert [(w["start_seconds"], w["end_seconds"]) for w in windows] == [(0, 1), (1, 2)]
        assert all(w["frames"] == [] and w["audio"]["output"]["sample_count"] == 16000 for w in windows)
        for window in windows:
            part = window["parts"][0]
            assert part["kind"] == "audio" and isinstance(part["data"], bytes)
            assert hashlib.sha256(part["data"]).hexdigest() == part["sha256"]
            assert "path" not in window["audio"]["artifact"]
            assert window["payload_bytes"] == len(part["data"])
            assert window["watched_intervals"] == []
        await verify()
        assert list((tmp_path / "cache" / "media" / "views").iterdir())
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
async def av_source(source_audio):
    """Freeze an owned red16x16 video with lossless audio and a+3second shared source clock."""
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    audio, _ = source_audio
    path = audio.with_suffix(".mp4")
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-threads", "1",
        "-f", "lavfi", "-i", "color=c=red:s=16x16:r=4:d=2", "-i", str(audio), "-map", "0:v:0",
        "-map", "1:a:0", "-c:v", "libx264", "-threads", "1", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-c:a", "alac", "-output_ts_offset", "3", "-n", str(path)], 5)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
async def av_source_30fps(source_audio, monkeypatch, record_property):
    """Generate one owned 30 fps source and record every joined native process."""
    from video_research_mcp.config import update_config
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    update_config(media_acquire_timeout_seconds=5)
    processes, commands = [], []
    spawn = asyncio.create_subprocess_exec

    async def tracked(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        processes.append(process)
        commands.append({"pid": process.pid, "argv": list(args)})
        return process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", tracked)
    audio, audio_sha = source_audio
    path = audio.with_name("owned-av-30fps.mp4")
    try:
        await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-threads", "1",
            "-f", "lavfi", "-i", "color=c=red:s=16x16:r=30:d=1", "-i", str(audio),
            "-map", "0:v:0", "-map", "1:a:0", "-t", "1", "-c:v", "libx264", "-threads", "1",
            "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "alac", "-output_ts_offset", "3",
            "-n", str(path)], 5)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        record_property("fixture", json.dumps({"source_sha256": digest, "source_bytes": path.stat().st_size,
            "input_audio_sha256": audio_sha, "rate": 30, "seconds": 1, "pixels": [16, 16], "timeout_seconds": 5}))
        yield path, digest
    finally:
        for process, command in zip(processes, commands):
            command["returncode"] = process.returncode
            assert process.returncode is not None
            with pytest.raises(ProcessLookupError):
                os.kill(process.pid, 0)
        record_property("native_processes", json.dumps(commands))


@pytest.mark.parametrize("cap", [32, 7])
async def test_30fps_preparation_and_caption_dry_run(av_source_30fps, tmp_path, monkeypatch, record_property, cap):
    from video_research_mcp.av_events import caption_events
    from video_research_mcp.client import GeminiClient
    from video_research_mcp.media_perception_prepare import prepare_media
    from video_research_mcp.models.av_events import CaptionEventsRequest

    monkeypatch.setattr(GeminiClient, "get", lambda: pytest.fail("Dry run reached provider SDK"))
    path, digest = av_source_30fps
    request = CaptionEventsRequest(file_path=str(path), expected_source_sha256=digest, fps=30,
        end_seconds=1, window_seconds=1, max_frames_per_window=cap, limits={"timeout_seconds": 5})
    async with prepare_media(request) as (source, windows, verify):
        window = windows[0]
        frames, parts = window["frames"], window["parts"]
        count = min(cap, 30)
        assert source["sha256"] == digest and source["container_start_seconds"] == 3
        assert len(frames) == count and [p["kind"] for p in parts] == ["image"] * count + ["audio"]
        assert [f["actual_seconds"] for f in frames] == pytest.approx([i / 30 for i in range(count)], abs=1e-12)
        assert [Fraction(f["original_pts"]) * Fraction(f["time_base"]) for f in frames] == [
            Fraction(3) + Fraction(i, 30) for i in range(count)]
        assert all((f["width"], f["height"]) == (16, 16) for f in frames)
        assert all(hashlib.sha256(p["data"]).hexdigest() == p["sha256"] for p in parts)
        with wave.open(io.BytesIO(parts[-1]["data"]), "rb") as decoded:
            assert (decoded.getnchannels(), decoded.getsampwidth(), decoded.getframerate(), decoded.getnframes()) == (1, 2, 16000, 16000)
            pcm = decoded.readframes(16000)
        with wave.open(str(path.with_name("owned-audio.wav")), "rb") as original:
            assert pcm == original.readframes(16000)
        assert hashlib.sha256(pcm).hexdigest() == window["audio"]["output"]["pcm_sha256"]
        assert source["audio_clock_origin_seconds"] == 3
        assert window["audio"]["selected_window"] == pytest.approx(
            {"start_seconds": 0, "end_seconds": 1}, abs=1e-12, rel=0)
        assert window["audio_status"] == "complete_selected_audio" and window["watched_intervals"] == []
        visual = window["visual_sampling"]
        assert visual["status"] == ("partial" if cap < 30 else "complete")
        assert visual["coverage"]["stop_reason"] == ("frame_budget" if cap < 30 else None)
        assert not visual["continuous_watched_coverage"]
        record_property("prepared", json.dumps({"source": source, "window": {k: v for k, v in window.items() if k != "parts"},
            "parts": [{k: v for k, v in p.items() if k != "data"} for p in parts]}))
        await verify()
    result = await caption_events(request)
    assert result["status"] == "planned" and result["execution"]["provider_calls"] == 0
    assert result["source"]["sha256"] == digest and result["windows"][0]["frames"] == frames
    record_property("dry_run", json.dumps(result))
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


async def test_joint_windows_keep_actual_offsets_frame_order_and_complete_pcm(av_source, tmp_path):
    from video_research_mcp.media_perception_prepare import prepare_media

    path, digest = av_source
    async with prepare_media(request_for(av_source, window_seconds=1, fps=2)) as (source, windows, verify):
        assert source["selected_media_type"] == "video" and source["has_audio"]
        assert source["container_start_seconds"] == source["audio_clock_origin_seconds"] == 3
        assert [[f["actual_seconds"] for f in w["frames"]] for w in windows] == [[0, .5], [1, 1.5]]
        for window in windows:
            assert [p["kind"] for p in window["parts"]] == ["image", "image", "audio"]
            assert window["audio"]["output"]["sample_count"] == 16000
            assert window["audio"]["selected_window"] == pytest.approx(
                {"start_seconds": window["start_seconds"], "end_seconds": window["end_seconds"]}, abs=1e-12, rel=0)
            assert window["visual_sampling"]["unobserved_between_sampled_points"]
            assert not window["visual_sampling"]["continuous_watched_coverage"]
            assert all("path" not in frame for frame in window["frames"])
            assert all(hashlib.sha256(p["data"]).hexdigest() == p["sha256"] for p in window["parts"])
        await verify()
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


async def test_audio_selected_from_video_has_no_visual_payload(av_source):
    from video_research_mcp.media_perception_prepare import prepare_media

    async with prepare_media(request_for(av_source, media_type="audio", start_seconds=.5, end_seconds=1.5)) as (source, windows, _):
        assert source["has_video"] and source["selected_media_type"] == "audio"
        assert not windows[0]["frames"] and [p["kind"] for p in windows[0]["parts"]] == ["audio"]
        assert windows[0]["audio"]["selected_window"] == pytest.approx(
            {"start_seconds": .5, "end_seconds": 1.5}, abs=1e-12, rel=0)


async def test_silent_video_has_no_fabricated_audio(av_source):
    from video_research_mcp.media_perception_prepare import prepare_media
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    path, _ = av_source
    silent = path.with_name("silent.mp4")
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-copyts", "-i", str(path),
                             "-c:v", "copy", "-an", "-n", str(silent)], 5)
    source = silent, hashlib.sha256(silent.read_bytes()).hexdigest()
    async with prepare_media(request_for(source, end_seconds=1)) as (metadata, windows, _):
        assert metadata["selected_media_type"] == "video" and not metadata["has_audio"]
        assert windows[0]["audio"] is None and windows[0]["audio_status"] == "source_has_no_audio"
        assert all(p["kind"] == "image" for p in windows[0]["parts"])
    with pytest.raises(ValueError, match="matching"):
        async with prepare_media(request_for(source, media_type="audio", end_seconds=1)):
            pytest.fail("Silent video accepted as audio")


async def test_partial_visual_sampling_retains_every_returned_frame(av_source):
    from video_research_mcp.media_perception_prepare import prepare_media

    async with prepare_media(request_for(av_source, end_seconds=2, fps=4, max_frames_per_window=1)) as (_, windows, _):
        visual = windows[0]["visual_sampling"]
        assert len(windows[0]["frames"]) == 1
        assert visual["status"] == "partial" and visual["coverage"]["stop_reason"] == "frame_budget"
        assert visual["coverage"]["watched_intervals"] == []


@pytest.mark.parametrize("changes", [{"end_seconds": 3}, {"start_seconds": 2, "end_seconds": 3},
    {"window_seconds": 1, "limits": {"max_windows": 1}}, {"media_type": "video"}])
async def test_source_interval_type_and_window_limits_reject_before_nested_work(source_audio, monkeypatch, changes):
    import video_research_mcp.media_perception_prepare as engine

    async def denied(*args, **kwargs):
        pytest.fail("Rejected selection reached nested artifact preparation")
    monkeypatch.setattr(engine, "export_audio", denied)
    monkeypatch.setattr(engine, "sample_frames", denied)
    with pytest.raises(ValueError):
        async with engine.prepare_media(request_for(source_audio, **changes)):
            pytest.fail("Invalid preparation yielded")


async def test_duration_over120_and_unknown_whole_extent_fail_closed(source_audio, monkeypatch):
    import video_research_mcp.media_perception_prepare as engine

    real = engine._source
    async def extent(owned, request):
        source = await real(owned, request)
        source["audio_end_seconds"] = 121
        return source
    monkeypatch.setattr(engine, "_source", extent)
    with pytest.raises(ValueError, match="120"):
        async with engine.prepare_media(request_for(source_audio)):
            pytest.fail("Overlong source yielded")
    async def unknown(owned, request):
        source = await real(owned, request)
        source["audio_end_seconds"] = None
        return source
    monkeypatch.setattr(engine, "_source", unknown)
    with pytest.raises(ValueError, match="known finite"):
        async with engine.prepare_media(request_for(source_audio)):
            pytest.fail("Unknown whole source yielded")
    async with engine.prepare_media(request_for(source_audio, end_seconds=1)) as (_, windows, _):
        assert windows[0]["audio"]["output"]["sample_count"] == 16000


async def test_frame_aggregate_reservation_before_sampling(av_source, monkeypatch):
    import video_research_mcp.media_perception_prepare as engine

    async def denied(*args, **kwargs):
        pytest.fail("Excess frame reservation reached sampler")
    monkeypatch.setattr(engine, "sample_frames", denied)
    with pytest.raises(ValueError, match="frame reservation"):
        async with engine.prepare_media(request_for(av_source, limits={"max_frames": 1})):
            pytest.fail("Excess frames yielded")


@pytest.mark.parametrize("limits", [{"max_payload_bytes": 1}, {"max_transmitted_bytes": 1},
                                    {"max_payload_bytes": 40000}])
async def test_byte_limits_cleanup_every_registered_nested_output(source_audio, tmp_path, limits):
    from video_research_mcp.media_perception_prepare import prepare_media

    base = tmp_path / "cache" / "media" / "views"
    preserved = base / ("f" * 32)
    preserved.mkdir(parents=True)
    (preserved / "sentinel").write_bytes(b"preserve unrelated output")
    with pytest.raises(ValueError, match="byte budget"):
        async with prepare_media(request_for(source_audio, window_seconds=1, limits=limits)):
            pytest.fail("Oversized payload yielded")
    assert list(base.iterdir()) == [preserved]


async def test_wrong_nested_source_binding_registered_then_cleaned(source_audio, monkeypatch, tmp_path):
    import video_research_mcp.media_perception_prepare as engine

    real = engine.export_audio
    async def stale(*args):
        result = await real(*args)
        result["source"]["sha256"] = "0" * 64
        return result
    monkeypatch.setattr(engine, "export_audio", stale)
    with pytest.raises(ValueError, match="frozen original"):
        async with engine.prepare_media(request_for(source_audio)):
            pytest.fail("Stale nested binding yielded")
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())


async def test_source_mutation_after_yield_fails_and_cleans_owned_views(source_audio, tmp_path):
    from video_research_mcp.media_perception_prepare import prepare_media

    path, _ = source_audio
    with pytest.raises(ValueError, match="changed"):
        async with prepare_media(request_for(source_audio)):
            with path.open("ab") as writer:
                writer.write(b"altered original")
    assert path.exists() and not list((tmp_path / "cache" / "media" / "views").iterdir())


async def test_artifact_or_buffer_tamper_is_detected_before_provider(source_audio, tmp_path):
    from video_research_mcp.media_perception_prepare import prepare_media

    with pytest.raises(ValueError, match="commitment"):
        async with prepare_media(request_for(source_audio)) as (_, windows, verify):
            windows[0]["parts"][0]["data"] = b"tampered immutable replacement"
            await verify()
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())


async def test_cancellation_at_yield_discards_ephemeral_outputs(source_audio, tmp_path):
    from video_research_mcp.media_perception_prepare import prepare_media

    entered = asyncio.Event()
    async def wait():
        async with prepare_media(request_for(source_audio)):
            entered.set()
            await asyncio.Event().wait()
    task = asyncio.create_task(wait())
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())


async def test_source_sha_fence_symlink_and_fifo_boundaries_before_probe(source_audio, tmp_path, monkeypatch):
    import os
    import video_research_mcp.media_perception_prepare as engine

    path, digest = source_audio
    symlink, fifo = tmp_path / "link.wav", tmp_path / "pipe.wav"
    symlink.symlink_to(path)
    os.mkfifo(fifo)
    async def denied(*args):
        pytest.fail("Rejected source reached probe")
    monkeypatch.setattr(engine, "probe_snapshot", denied)
    for candidate, expected in ((path, "0" * 64), (symlink, digest), (fifo, digest), (tmp_path.parent / "outside.wav", digest)):
        with pytest.raises((ValueError, PermissionError, FileNotFoundError)):
            async with engine.prepare_media(request_for((candidate, expected))):
                pytest.fail("Rejected source yielded")


async def test_attached_album_art_is_not_auto_selected_as_video(source_audio, monkeypatch):
    import video_research_mcp.media_perception_prepare as engine

    real = engine.probe_snapshot
    async def with_cover(owned):
        result = await real(owned)
        result["streams"].append({"codec_type": "video", "index": 1, "disposition": {"attached_pic": 1}})
        assert result["stream_index"] is None
        return result
    monkeypatch.setattr(engine, "probe_snapshot", with_cover)
    async with engine.prepare_media(request_for(source_audio)) as (source, windows, _):
        assert source["selected_media_type"] == "audio" and not source["has_video"]
        assert not windows[0]["frames"] and windows[0]["parts"][0]["kind"] == "audio"


async def test_probe_identity_cannot_rebind_the_expected_source(source_audio, monkeypatch):
    import video_research_mcp.media_perception_prepare as engine

    real = engine.audio_source
    async def wrong(owned):
        result = await real(owned)
        result["sha256"] = "0" * 64
        return result
    monkeypatch.setattr(engine, "audio_source", wrong)
    with pytest.raises(ValueError, match="frozen original"):
        async with engine.prepare_media(request_for(source_audio)):
            pytest.fail("Incorrect source metadata yielded")
