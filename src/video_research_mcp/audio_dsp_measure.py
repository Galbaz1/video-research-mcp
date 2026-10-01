"""Finite PCM measurements and A/B differences with declared units and limitations."""

import math

from .audio_fingerprints import numpy_runtime
from .image_preprocessing import check_worker
from .audio_dsp_pcm import RATE

FFT = 2048
HOP = 512


def spectrum(samples, cancelled, deadline):
    """Average Hann-window power in chunks without materializing a full STFT matrix."""
    np = numpy_runtime()
    count = (len(samples) - FFT) // HOP + 1
    total = np.zeros((FFT // 2 + 1, samples.shape[1]), dtype=np.float64)
    window = np.hanning(FFT)[:, None]
    for offset in range(0, count, 64):
        check_worker(cancelled, deadline)
        for index in range(offset, min(count, offset + 64)):
            frame = samples[index * HOP : index * HOP + FFT]
            total += np.abs(np.fft.rfft(frame * window, axis=0)) ** 2
    return total / count, count


def clipping_events(samples, start, maximum):
    """Retain the full sample count and a bounded near-full-scale event population."""
    np = numpy_runtime()
    hits = np.any(np.abs(samples) >= 32767 / 32768, axis=1)
    boundaries = np.diff(np.concatenate(([False], hits, [False])).astype(np.int8))
    starts, ends = np.flatnonzero(boundaries == 1), np.flatnonzero(boundaries == -1)
    events = [
        {
            "start_seconds": start + int(a) / RATE,
            "end_seconds": start + int(b) / RATE,
            "frames": int(b - a),
        }
        for a, b in zip(starts[:maximum], ends[:maximum])
    ]
    return {
        "near_full_scale_samples": int(np.sum(np.abs(samples) >= 32767 / 32768)),
        "near_full_scale_frames": int(np.sum(hits)),
        "event_count": len(starts),
        "events": events,
        "events_truncated": len(starts) > maximum,
        "threshold_linear": 32767 / 32768,
        "method": "integer_pcm_near_full_scale_runs",
        "analog_clipping_verified": False,
    }


def channel_measurement(np, values, power, frequency, index):
    """Measure one actual channel with explicit undefined silent logarithms."""
    rms, peak = float(np.sqrt(np.mean(values**2))), float(np.max(np.abs(values)))
    energy = float(np.sum(power))
    return {
        "channel": index,
        "rms_linear": rms,
        "sample_peak_linear": peak,
        "rms_dbfs": 20 * math.log10(rms) if rms else None,
        "sample_peak_dbfs": 20 * math.log10(peak) if peak else None,
        "logarithm_state": "finite" if rms else "undefined_for_silence",
        "dominant_frequency_hz": float(frequency[int(np.argmax(power))]) if energy else 0.0,
        "spectral_centroid_hz": float(np.sum(frequency * power) / energy) if energy else 0.0,
    }


def measure_pcm(pcm, selection, maximum_events, cancelled, deadline):
    """Measure exact selected samples without converting silent logarithms to infinities."""
    np = numpy_runtime()
    samples = (
        np.frombuffer(pcm, dtype="<i2").astype(np.float64).reshape(-1, selection["channels"])
        / 32768
    )
    power, count = spectrum(samples, cancelled, deadline)
    frequency = np.fft.rfftfreq(FFT, 1 / RATE)
    channels = [
        channel_measurement(np, samples[:, i], power[:, i], frequency, i)
        for i in range(samples.shape[1])
    ]
    check_worker(cancelled, deadline)
    return {
        "duration_seconds": selection["duration_seconds"],
        "frames": selection["frames"],
        "sample_rate_hz": RATE,
        "channels": channels,
        "clipping": clipping_events(
            samples, selection["source_clock"]["first_seconds"], maximum_events
        ),
        "spectrum": {
            "fft_samples": FFT,
            "hop_samples": HOP,
            "window": "hann",
            "frames": count,
            "frequency_bin_hz": RATE / FFT,
            "power_role": "relative_windowed_pcm_power",
        },
        "units": {
            "duration": "seconds",
            "frequency": "Hz",
            "rms": "linear_full_scale_and_dBFS",
            "peak": "sample_peak_linear_full_scale_and_dBFS",
            "clipping_events": "absolute_source_seconds",
        },
    }


def compare_measurements(left, right):
    """Report right-minus-left measurements; unequal channel layouts remain explicit."""
    rows = []
    for a, b in zip(left["channels"], right["channels"]):
        rows.append(
            {
                "channel": a["channel"],
                "rms_linear_difference": b["rms_linear"] - a["rms_linear"],
                "rms_db_difference": b["rms_dbfs"] - a["rms_dbfs"]
                if a["rms_dbfs"] is not None and b["rms_dbfs"] is not None
                else None,
                "sample_peak_linear_difference": b["sample_peak_linear"] - a["sample_peak_linear"],
                "dominant_frequency_hz_difference": b["dominant_frequency_hz"]
                - a["dominant_frequency_hz"],
                "spectral_centroid_hz_difference": b["spectral_centroid_hz"]
                - a["spectral_centroid_hz"],
            }
        )
    return {
        "direction": "reference_minus_primary",
        "duration_seconds_difference": right["duration_seconds"] - left["duration_seconds"],
        "channel_count_primary": len(left["channels"]),
        "channel_count_reference": len(right["channels"]),
        "paired_channels": rows,
        "clipped_sample_count_difference": right["clipping"]["near_full_scale_samples"]
        - left["clipping"]["near_full_scale_samples"],
        "perceptual_quality_difference_verified": False,
    }
