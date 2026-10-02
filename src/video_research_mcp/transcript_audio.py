"""Measured audio/caption source preparation using the existing owned native policies."""

import hashlib
import json
import wave
from pathlib import Path

from .ingestion_audio import parse_audio_source
from .media_local_io import _open_regular
from .media_perception_prepare import _selection, prepare_media
from .media_probe import FORMATS, binary, probe_snapshot
from .media_process import run_media_process
from .models.media_perception import AVPerceptionLimits, AVPerceptionRequest


def audio_request(request):
    """Map the focused public request to the existing audio-only measured preparation caller."""
    return AVPerceptionRequest(file_path=request.file_path, expected_source_sha256=request.expected_source_sha256,
        instruction="Transcribe actual submitted audio only", media_type="audio", start_seconds=request.start_seconds,
        end_seconds=request.end_seconds, window_seconds=request.window_seconds, dry_run=request.dry_run,
        authorize_submission=request.authorize_submission, thinking_level=request.thinking_level,
        limits=AVPerceptionLimits(**request.limits.model_dump()))


def pcm_observation(path: Path, directory: Path) -> dict:
    """Measure all PCM16 frames, then observe exact zero samples across the entire selection."""
    directory.mkdir(mode=0o700)
    parse_audio_source(path, directory)
    observation = json.loads((directory / "audio-pcm-observation.json").read_bytes())
    with _open_regular(path) as opened, wave.open(opened, "rb") as reader:
        consumed, all_zero = 0, True
        while data := reader.readframes(4096):
            consumed += len(data) // (reader.getnchannels() * reader.getsampwidth())
            all_zero = all_zero and not any(data)
        if consumed != observation["sample_count"]:
            raise ValueError("PCM population changed between complete reads")
    return {**observation, "all_samples_exact_zero": all_zero,
            "silence_policy": "all decoded PCM16 sample bytes zero; complete population, no quiet threshold"}


async def source_clock(owned, request, directory: Path) -> tuple[dict, list]:
    """Allow caption assertions on video without forcing an audio stream to exist."""
    if owned.path.suffix == ".wav":
        pcm = pcm_observation(owned.path, directory / "source-pcm")
        source = {"path": str(owned.original), "sha256": owned.sha256, "bytes": owned.size,
            "source_revision": "sha256:" + owned.sha256, "selected_media_type": "audio",
            "audio_end_seconds": pcm["duration_seconds"], "presentation_end_seconds": pcm["duration_seconds"],
            "has_audio": True, "pcm_observation": pcm, "metadata_method": "complete_stdlib_pcm16_read"}
    else:
        source = await probe_snapshot(owned)
        video = source["stream_index"] is not None
        audio = any(s.get("codec_type") == "audio" for s in source["streams"])
        if not video and not audio:
            raise ValueError("Source has no finite audio/video caption clock")
        source.update(selected_media_type="video" if video else "audio", has_audio=audio)
    await owned.verify()
    caption_clock = {"selected_media_type": "audio", "audio_end_seconds": source["presentation_end_seconds"]}
    return source, _selection(audio_request(request), caption_clock)


async def extract_embedded(owned, caption, directory: Path) -> bytes:
    """Extract only the explicitly selected subtitle stream into owned file-only SRT output."""
    target = directory / "embedded.srt"
    command = [binary("ffmpeg"), "-nostdin", "-v", "error", "-n", "-threads", "1",
        "-protocol_whitelist", "file", "-format_whitelist", FORMATS, "-copyts", "-i", str(owned.path),
        "-map", f"0:s:{caption.embedded_track}", "-c:s", "srt", "-f", "srt", str(target)]
    await run_media_process(command, owned.remaining(), cwd=directory)
    await owned.verify()
    with _open_regular(target) as reader:
        data = reader.read(1024 * 1024 + 1)
    if not 0 < len(data) <= 1024 * 1024:
        raise ValueError("Embedded caption extraction is empty or exceeds1MiB")
    return data


def retained_window(window: dict, directory: Path, write) -> tuple[dict, dict]:
    """Persist the byte-identical selected WAV and bind complete PCM observations to its hash."""
    parts = [part for part in window["parts"] if part["kind"] == "audio"]
    if len(parts) != 1 or not window["audio"]:
        raise ValueError("ASR requires exactly one actual measured WAV per window")
    part = parts[0]
    data = part["data"]
    if hashlib.sha256(data).hexdigest() != part["sha256"] or len(data) != part["bytes"]:
        raise ValueError("Selected immutable audio bytes changed")
    artifact = write(directory, f"chunk-{window['index']}.wav", data, "selected_pcm_wav")
    measured = pcm_observation(directory / artifact["path"], directory / f"pcm-{window['index']}")
    interval = window["audio"]["selected_window"]
    if abs(measured["duration_seconds"] - (interval["end_seconds"] - interval["start_seconds"])) > 1e-6:
        raise ValueError("Measured WAV duration differs from the actual selected source clock")
    return artifact, measured


def prepared_audio(request):
    """Reuse immutable payloads, original/source readbacks and joined cleanup unchanged."""
    return prepare_media(audio_request(request))
