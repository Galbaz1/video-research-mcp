"""Measured stdlib PCM/sample controls; no native process or playback occurs."""

from array import array
from contextlib import contextmanager
import math
import os
from pathlib import Path
import struct

import pytest

from video_explainer_mcp import narration_pcm as pcm


def test_actual_mock_events_and_quantized_final_pause():
    first, words_a = pcm.tone("One. ", 1)
    second, words_b = pcm.tone("Two.", 1)
    _, a = pcm.qualify(first)
    assert a["frames"] == 4800 and a["sample_rate"] == 24000
    assert (a["channels"], a["sample_width"]) == (1, 2)
    assert words_a == [{"word": "One.", "text_begin": 0, "text_end": 4, "start_frame": 0,
                        "end_frame": 4800, "alignment": "synthetic_event"}]
    assert words_b[0]["end_frame"] == 4800
    combined, intervals = pcm.concatenate([first, second], 0.1)
    samples, measured = pcm.qualify(combined)
    assert measured["frames"] == 14400 and measured["duration_seconds"] == 0.6
    assert intervals == [{"start_frame": 0, "audio_end_frame": 4800, "end_frame": 7200, "pause_frames": 2400},
                         {"start_frame": 7200, "audio_end_frame": 12000, "end_frame": 14400, "pause_frames": 2400}]
    assert samples[4800 * 2:7200 * 2] == bytes(2400 * 2)
    assert samples[-2400 * 2:] == bytes(2400 * 2)
    assert -40 < measured["quality"]["rms_dbfs"] < -6 and measured["quality"]["clipped_samples"] == 0


def test_rate_and_pause_account_for_every_actual_sample():
    clips = [pcm.tone(text, 2)[0] for text in ("One.", "Two.")]
    combined, intervals = pcm.concatenate(clips, 0.1)
    assert pcm.qualify(combined)[1]["frames"] == 9600
    assert intervals[1]["start_frame"] == 4800 and intervals[1]["audio_end_frame"] == 7200
    combined, intervals = pcm.concatenate(clips, 0.10003)
    assert intervals[0]["pause_frames"] == 2401
    assert pcm.qualify(combined)[1]["frames"] == 9602


def test_rms_peak_and_clipped_count_are_measured_not_lufs():
    body = pcm.wav(array("h", [1000, -1000] * 10).tobytes())
    _, measured = pcm.decode(body)
    assert measured["quality"]["rms_dbfs"] == pytest.approx(20 * math.log10(1000 / 32768))
    assert measured["quality"]["peak"] == 1000 / 32768
    assert measured["quality"]["measurement"] == "RMS dBFS, not LUFS"
    clipped = pcm.wav(array("h", [32767, -32768, 1234]).tobytes())
    assert pcm.decode(clipped)[1]["quality"]["clipped_samples"] == 2
    with pytest.raises(ValueError, match="quality"):
        pcm.qualify(clipped)


@pytest.mark.parametrize("kind", ["empty", "silence", "quiet", "header", "truncated", "riff_size", "stereo", "width", "odd_data"])
def test_bad_media_refuses_quality_acceptance(kind):
    body = pcm.tone("One.", 1)[0]
    if kind == "empty":
        body = pcm.wav(b"")
    elif kind == "silence":
        body = pcm.wav(bytes(9600))
    elif kind == "quiet":
        body = pcm.wav(array("h", [1] * 4800).tobytes())
    elif kind == "header":
        body = b"not a wav"
    elif kind == "truncated":
        body = body[:-1]
    elif kind == "riff_size":
        body = body[:4] + struct.pack("<I", 42) + body[8:]
    elif kind == "stereo":
        body = body[:22] + struct.pack("<H", 2) + body[24:]
    elif kind == "width":
        body = body[:34] + struct.pack("<H", 8) + body[36:]
    else:
        body = body[:4] + struct.pack("<I", len(body) - 6) + body[8:40] + struct.pack("<I", len(body) - 43) + body[44:] + b"\0\0"
    with pytest.raises(ValueError):
        pcm.qualify(body)


def test_mixed_formats_are_refused_and_fresh_binary_write_preserves_existing(tmp_path):
    body = pcm.tone("One.", 1)[0]
    samples, _ = pcm.qualify(body)
    with pytest.raises(ValueError, match="Mixed"):
        pcm.concatenate([body, pcm.wav(samples, 32000)], 0.1)
    target = tmp_path / "owned.wav"
    pcm.atomic_bytes(target, body)
    assert pcm.snapshot(target) == body
    with pytest.raises(ValueError, match="preserved"):
        pcm.atomic_bytes(target, pcm.tone("Two.", 1)[0])
    assert pcm.artifact(target, tmp_path, body)["path"] == "owned.wav"


def test_containment_fifo_and_mutation_do_not_become_audio(tmp_path, monkeypatch):
    target = tmp_path / "source.wav"
    target.write_bytes(pcm.tone("One.", 1)[0])
    link = tmp_path / "link.wav"
    link.symlink_to(target)
    for path in ("../outside.wav", str(target), "link.wav"):
        with pytest.raises(ValueError):
            pcm.contained(tmp_path, path)
    fifo = tmp_path / "fifo.wav"
    os.mkfifo(fifo)
    with pytest.raises(ValueError, match="regular"):
        pcm.snapshot(fifo)
    original = pcm.open_regular
    @contextmanager
    def mutating(path: Path):
        with original(path) as pair:
            yield pair
            path.write_bytes(b"changed")
    monkeypatch.setattr(pcm, "open_regular", mutating)
    with pytest.raises(ValueError, match="changed"):
        pcm.snapshot(target)
