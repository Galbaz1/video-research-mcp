"""Source-bound audio export with actual owned WAV and native-process readback."""

from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path
import struct
import wave
import asyncio

import pytest

from video_research_mcp.models.scene_assets import AudioExportRequest


@pytest.fixture(autouse=True)
def isolated_audio_config(clean_config, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


@pytest.fixture
def audio_source(tmp_path):
    """Freeze four authored one-second blocks: repeated440Hz,2800Hz and silence."""
    path = tmp_path / "owned-tones.wav"
    rate = 16000
    body = bytearray()
    for frequency in (440, 440, 2800, 0):
        body.extend(b"".join(struct.pack("<h", round(12000 * math.sin(2 * math.pi * frequency * n / rate)))
                             for n in range(rate)))
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(body)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


async def test_whole_wav_export_derives_missing_origin_and_reads_back_exact_samples(audio_source):
    from video_research_mcp.audio_assets import export_audio
    from video_research_mcp.image_manifest import read_manifest

    path, original_sha = audio_source
    result = await export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=original_sha))
    assert result["source"]["container_start_seconds"] is None
    assert result["source"]["audio_clock_origin_basis"] == "derived_first_decoded_audio_pts"
    assert result["output"]["sample_count"] == 64000
    assert result["output"]["duration_seconds"] == 4
    assert result["output"]["sample_rate"] == 16000
    assert result["artifact"]["mime"] == "audio/wav"
    assert result["source"]["sha256"] == original_sha == hashlib.sha256(path.read_bytes()).hexdigest()
    restored = await read_manifest(result["manifest"]["path"], result["manifest"]["sha256"])
    assert restored["verified"] and restored["artifact"]["sha256"] == result["artifact"]["sha256"]


@pytest.mark.parametrize(("start", "end", "samples"), [(1, None, 48000), (0, 2, 32000), (.25, .75, 8000)])
async def test_one_sided_and_half_open_selection_matches_authored_pcm(audio_source, start, end, samples):
    from video_research_mcp.audio_assets import export_audio

    path, digest = audio_source
    result = await export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=digest,
                                                  start_seconds=start, end_seconds=end))
    with wave.open(str(path), "rb") as original:
        original.setpos(round(start * 16000))
        expected = original.readframes(samples)
    assert result["output"]["sample_count"] == samples
    assert result["output"]["pcm_sha256"] == hashlib.sha256(expected).hexdigest()
    assert result["selected_window"] == {"start_seconds": start, "end_seconds": end or 4}
    assert result["source_audio_clock"]["sample_count"] == samples


async def test_repeat_export_never_overwrites_and_manifest_rejects_artifact_tamper(audio_source):
    from video_research_mcp.audio_assets import export_audio
    from video_research_mcp.image_manifest import read_manifest

    path, digest = audio_source
    request = AudioExportRequest(file_path=str(path), expected_source_sha256=digest, end_seconds=1)
    first, second = await export_audio(request), await export_audio(request)
    assert first["artifact"]["path"] != second["artifact"]["path"]
    assert first["artifact"]["sha256"] == second["artifact"]["sha256"]
    Path(first["artifact"]["path"]).write_bytes(b"altered")
    with pytest.raises(ValueError, match="(changed|digest|SHA|commitment)"):
        await read_manifest(first["manifest"]["path"], first["manifest"]["sha256"])
    assert hashlib.sha256(Path(second["artifact"]["path"]).read_bytes()).hexdigest() == second["artifact"]["sha256"]
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize(("start", "end"), [(4, None), (0, 5), (3.9, 4.1)])
async def test_outside_track_fails_and_removes_only_owned_staging(audio_source, tmp_path, start, end):
    from video_research_mcp.audio_assets import export_audio

    path, digest = audio_source
    preserved = tmp_path / "cache" / "media" / "views" / "existing"
    preserved.mkdir(parents=True)
    sentinel = preserved / "sentinel"
    sentinel.write_bytes(b"preserve")
    with pytest.raises(ValueError, match="outside"):
        await export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=digest,
                                              start_seconds=start, end_seconds=end))
    assert list(preserved.parent.iterdir()) == [preserved]
    assert sentinel.read_bytes() == b"preserve" and hashlib.sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("kind", ["digest", "symlink", "fifo", "fence", "missing", "uri"])
