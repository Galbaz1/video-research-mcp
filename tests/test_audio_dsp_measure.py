"""Analytic PCM controls for finite measurements, absolute events and channel-aware A/B."""

import json
import math
import struct
import threading
import time

import pytest

from video_research_mcp.audio_dsp_measure import compare_measurements, measure_pcm
from video_research_mcp.audio_dsp_native import loudness_summary


def observed(pcm, channels=1, start=7.):
    selection = {"channels": channels, "frames": len(pcm) // (2 * channels),
                 "duration_seconds": len(pcm) / (96000 * channels),
                 "source_clock": {"first_seconds": start}}
    return measure_pcm(pcm, selection, 128, threading.Event(), time.monotonic() + 10)


def tone(amplitude, channels=1):
    return b"".join(struct.pack("<h", round(amplitude * 32768 * math.sin(2 * math.pi * frequency * i / 48000)))
                    for i in range(48000) for frequency in ([440] if channels == 1 else [440, 880]))


def test_tone_and_stereo_frequency_rms_repeat_and_finite_values():
    """Known sine amplitudes and unequal channel frequencies survive measured repetition."""
    pcm = tone(.25, 2)
    result = observed(pcm, 2)
    assert result == observed(pcm, 2)
    json.dumps(result, allow_nan=False)
    assert result["duration_seconds"] == 1 and result["frames"] == 48000
    for channel, frequency in zip(result["channels"], (440, 880)):
        assert channel["rms_linear"] == pytest.approx(.25 / math.sqrt(2), abs=1e-6)
        assert channel["dominant_frequency_hz"] == pytest.approx(frequency, abs=48000 / 2048)
    assert result["clipping"]["event_count"] == 0


def test_silence_reports_undefined_logarithms_without_infinite_numbers():
    result = observed(b"\0" * 96000)
    json.dumps(result, allow_nan=False)
    channel = result["channels"][0]
    assert channel["rms_linear"] == channel["dominant_frequency_hz"] == 0
    assert channel["rms_dbfs"] is None and channel["sample_peak_dbfs"] is None
    assert channel["logarithm_state"] == "undefined_for_silence"


def test_clipping_events_use_absolute_half_open_source_sample_times():
    samples = [0] * 48000
    samples[12000:18000] = [32767] * 6000
    samples[24000:30000] = [-32768] * 6000
    pcm = b"".join(struct.pack("<h", value) for value in samples)
    result = observed(pcm)
    assert result["clipping"]["near_full_scale_samples"] == 12000
    assert result["clipping"]["events"] == [
        {"start_seconds": 7.25, "end_seconds": 7.375, "frames": 6000},
        {"start_seconds": 7.5, "end_seconds": 7.625, "frames": 6000}]
    assert result["clipping"]["analog_clipping_verified"] is False


def test_ab_gain_difference_has_direction_and_units_without_perceptual_score():
    left, right = observed(tone(.25)), observed(tone(.125))
    result = compare_measurements(left, right)
    assert result["direction"] == "reference_minus_primary"
    assert result["paired_channels"][0]["rms_db_difference"] == pytest.approx(-6.0206, abs=.001)
    assert result["duration_seconds_difference"] == 0
    assert result["perceptual_quality_difference_verified"] is False
    assert compare_measurements(left, observed(b"\0" * 96000))["paired_channels"][0]["rms_db_difference"] is None


def test_loudness_parser_requires_terminal_fields_and_keeps_silent_peak_undefined():
    data = b"[Parsed_ebur128_0 @ 0x1] Summary:\n  Integrated loudness:\n I: -70.0 LUFS\n Loudness range:\n LRA: 0.0 LU\n True peak:\n Peak: -inf dBFS\n"
    result = loudness_summary(data)
    json.dumps(result, allow_nan=False)
    assert result["integrated_lufs"] == -70 and result["true_peak_dbfs"] is None
    assert result["undefined_fields"] == ["true_peak_dbfs"]
    assert result["standards_conformance_verified"] is False
    with pytest.raises(ValueError, match="terminal"):
        loudness_summary(b"[frame] I: -15 LUFS")
