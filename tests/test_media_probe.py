"""Exact source snapshots and metadata failure boundaries."""

import asyncio
import hashlib
import json
import os
import threading
from unittest.mock import AsyncMock

import pytest


async def test_missing_and_denied_source_never_probe(tmp_path, monkeypatch, clean_config):
    """Missing/denied local inputs fail before native processing."""
    from video_research_mcp import media_probe

    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    run = AsyncMock()
    monkeypatch.setattr(media_probe, "run_media_process", run)
    with pytest.raises(FileNotFoundError):
        await media_probe.inspect_media(str(tmp_path / "missing.mp4"))
    with pytest.raises(PermissionError):
        await media_probe.inspect_media("/etc/passwd")
    run.assert_not_awaited()


def test_long_nested_path_fails_before_parsing_or_filesystem_access(monkeypatch):
    from video_research_mcp import media_snapshot
    from unittest.mock import Mock

    parse = Mock(side_effect=AssertionError("Long path must fail before parsing"))
    monkeypatch.setattr(media_snapshot, "resolve_path", parse)
    with pytest.raises(ValueError, match="4096"):
        media_snapshot.checked_path("/" + "nested/" * 700)
    parse.assert_not_called()


@pytest.fixture
def native_env(tmp_path, monkeypatch, clean_config):
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    path = tmp_path / "source.mp4"
    path.write_bytes(b"owned deterministic input")
    return path


async def test_unknown_metadata_remains_unknown(native_env, monkeypatch):
    from video_research_mcp import media_probe

    run = AsyncMock(return_value=(b'{"streams": [{"codec_type": "audio", "index": 0}], "format": {}}', b""))
    monkeypatch.setattr(media_probe, "run_media_process", run)
    source = await media_probe.inspect_media(str(native_env))
    assert source["sha256"] == hashlib.sha256(native_env.read_bytes()).hexdigest()
    assert source["source_revision"] == "sha256:" + source["sha256"]
    assert source["duration_seconds"] is None
    assert source["container_start_seconds"] is None
    assert source["display_width"] is None
    assert source["stream_index"] is None
    assert source["time_base"] is None
    assert list((native_env.parent / "cache/media/views").iterdir()) == []


async def test_mutated_source_during_probe_discards_only_owned_stage(native_env, monkeypatch):
    from video_research_mcp import media_probe

    kept = native_env.parent / "cache/media/views/other"
    kept.mkdir(parents=True)
    (kept / "keep").write_text("unrelated")

    async def mutate(*args, **kwargs):
        native_env.write_bytes(b"changed bytes")
        return b'{"streams": [], "format": {}}', b""

    monkeypatch.setattr(media_probe, "run_media_process", mutate)
    with pytest.raises(ValueError, match="changed"):
        await media_probe.inspect_media(str(native_env))
    assert native_env.read_bytes() == b"changed bytes"
    assert list(kept.parent.iterdir()) == [kept]
    assert (kept / "keep").read_text() == "unrelated"


@pytest.mark.parametrize("kind", ["symlink", "parent_symlink", "fifo", "uri"])
async def test_nonregular_protocol_and_parent_symlink_inputs_fail(native_env, monkeypatch, kind):
    from video_research_mcp import media_probe

    run = AsyncMock()
    monkeypatch.setattr(media_probe, "run_media_process", run)
    path = native_env.parent / "bad.mp4"
    if kind == "symlink":
        path.symlink_to(native_env)
    elif kind == "parent_symlink":
        link = native_env.parent / "linked"
        link.symlink_to(native_env.parent, target_is_directory=True)
        path = link / native_env.name
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        path = "https://example.com/video.mp4"
    with pytest.raises(PermissionError):
        await media_probe.inspect_media(str(path))
    run.assert_not_awaited()


async def test_output_fence_is_checked_before_copy(native_env, monkeypatch):
    from video_research_mcp import media_snapshot

    monkeypatch.setenv("GEMINI_CACHE_DIR", str(native_env.parent.parent / "denied-cache"))
    copy = AsyncMock()
    monkeypatch.setattr(media_snapshot, "copy_hash", copy)
    with pytest.raises(PermissionError):
        async with media_snapshot.snapshot(str(native_env)):
            pytest.fail("Denied output fence must not yield")
    copy.assert_not_awaited()