async def test_source_boundaries_reject_before_any_process(audio_source, tmp_path, monkeypatch, kind):
    import os
    import video_research_mcp.audio_assets as engine

    path, digest = audio_source
    if kind == "digest":
        digest = "0" * 64
    elif kind == "symlink":
        link = tmp_path / "link.wav"
        link.symlink_to(path)
        path = link
    elif kind == "fifo":
        path = tmp_path / "pipe.wav"
        os.mkfifo(path)
    elif kind == "fence":
        path = tmp_path.parent / "outside.wav"
    elif kind == "missing":
        path = tmp_path / "absent.wav"
    elif kind == "uri":
        path = "https://example.org/audio.wav"

    async def denied(*args, **kwargs):
        pytest.fail("A rejected source reached a native process")

    monkeypatch.setattr(engine, "run_media_process", denied)
    with pytest.raises((ValueError, PermissionError, FileNotFoundError)):
        await engine.export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=digest))


async def test_source_changed_during_decode_has_no_published_artifact(audio_source, monkeypatch, tmp_path):
    import video_research_mcp.audio_assets as engine

    path, digest = audio_source
    real = engine.run_media_process
    async def mutate_after_export(command, timeout, **kwargs):
        result = await real(command, timeout, **kwargs)
        if command[-1].endswith("audio.wav"):
            with path.open("ab") as writer:
                writer.write(b"changed")
        return result

    monkeypatch.setattr(engine, "run_media_process", mutate_after_export)
    with pytest.raises(ValueError, match="changed"):
        await engine.export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=digest))
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())
    assert path.exists()


async def test_cancellation_joins_process_before_owned_cleanup(audio_source, monkeypatch, tmp_path):
    import video_research_mcp.audio_assets as engine

    path, digest = audio_source
    real, entered, joined = engine.run_media_process, asyncio.Event(), asyncio.Event()
    async def blocked_export(command, timeout, **kwargs):
        if not command[-1].endswith("audio.wav"):
            return await real(command, timeout, **kwargs)
        Path(command[-1]).write_bytes(b"ownedpartial")
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            assert Path(command[-1]).exists()
            joined.set()

    monkeypatch.setattr(engine, "run_media_process", blocked_export)
    task = asyncio.create_task(engine.export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=digest)))
    await asyncio.wait_for(entered.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert joined.is_set() and not list((tmp_path / "cache" / "media" / "views").iterdir())
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


def test_measured_clock_rejects_spoofed_incomplete_gaps_and_rate_changes():
    from video_research_mcp.audio_assets import measured_audio

    def frame(n, pts, rate=8000, samples=800):
        return f"[Parsed_ashowinfo_1 @ 0xabc] n:{n} pts:{pts} pts_time:{pts / rate:g} rate:{rate} nb_samples:{samples}\n"

    actual = frame(0, 0) + frame(1, 800)
    assert measured_audio(actual.encode(), 0, 0, .2)["sample_count"] == 1600
    for bad in ("metadata: " + actual.splitlines()[0], actual.replace("pts_time:0.1", "pts_time:0.5"),
                frame(0, 0) + frame(1, 1000), frame(0, 0) + frame(1, 800, rate=16000)):
        with pytest.raises(ValueError):
            measured_audio(bad.encode(), 0, 0, 1)


async def test_missing_optional_native_binary_is_actionable(audio_source, monkeypatch):
    import video_research_mcp.media_probe as probe
    from video_research_mcp.audio_assets import export_audio

    path, digest = audio_source
    monkeypatch.setattr(probe.shutil, "which", lambda name: None)
    with pytest.raises(ImportError, match="ffprobe"):
        await export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=digest))


@pytest.mark.parametrize(("start", "end"), [(-1, None), (0, float("inf")), (2, 1), (1, 1), (True, None)])
def test_invalid_intervals_rejected_by_typed_boundary(audio_source, start, end):
    path, digest = audio_source
    with pytest.raises(ValueError):
        AudioExportRequest(file_path=str(path), expected_source_sha256=digest, start_seconds=start, end_seconds=end)


