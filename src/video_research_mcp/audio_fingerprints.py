"""Bounded mono PCM identities and explicitly lossy mean-MFCC audio similarity."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time

from .audio_assets import audio_limits, audio_provenance, audio_source, decode_pcm
from .config import get_config
from .image_preprocessing import check_worker, image_worker
from .media_snapshot import snapshot
from .models.scene_assets import AudioDedupRequest

FEATURE_METHOD = {"name": "mean_mfcc_cosine", "sample_rate": 8000, "channels": 1,
                  "pcm_format": "float32_little_endian", "window": "hamming", "window_samples": 256,
                  "hop_samples": 128, "fft_samples": 512, "mel_filters": 26, "coefficients": 13,
                  "dct": "orthonormal_dct_ii", "log_floor": 1e-10, "frame_aggregation": "mean",
                  "similarity_is_lossy": True, "speech_or_ordering_equality_verified": False}


def numpy_runtime():
    """Load the optional audio numerical runtime only for explicitly requested MFCC work."""
    try:
        import numpy
    except ImportError as error:
        raise ImportError("NumPy is unavailable; install video-research-mcp[audio] for audio similarity") from error
    return numpy


def _mel_filters(np):
    """Construct finite triangular filters on the declared8kHz/512-point frequency grid."""
    mel = np.linspace(0, 2595 * np.log10(1 + 4000 / 700), 28)
    bins = np.floor(513 * (700 * (10 ** (mel / 2595) - 1)) / 8000).astype(int)
    filters = np.zeros((26, 257))
    for index in range(26):
        left, center, right = bins[index:index + 3]
        if not 0 <= left < center < right <= 256:
            raise ValueError("MFCC filter grid is degenerate")
        filters[index, left:center] = np.arange(center - left) / (center - left)
        filters[index, center:right] = np.arange(right - center, 0, -1) / (right - center)
    return filters


def mfcc_fingerprint(pcm: bytes, cancelled, deadline) -> dict:
    """Reject invalid/silent PCM before a bounded, independently implemented mean-MFCC matrix."""
    check_worker(cancelled, deadline)
    np = numpy_runtime()
    if len(pcm) % 4 or not 800 <= len(pcm) // 4 <= 240000:
        raise ValueError("MFCC requires between800 and240000 complete float32 samples")
    samples = np.frombuffer(pcm, dtype="<f4")
    if not np.isfinite(samples).all():
        raise ValueError("Decoded PCM contains nonfinite samples")
    rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
    if rms <= 1e-8:
        raise ValueError("Decoded candidate is silence; MFCC similarity is undefined")
    windows = np.lib.stride_tricks.sliding_window_view(samples, 256)[::128]
    power = np.abs(np.fft.rfft(windows * np.hamming(256), n=512)) ** 2
    log_mel = np.log(power @ _mel_filters(np).T + 1e-10)
    basis = np.cos(np.pi * np.arange(13)[:, None] * (np.arange(26) + .5) / 26) * np.sqrt(2 / 26)
    basis[0] /= np.sqrt(2)
    feature = np.mean(log_mel @ basis.T, axis=0)
    if not np.isfinite(feature).all() or float(np.linalg.norm(feature)) < 1e-9:
        raise ValueError("MFCC feature is nonfinite or has no comparison norm")
    check_worker(cancelled, deadline)
    return {"feature": feature.tolist(), "rms": rms, "feature_frame_count": len(windows)}


def cosine(left: list[float], right: list[float]) -> float:
    """Compare finite nonzero13-coefficient features without claiming content equality."""
    if len(left) != 13 or len(right) != 13 or not all(math.isfinite(x) for x in left + right):
        raise ValueError("Audio similarity requires two finite13-coefficient features")
    norm = math.sqrt(sum(x * x for x in left) * sum(x * x for x in right))
    if not math.isfinite(norm) or norm < 1e-9:
        raise ValueError("Audio similarity feature has no comparison norm")
    return max(-1., min(1., sum(a * b for a, b in zip(left, right)) / norm))


async def _candidate(owned, source: dict, segment, index: int) -> dict:
    row = {"index": index, "start_seconds": segment.start_seconds, "end_seconds": segment.end_seconds,
           "status": "error", "pcm_sha256": None, "sample_count": None, "source_audio_clock": None,
           "feature": None, "rms": None, "feature_frame_count": None, "score": None,
           "duplicate_of": None, "exact_pcm_identity": False, "error": None}
    try:
        pcm, clock = await decode_pcm(owned, source, segment.start_seconds, segment.end_seconds)
        row.update(pcm_sha256=hashlib.sha256(pcm).hexdigest(), sample_count=len(pcm) // 4,
                   source_audio_clock=clock)
        row.update(await image_worker(mfcc_fingerprint, pcm, deadline=owned.deadline))
        row["status"] = "retained"
    except ValueError as error:
        row["error"] = str(error)[:512]
    except RuntimeError:
        row["error"] = "Bounded source audio decoding failed"
    return row


def _classify(candidate: dict, retained: list[dict], threshold: float) -> None:
    if candidate["status"] == "error":
        return
    for previous in retained:
        score = cosine(candidate["feature"], previous["feature"])
        candidate["score"] = max(score, candidate["score"]) if candidate["score"] is not None else score
        if score >= threshold:
            candidate.update(status="similar", score=score, duplicate_of=previous["index"],
                             exact_pcm_identity=candidate["pcm_sha256"] == previous["pcm_sha256"])
            return
    retained.append(candidate)


async def dedup_audio(request: AudioDedupRequest) -> dict:
    """Keep every candidate, its actual decoded identity and errors in a source-bound report."""
    numpy_runtime()
    timeout = min(120, get_config().media_acquire_timeout_seconds)
    deadline = time.monotonic() + timeout
    async with asyncio.timeout(timeout), snapshot(request.file_path, request.expected_source_sha256) as owned:
        owned.deadline = min(owned.deadline, deadline)
        source, candidates, retained = await audio_source(owned), [], []
        for index, segment in enumerate(request.segments):
            candidate = await _candidate(owned, source, segment, index)
            _classify(candidate, retained, request.similarity_threshold)
            candidates.append(candidate)
        counts = {"requested": len(candidates), **{name: sum(c["status"] == name for c in candidates)
                                                  for name in ("retained", "similar", "error")}}
        raw_request = request.model_dump(mode="json")
        return {"status": "partial" if counts["error"] else "complete", "source": source,
                "request": raw_request, "request_sha256": hashlib.sha256(json.dumps(
                    raw_request, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
                "candidates": candidates, "counts": counts, "feature_method": FEATURE_METHOD.copy(),
                "limits": {**audio_limits(), "max_candidates": 64, "max_candidate_seconds": 30,
                           "max_aggregate_candidate_seconds": 120, "min_candidate_samples": 800,
                           "max_feature_frames": 1874, "max_fft_bins": 257,
                           "deadline_failure": "no_result_published"},
                "provenance": {**audio_provenance("source_audio_similarity_observations"),
                               "retention_method": "first_matching_retained_representative",
                               "exact_identity_method": "decoded_pcm_sha256"}}