async def test_cancellation_joins_hash_thread_before_owned_cleanup(native_env, monkeypatch):
    from video_research_mcp import media_probe, media_snapshot

    started, finished = threading.Event(), threading.Event()

    def slow_copy(source, target=None, *, cancelled):
        target.write_bytes(b"partial")
        started.set()
        cancelled.wait(2)
        assert target.exists()
        finished.set()
        raise TimeoutError("controlled cancel")

    monkeypatch.setattr(media_snapshot, "_copy_hash", slow_copy)
    task = asyncio.create_task(media_probe.inspect_media(str(native_env)))
    while not started.is_set():
        await asyncio.sleep(0.001)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
    assert native_env.exists()
    assert list((native_env.parent / "cache/media/views").iterdir()) == []


async def test_delayed_video_extent_retains_container_and_stream_clocks(native_env, monkeypatch):
    from video_research_mcp import media_probe

    data = {"format": {"start_time": "3", "duration": "10"}, "streams": [
        {"codec_type": "audio", "index": 0},
        {"codec_type": "video", "index": 1, "width": 32, "height": 24,
         "start_time": "5", "duration": "4", "time_base": "1/1000"}]}
    monkeypatch.setattr(media_probe, "run_media_process", AsyncMock(return_value=(json.dumps(data).encode(), b"")))
    source = await media_probe.inspect_media(str(native_env))
    assert source["duration_seconds"] == 10
    assert source["container_start_seconds"] == 3
    assert source["stream_start_seconds"] == 5
    assert source["stream_duration_seconds"] == 4
    assert source["presentation_end_seconds"] == 6


async def test_actual_owned_wav_audio_metadata_has_no_video_clock(native_env):
    import wave
    from video_research_mcp.media_probe import inspect_media

    path = native_env.with_suffix(".wav")
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, 8000, 800, "NONE", "not compressed"))
        writer.writeframes(b"\0\0" * 800)
    result = await inspect_media(str(path))
    assert result["duration_seconds"] == pytest.approx(0.1)
    assert result["display_width"] is None
    assert result["stream_index"] is None
    assert result["time_base"] is None
    assert result["streams"][0]["sample_rate"] == "8000"


def test_missing_optional_native_binary_is_dependency_error(monkeypatch):
    from video_research_mcp import media_probe

    monkeypatch.setattr(media_probe.shutil, "which", lambda name: None)
    with pytest.raises(ImportError, match="ffprobe is unavailable"):
        media_probe.binary("ffprobe")


@pytest.mark.parametrize("sar,basis,verified,supported", [
    (None, "stored_pixel_grid_sar_unspecified", False, True),
    ("1:1", "observed_square_pixels", True, True),
    ("2:2", "observed_square_pixels", True, True),
    ("2:1", "unsupported_non_square_sample_aspect_ratio", False, False),
    ("0:1", "unsupported_non_square_sample_aspect_ratio", False, False),
    ("N/A", "unsupported_invalid_sample_aspect_ratio", False, False),
    ("1:0", "unsupported_invalid_sample_aspect_ratio", False, False),
])
async def test_aspect_metadata_distinguishes_unknown_convention_and_verified_pixels(native_env, monkeypatch, sar, basis, verified, supported):
    from video_research_mcp import media_probe

    stream = {"codec_type": "video", "index": 0, "width": 160, "height": 96, "time_base": "1/1000"}
    if sar is not None:
        stream["sample_aspect_ratio"] = sar
    data = {"streams": [stream], "format": {}}
    monkeypatch.setattr(media_probe, "run_media_process", AsyncMock(return_value=(json.dumps(data).encode(), b"")))
    source = await media_probe.inspect_media(str(native_env))
    assert source["sample_aspect_ratio"] == sar
    assert source["display_geometry_basis"] == basis
    assert source["pixel_aspect_verified"] is verified
    assert source["display_geometry_supported"] is supported
    assert (source["display_width"], source["display_height"]) == ((160, 96) if supported else (None, None))