async def test_nonzero_container_origin_and_audio_only_unknown_duration(audio_source):
    from video_research_mcp.audio_assets import export_audio
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    path, _ = audio_source
    shifted = path.with_suffix(".mka")
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-i", str(path),
                             "-map", "0:a:0", "-c:a", "copy", "-output_ts_offset", "3", "-n", str(shifted)], 5)
    digest = hashlib.sha256(shifted.read_bytes()).hexdigest()
    result = await export_audio(AudioExportRequest(file_path=str(shifted), expected_source_sha256=digest,
                                                  start_seconds=1, end_seconds=2))
    assert result["source"]["container_start_seconds"] == 3
    assert result["source"]["audio_clock_origin_seconds"] == 3
    assert result["source"]["audio_clock_origin_basis"] == "observed_container_start"
    assert result["source_audio_clock"]["first_pts"] == 64000
    assert result["selected_window"] == {"start_seconds": 1, "end_seconds": 2}
    assert result["output"]["sample_count"] == 16000
    whole = await export_audio(AudioExportRequest(file_path=str(shifted), expected_source_sha256=digest))
    assert whole["source"]["audio_end_seconds"] is None
    assert whole["output"]["sample_count"] == 64000
    assert digest == hashlib.sha256(shifted.read_bytes()).hexdigest()


async def test_video_audio_export_retains_video_source_and_audio_clock(audio_source):
    from video_research_mcp.audio_assets import export_audio
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    path, _ = audio_source
    video = path.with_suffix(".mkv")
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-threads", "1",
        "-f", "lavfi", "-i", "color=c=black:s=16x16:r=2:d=4", "-i", str(path), "-map", "0:v:0",
        "-map", "1:a:0", "-c:v", "ffv1", "-threads", "1", "-c:a", "pcm_s16le", "-n", str(video)], 5)
    digest = hashlib.sha256(video.read_bytes()).hexdigest()
    result = await export_audio(AudioExportRequest(file_path=str(video), expected_source_sha256=digest,
                                                  start_seconds=.5, end_seconds=1.5))
    assert result["source"]["stored_width"] == result["source"]["stored_height"] == 16
    assert result["source"]["audio_stream_index"] == 1
    assert result["output"]["sample_count"] == 16000
    assert result["selected_window"] == {"start_seconds": .5, "end_seconds": 1.5}
    assert digest == hashlib.sha256(video.read_bytes()).hexdigest()


@pytest.mark.parametrize("seconds", [240, 241])
async def test_exact_export_duration_ceiling_not_silent_truncation(tmp_path, seconds):
    from video_research_mcp.audio_assets import export_audio

    path = tmp_path / "duration-ceiling.wav"
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        for _ in range(seconds):
            writer.writeframesraw(b"\0" * 32000)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    request = AudioExportRequest(file_path=str(path), expected_source_sha256=digest)
    if seconds == 241:
        with pytest.raises(ValueError, match="duration limit"):
            await export_audio(request)
    else:
        result = await export_audio(request)
        assert result["output"]["sample_count"] == 240 * 16000
        assert result["artifact"]["bytes"] < 8 * 1024 * 1024
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


async def test_export_cannot_attest_a_truncated_native_output(audio_source, monkeypatch, tmp_path):
    import video_research_mcp.audio_assets as engine

    path, digest = audio_source
    real = engine.run_media_process
    async def truncate(command, timeout, **kwargs):
        result = await real(command, timeout, **kwargs)
        if command[-1].endswith("audio.wav"):
            output = Path(command[-1])
            output.write_bytes(output.read_bytes()[:-200])
        return result
    monkeypatch.setattr(engine, "run_media_process", truncate)
    with pytest.raises(ValueError, match="truncated"):
        await engine.export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=digest))
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())


async def test_overall_deadline_not_restarted_for_each_native_call(audio_source, monkeypatch, tmp_path):
    """GIVEN a completed probe consuming the source deadline
    WHEN decoding follows THEN it cannot restart the deadline or retain staging."""
    import video_research_mcp.audio_assets as engine

    path, digest = audio_source
    config = engine.get_config()
    monkeypatch.setattr(config, "media_acquire_timeout_seconds", 5)
    observed, later_calls = [], []
    real_probe = engine.probe_snapshot
    async def probe_then_expire(owned):
        observed.append("probe_entered")
        assert 0 < owned.remaining() <= 5
        result = await real_probe(owned)
        # Consume this source's deadline after native entry, independent of startup speed.
        owned.deadline -= owned.remaining() + 1
        observed.append("probe_completed_deadline_expired")
        return result

    async def later_native(command, timeout, **kwargs):
        later_calls.append(command)
        pytest.fail("A later native phase restarted the expired source deadline")

    monkeypatch.setattr(engine, "probe_snapshot", probe_then_expire)
    monkeypatch.setattr(engine, "run_media_process", later_native)
    with pytest.raises(TimeoutError, match="Native media operation exceeded its configured timeout"):
        await engine.export_audio(AudioExportRequest(file_path=str(path), expected_source_sha256=digest))
    assert observed == ["probe_entered", "probe_completed_deadline_expired"]
    assert later_calls == []
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


