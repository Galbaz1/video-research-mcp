"""Actual PCM identity and lossy MFCC comparison without a dropped error denominator."""

import hashlib
import math
import struct
import wave
import threading
import time
import builtins

import pytest

from video_research_mcp.models.scene_assets import AudioDedupRequest


@pytest.fixture(autouse=True)
def isolated_audio_config(clean_config, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


@pytest.fixture
def tone_source(tmp_path):
    """Freeze authored repeated440Hz/distinct2800Hz/silent blocks before candidate inference."""
    path, rate = tmp_path / "owned-tones.wav", 16000
    body = b"".join(struct.pack("<h", round(12000 * math.sin(2 * math.pi * frequency * n / rate)))
                    for frequency in (440, 440, 2800, 0) for n in range(rate))
    with wave.open(str(path), "wb") as writer:
        writer.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        writer.writeframes(body)
    return path, hashlib.sha256(path.read_bytes()).hexdigest()


async def test_repeated_distinct_and_silent_candidates_keep_original_denominator(tone_source):
    from video_research_mcp.audio_fingerprints import dedup_audio

    path, digest = tone_source
    segments = [{"start_seconds": index + .1, "end_seconds": index + .9} for index in range(4)]
    result = await dedup_audio(AudioDedupRequest(file_path=str(path), expected_source_sha256=digest,
                                                segments=segments))
    assert result["counts"] == {"requested": 4, "retained": 2, "similar": 1, "error": 1}
    first, repeat, distinct, silent = result["candidates"]
    assert repeat["duplicate_of"] == first["index"] == 0
    assert repeat["pcm_sha256"] == first["pcm_sha256"] and repeat["exact_pcm_identity"]
    assert repeat["score"] > .999999
    assert distinct["status"] == "retained" and distinct["score"] < .95
    assert silent["status"] == "error" and "silence" in silent["error"].lower()
    assert silent["sample_count"] == first["sample_count"] == 6400
    assert result["status"] == "partial" and len(result["candidates"]) == 4
    assert digest == hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("body", [b"bad", b"\0" * (799 * 4), b"\0" * (240001 * 4),
                                  struct.pack("<f", float("nan")) * 800,
                                  struct.pack("<f", float("inf")) * 800, b"\0" * (800 * 4)])
def test_invalid_too_short_nonfinite_or_silent_pcm_cannot_become_similarity(body):
    from video_research_mcp.audio_fingerprints import mfcc_fingerprint

    with pytest.raises(ValueError):
        mfcc_fingerprint(body, threading.Event(), time.monotonic() + 5)


def test_exact_pcm_identity_distinct_from_lossy_mean_mfcc():
    from video_research_mcp.audio_fingerprints import cosine, mfcc_fingerprint

    pcm = b"".join(struct.pack("<f", math.sin(2 * math.pi * 440 * n / 8000)) for n in range(2048))
    inverted = b"".join(struct.pack("<f", -math.sin(2 * math.pi * 440 * n / 8000)) for n in range(2048))
    left = mfcc_fingerprint(pcm, threading.Event(), time.monotonic() + 5)
    right = mfcc_fingerprint(inverted, threading.Event(), time.monotonic() + 5)
    assert hashlib.sha256(pcm).digest() != hashlib.sha256(inverted).digest()
    assert cosine(left["feature"], right["feature"]) > .999999
    assert len(left["feature"]) == 13 and left["feature_frame_count"] == 15


async def test_candidate_errors_preserve_indices_and_sample_evidence(tone_source):
    from video_research_mcp.audio_fingerprints import dedup_audio

    path, digest = tone_source
    result = await dedup_audio(AudioDedupRequest(file_path=str(path), expected_source_sha256=digest,
        segments=[{"start_seconds": .1, "end_seconds": .15}, {"start_seconds": 10, "end_seconds": 11},
                  {"start_seconds": .1, "end_seconds": .9}, {"start_seconds": 1.1, "end_seconds": 1.9}]))
    assert result["counts"] == {"requested": 4, "retained": 1, "similar": 1, "error": 2}
    short, outside, retained, repeat = result["candidates"]
    assert short["sample_count"] == 400 and short["pcm_sha256"] is not None
    assert outside["sample_count"] is None and "outside" in outside["error"]
    assert repeat["duplicate_of"] == retained["index"] == 2
    assert [row["index"] for row in result["candidates"]] == [0, 1, 2, 3]


async def test_unknown_decode_failure_is_not_a_silent_skipped_candidate(tone_source, monkeypatch):
    import video_research_mcp.audio_fingerprints as engine

    path, digest = tone_source
    async def failed(*args):
        raise RuntimeError("untrusted ffmpeg body must not escape")
    monkeypatch.setattr(engine, "decode_pcm", failed)
    result = await engine.dedup_audio(AudioDedupRequest(file_path=str(path), expected_source_sha256=digest,
                            segments=[{"start_seconds": .1, "end_seconds": .9}]))
    assert result["counts"]["requested"] == result["counts"]["error"] == 1
    assert result["candidates"][0]["error"] == "Bounded source audio decoding failed"


def test_missing_numpy_is_actionable_optional_runtime_error(monkeypatch):
    from video_research_mcp.audio_fingerprints import numpy_runtime

    real_import = builtins.__import__
    def absent(name, *args, **kwargs):
        if name == "numpy":
            raise ImportError("controlled absence")
        return real_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", absent)
    with pytest.raises(ImportError, match=r"\[audio\]"):
        numpy_runtime()


def test_cancellation_prevents_feature_publication():
    from video_research_mcp.audio_fingerprints import mfcc_fingerprint

    canceled = threading.Event()
    canceled.set()
    with pytest.raises(TimeoutError):
        mfcc_fingerprint(b"\0" * 3200, canceled, time.monotonic() + 5)


@pytest.mark.parametrize("segments", [[], [{"start_seconds": 0, "end_seconds": 31}],
    [{"start_seconds": 0, "end_seconds": 1}] * 65, [{"start_seconds": 0, "end_seconds": 30}] * 5,
    [{"start_seconds": float("nan"), "end_seconds": 1}], [{"start_seconds": True, "end_seconds": 1}]])
def test_candidate_and_aggregate_limits_reject_before_decode(tone_source, segments):
    path, digest = tone_source
    with pytest.raises(ValueError):
        AudioDedupRequest(file_path=str(path), expected_source_sha256=digest, segments=segments)


@pytest.mark.parametrize(("left", "right"), [([0.] * 13, [1.] * 13), ([float("nan")] * 13, [1.] * 13),
                                             ([1e308] * 13, [1e308] * 13), ([1.] * 12, [1.] * 13)])
def test_invalid_comparison_features_cannot_become_passing_similarity(left, right):
    from video_research_mcp.audio_fingerprints import cosine

    with pytest.raises(ValueError):
        cosine(left, right)


async def test_source_revalidation_prevents_publishing_features(tone_source, monkeypatch, tmp_path):
    import video_research_mcp.audio_fingerprints as engine

    path, digest = tone_source
    real_decode = engine.decode_pcm
    async def changed(*args):
        result = await real_decode(*args)
        with path.open("ab") as writer:
            writer.write(b"changed")
        return result
    monkeypatch.setattr(engine, "decode_pcm", changed)
    with pytest.raises(ValueError, match="changed"):
        await engine.dedup_audio(AudioDedupRequest(file_path=str(path), expected_source_sha256=digest,
            segments=[{"start_seconds": .1, "end_seconds": .9}]))
    assert not list((tmp_path / "cache" / "media" / "views").iterdir())
