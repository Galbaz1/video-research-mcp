"""Exact-source bounded audio extraction and independently read-back PCM WAV artifacts."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
import time
import wave
from fractions import Fraction

from .config import get_config
from .image_manifest import write_manifest
from .image_preprocessing import check_worker, image_worker
from .media_clip_timing import source_audio
from .media_local_io import _open_regular
from .media_probe import FORMATS, binary, finite, probe_snapshot
from .media_process import run_media_process
from .media_snapshot import snapshot
from .models.scene_assets import AudioExportRequest

MAX_AUDIO_SECONDS = 240
MAX_AUDIO_BYTES = 8 * 1024 * 1024
CLOCK_TOLERANCE = 1 / 16000


def audio_command(owned, stream_index: int) -> list[str]:
    """Disable network demuxing and preserve source timestamps before audio filtering."""
    return [binary("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info",
            "-max_alloc", "67108864", "-threads", "1", "-protocol_whitelist", "file,pipe",
            "-format_whitelist", FORMATS, "-copyts", "-i", str(owned.path),
            "-map", f"0:{stream_index}", "-vn", "-map_metadata", "-1", "-threads", "1"]


def measured_audio(stderr: bytes, origin: float, start: float, end: float) -> dict:
    """Bind decoded sample totals to anchored filter clocks and reject source gaps."""
    clock = source_audio(stderr, origin, start - 1 / 8000, end + 1 / 8000)
    pattern = r"\[Parsed_ashowinfo_\d+ @ (?:0x)?[0-9a-fA-F]+\]\s+.*\bnb_samples:(\d+)\b.*"
    samples = sum(int(match[1]) for line in stderr.decode(errors="replace").splitlines()
                  if (match := re.fullmatch(pattern, line)))
    rates = set(re.findall(r"\brate:(\d+)\b", "\n".join(
        line for line in stderr.decode(errors="replace").splitlines() if re.fullmatch(pattern, line))))
    if rates != {str(clock["sample_rate"])}:
        raise ValueError("Decoded audio sample rate changed during extraction")
    duration = samples / clock["sample_rate"]
    if abs(clock["end_seconds"] - clock["first_seconds"] - duration) > 1e-6:
        raise ValueError("Decoded audio contains clock gaps; continuous PCM export is unsupported")
    return {**clock, "sample_count": samples, "duration_seconds": duration}


async def audio_source(owned) -> dict:
    """Measure a real decoded audio origin while retaining absent container metadata."""
    source = await probe_snapshot(owned)
    stream = next((s for s in source["streams"] if s.get("codec_type") == "audio"), None)
    if stream is None:
        raise ValueError("Source contains no audio stream")
    index, rate, channels = (int(stream[k]) for k in ("index", "sample_rate", "channels"))
    clock = Fraction(stream["time_base"])
    if index < 0 or not 1 <= rate <= 192000 or not 1 <= channels <= 32 or clock <= 0:
        raise ValueError("Audio stream metadata exceeds the bounded extraction contract")
    command = audio_command(owned, index) + ["-af", "aresample=16000,ashowinfo", "-frames:a", "1",
                                           "-ac", "1", "-f", "null", "-"]
    _, stderr = await run_media_process(command, owned.remaining())
    first = measured_audio(stderr, 0, -1e12, 1e12)
    origin = source["container_start_seconds"]
    basis = "observed_container_start"
    if origin is None:
        origin, basis = first["first_seconds"], "derived_first_decoded_audio_pts"
    duration = finite(stream.get("duration"))
    if duration is None and stream.get("duration_ts") is not None:
        duration = float(int(stream["duration_ts"]) * clock)
    start = finite(stream.get("start_time"))
    end = start - origin + duration if start is not None and duration is not None else None
    if start is None and duration is not None:
        end = first["first_seconds"] - origin + duration
    return {**source, "audio_stream_index": index, "audio_sample_rate": rate,
            "audio_channels": channels, "audio_time_base": str(clock), "audio_start_seconds": start,
            "audio_duration_seconds": duration, "audio_end_seconds": end,
            "audio_clock_origin_seconds": origin, "audio_clock_origin_basis": basis,
            "first_audio_seconds": first["first_seconds"] - origin,
            "first_audio_pts": first["first_pts"], "first_audio_pts_time_base": "1/16000",
            "audio_origin_method": "first_decoded_resampled_audio_pts"}


def audio_window(source: dict, start: float, end: float | None, maximum: float) -> tuple[float, bool]:
    """Resolve whole/remaining tracks; unknown ends receive one extra sample as a truncation guard."""
    known_end = source["audio_end_seconds"]
    first = max(start, source["first_audio_seconds"])
    if known_end is not None and start >= known_end:
        raise ValueError("Audio selection starts outside the source audio track")
    if end is not None:
        if known_end is not None and end > known_end + CLOCK_TOLERANCE:
            raise ValueError("Audio selection ends outside the source audio track")
        resolved, guarded = end, False
    elif known_end is not None:
        resolved, guarded = known_end, False
    else:
        resolved, guarded = first + maximum + CLOCK_TOLERANCE, True
    if resolved <= first or (not guarded and resolved - first > maximum):
        raise ValueError("Audio selection is empty or exceeds the decoded duration limit")
    return resolved, guarded


def audio_filter(source: dict, start: float, end: float, rate: int, *, reset: bool = False) -> str:
    """Trim on the measured source clock and observe resampled PTS before any output reset."""
    origin = source["audio_clock_origin_seconds"]
    filters = f"atrim=start={origin + start:.12f}:end={origin + end:.12f},aresample={rate},ashowinfo"
    return filters + (",asetpts=PTS-STARTPTS" if reset else "")


def validate_audio(clock: dict, source: dict, start: float, end: float, rate: int, guarded: bool) -> None:
    """Reject empty, incomplete and truncated selections without treating metadata as decoded proof."""
    tolerance = max(1 / rate, CLOCK_TOLERANCE)
    target_start = max(start, source["first_audio_seconds"])
    if clock["sample_rate"] != rate or abs(clock["first_seconds"] - target_start) > tolerance:
        raise ValueError("Decoded audio does not reach the requested source start")
    if not guarded and abs(clock["end_seconds"] - end) > tolerance:
        raise ValueError("Decoded audio is incomplete or outside the requested source end")


async def decode_pcm(owned, source: dict, start: float, end: float) -> tuple[bytes, dict]:
    """Decode one explicit <=30-second candidate to bounded8kHz mono float32 bytes."""
    resolved, guarded = audio_window(source, start, end, 30)
    command = audio_command(owned, source["audio_stream_index"]) + [
        "-af", audio_filter(source, start, resolved, 8000), "-ac", "1", "-ar", "8000",
        "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1"]
    pcm, stderr = await run_media_process(command, owned.remaining())
    measured = measured_audio(stderr, source["audio_clock_origin_seconds"], start, resolved)
    validate_audio(measured, source, start, resolved, 8000, guarded)
    if len(pcm) % 4 or not 1 <= len(pcm) // 4 <= 240000 or len(pcm) // 4 != measured["sample_count"]:
        raise ValueError("Decoded PCM byte count differs from its observed sample clock")
    return pcm, measured


def wav_readback(path, cancelled, deadline) -> tuple[dict, str, int]:
    """Bind full WAV PCM and file hashes to one bounded immutable byte read."""
    check_worker(cancelled, deadline)
    with _open_regular(path) as reader:
        data = reader.read(MAX_AUDIO_BYTES + 1)
    if len(data) > MAX_AUDIO_BYTES:
        raise ValueError("Exported WAV exceeds the8MiB artifact limit")
    output = _wav_samples(io.BytesIO(data), cancelled, deadline)
    return output, hashlib.sha256(data).hexdigest(), len(data)


def _wav_samples(reader, cancelled, deadline) -> dict:
    """Hash every stored PCM sample and reject a header that overstates the available body."""
    with wave.open(reader, "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("Exported audio is not16kHz mono16-bit PCM WAV")
        expected, total, digest = audio.getnframes(), 0, hashlib.sha256()
        if not 1 <= expected <= MAX_AUDIO_SECONDS * 16000:
            raise ValueError("Exported audio exceeds the240-second sample budget")
        while body := audio.readframes(4096):
            check_worker(cancelled, deadline)
            total += len(body)
            digest.update(body)
            if total > MAX_AUDIO_BYTES or len(body) % 2:
                raise ValueError("Exported PCM body is oversized or malformed")
        if total != expected * 2:
            raise ValueError("Exported WAV has a truncated sample body")
    return {"sample_count": expected, "duration_seconds": expected / 16000,
            "sample_rate": 16000, "channels": 1, "sample_format": "signed16_little_endian",
            "pcm_sha256": digest.hexdigest(), "readback_method": "stdlib_wave_full_sample_body"}


async def _export(owned, request: AudioExportRequest, source: dict) -> dict:
    end, guarded = audio_window(source, request.start_seconds, request.end_seconds, MAX_AUDIO_SECONDS)
    path = owned.directory / "audio.wav"
    command = audio_command(owned, source["audio_stream_index"]) + [
        "-af", audio_filter(source, request.start_seconds, end, 16000, reset=True),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", "-fs", str(MAX_AUDIO_BYTES),
        "-f", "wav", "-n", str(path)]
    _, stderr = await run_media_process(command, owned.remaining())
    measured = measured_audio(stderr, source["audio_clock_origin_seconds"], request.start_seconds, end)
    validate_audio(measured, source, request.start_seconds, end, 16000, guarded)
    output, digest, size = await image_worker(wav_readback, path, deadline=owned.deadline)
    if measured["sample_count"] != output["sample_count"]:
        raise ValueError("Exported WAV sample count differs from the selected source audio")
    artifact = {"path": str(path), "sha256": digest, "bytes": size, "mime": "audio/wav", "role": "audio"}
    raw_request = request.model_dump(mode="json")
    result = {"status": "complete", "source": source, "artifact": artifact, "artifacts": [artifact],
              "requested_window": {"start_seconds": request.start_seconds, "end_seconds": request.end_seconds},
              "selected_window": {"start_seconds": measured["first_seconds"], "end_seconds": measured["end_seconds"]},
              "source_audio_clock": measured, "output": output, "request": raw_request,
              "request_sha256": hashlib.sha256(json.dumps(raw_request, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest(),
              "limits": audio_limits(), "provenance": audio_provenance("extracted_source_audio"),
              "clock_relationship": {"output_origin_seconds": 0, "source_origin_seconds": measured["first_seconds"],
                                     "tolerance_seconds": CLOCK_TOLERANCE, "sample_count_verified": True}}
    result["manifest"] = await write_manifest(result, owned.directory)
    return result


def audio_limits() -> dict:
    """Declare measured work/output bounds without claiming a process RSS ceiling."""
    return {"max_export_seconds": MAX_AUDIO_SECONDS, "max_artifact_bytes": MAX_AUDIO_BYTES,
            "max_process_pipe_bytes": 1048576, "max_decoded_audio_frames": 4096,
            "overall_timeout_seconds": min(120, get_config().media_acquire_timeout_seconds),
            "max_single_allocation_bytes": 67108864, "source_max_bytes": get_config().media_max_input_bytes,
            "continuous_audio_required": True, "decoded_quality_verified": False}


def audio_provenance(output_class: str) -> dict:
    """Distinguish source-derived audio from generated media and unverified source origin."""
    return {"origin": "source_derived", "output_class": output_class, "newly_generated_media": False,
            "original_source_synthetic_status": "unverified", "audio_stream_selection": "first_audio_stream"}


async def export_audio(request: AudioExportRequest) -> dict:
    """Export a whole, remaining or explicitly selected local audio track with exact readback."""
    timeout = min(120, get_config().media_acquire_timeout_seconds)
    deadline = time.monotonic() + timeout
    async with asyncio.timeout(timeout), snapshot(request.file_path, request.expected_source_sha256) as owned:
        owned.deadline = min(owned.deadline, deadline)
        return await _export(owned, request, await audio_source(owned))
