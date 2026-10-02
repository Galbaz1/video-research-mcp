"""Complete PCM WAV reads with original-clock metadata and explicit speech abstention."""

from __future__ import annotations

import json
import math
import wave
from pathlib import Path

from .media_local_io import _open_regular
from .models.ingestion import IngestionLocation, IngestionSegment, ParsedSource


def parse_audio_source(path: Path, directory: Path) -> ParsedSource:
    """Measure every PCM16 frame; retain no inferred transcript or speaker labels."""
    with _open_regular(path) as original, wave.open(original, "rb") as reader:
        channels, rate, width = reader.getnchannels(), reader.getframerate(), reader.getsampwidth()
        if reader.getcomptype() != "NONE" or width != 2 or not (1 <= channels <= 8 and 8000 <= rate <= 192000):
            raise ValueError("Audio ingestion requires uncompressed PCM16 WAV with bounded channels/rate")
        frames, consumed = reader.getnframes(), 0
        if not 0 < frames / rate <= 600:
            raise ValueError("Audio extraction is empty or exceeds ten minutes")
        while chunk := reader.readframes(4096):
            if len(chunk) % (width * channels):
                raise ValueError("Audio extraction contains an incomplete PCM frame")
            consumed += len(chunk) // (width * channels)
        if consumed != frames:
            raise ValueError("Audio extraction frame count differs from the original header")
    descriptor = {"sample_count": consumed, "sample_rate": rate, "channels": channels,
                  "sample_width_bytes": width, "duration_seconds": frames / rate,
                  "duration_ms_policy": "ceiling of exact PCM frame duration",
                  "original_start_ms": 0, "original_end_ms": math.ceil(frames / rate * 1000),
                  "speech_transcription": "unavailable", "speaker_attribution": "unavailable"}
    artifact = directory / "audio-pcm-observation.json"
    with artifact.open("x", encoding="utf-8") as writer:
        artifact.chmod(0o600)
        json.dump(descriptor, writer, sort_keys=True, allow_nan=False)
    return ParsedSource(segments=[IngestionSegment(
        id="audio-0", kind="audio", artifact=str(artifact), method="stdlib-wave-full-pcm16-read-v1",
        location=IngestionLocation(start_ms=0, end_ms=descriptor["original_end_ms"]),
    )], limitations=["This method retains PCM timing only; speech, speakers and non-WAV decoding are unavailable"])