async def encoded_mp3(path):
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    compressed = path.with_suffix(".mp3")
    await run_media_process([binary("ffmpeg"), "-v", "error", "-nostdin", "-i", str(path),
                             "-c:a", "libmp3lame", "-n", str(compressed)], 5)
    return compressed


async def whole_packet_ticks(path):
    """Return the packet span that FFmpeg 6.1 reports as the MP3 stream duration_ts."""
    from video_research_mcp.media_probe import binary
    from video_research_mcp.media_process import run_media_process

    stdout, _ = await run_media_process([binary("ffprobe"), "-v", "error", "-select_streams", "0",
                                         "-show_entries", "packet=pts,duration", "-of", "json", str(path)], 5)
    packets = json.loads(stdout)["packets"]
    return packets[-1]["pts"] + packets[-1]["duration"] - packets[0]["pts"]


def claim_whole_packets(monkeypatch, engine, ticks):
    """Replace only the audio duration claim with FFmpeg 6.1's undiscarded packet span."""
    real = engine.probe_snapshot

    async def probe(owned):
        source = await real(owned)
        stream = next(s for s in source["streams"] if s.get("codec_type") == "audio")
        stream["duration_ts"] = ticks
        stream["duration"] = f"{float(ticks * Fraction(stream['time_base'])):.6f}"
        return source
    monkeypatch.setattr(engine, "probe_snapshot", probe)


async def test_whole_mp3_has_measured_full_sample_readback(audio_source):
    from video_research_mcp.audio_assets import export_audio

    compressed = await encoded_mp3(audio_source[0])
    digest = hashlib.sha256(compressed.read_bytes()).hexdigest()
    result = await export_audio(AudioExportRequest(file_path=str(compressed), expected_source_sha256=digest))
    assert result["source"]["audio_end_seconds"] == pytest.approx(4, abs=1 / 16000)
    assert result["output"]["duration_seconds"] == 4
    assert result["output"]["sample_count"] == 64000
    assert result["selected_window"]["end_seconds"] == pytest.approx(4)
    assert digest == hashlib.sha256(compressed.read_bytes()).hexdigest()


async def test_whole_packet_mp3_duration_excludes_signalled_gapless_padding(audio_source, monkeypatch):
    """GIVEN FFmpeg 6.1's MP3 duration including encoder delay and padding
    WHEN the whole track is exported THEN only FFmpeg's signalled padding is excluded."""
    import video_research_mcp.audio_assets as engine

    compressed = await encoded_mp3(audio_source[0])
    claim_whole_packets(monkeypatch, engine, await whole_packet_ticks(compressed))
    digest = hashlib.sha256(compressed.read_bytes()).hexdigest()
    result = await engine.export_audio(AudioExportRequest(file_path=str(compressed), expected_source_sha256=digest))
    assert result["source"]["audio_duration_seconds"] > 4.05
    assert result["source"]["audio_end_basis"] == "whole_packet_duration_minus_signalled_end_padding"
    assert result["source"]["audio_end_seconds"] == pytest.approx(4, abs=1 / 16000)
    assert result["output"]["sample_count"] == 64000
    assert result["selected_window"]["end_seconds"] == pytest.approx(4)


@pytest.mark.parametrize("claim", ["reported", "whole_packets"])
async def test_truncated_mp3_remains_incomplete(audio_source, monkeypatch, claim):
    """GIVEN an MP3 missing its final 108-byte frame (17 decoded samples) that its header still claims
    WHEN the whole track is exported under either FFmpeg duration convention THEN it is incomplete."""
    import video_research_mcp.audio_assets as engine

    compressed = await encoded_mp3(audio_source[0])
    ticks = await whole_packet_ticks(compressed)
    compressed.write_bytes(compressed.read_bytes()[:-108])
    if claim == "whole_packets":
        claim_whole_packets(monkeypatch, engine, ticks)
    digest = hashlib.sha256(compressed.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="incomplete"):
        await engine.export_audio(AudioExportRequest(file_path=str(compressed), expected_source_sha256=digest))
