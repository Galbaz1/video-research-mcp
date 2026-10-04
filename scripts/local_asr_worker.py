"""Explicit loopback timed ASR using a pinned optional faster-whisper environment.

The core client validates ``answer`` with ASRAnswer. This standalone entry point
uses only stdlib until an admitted, deadline-bounded inference worker imports the
already installed model libraries. It never installs or downloads anything.
"""

if __name__ == "__main__":
    raise SystemExit("Use trusted Python -I -S -B scripts/local_asr_launch.py --entry worker")

import argparse
import base64
import hashlib
import io
import json
import math
from numbers import Real
import os
import resource
import sys
import time
import wave

from local_asr_launch import admit, file_digest as file_digest

PROTOCOL = "faster_whisper_v1"
MAX_REQUEST = 2 * 1024 * 1024
MAX_WAV = 1024 * 1024
MAX_RESPONSE = 128 * 1024
MODEL_FILES = {"config.json", "model.bin", "tokenizer.json", "vocabulary.txt"}


def json_bytes(value):
    """Encode full-precision finite JSON for the explicit wire contract."""
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()


def parse_json(raw):
    """Reject duplicate fields and nonfinite JSON at the external boundary."""
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate field")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Nonfinite JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)


def decode_request(raw):
    """Validate the bounded actual WAV and explicit language/glossary hints."""
    if len(raw) > MAX_REQUEST:
        raise ValueError("Request exceeds byte bound")
    value = parse_json(raw)
    if not isinstance(value, dict) or set(value) != {"audio", "audio_sha256", "language", "glossary"}:
        raise ValueError("Unsupported request fields")
    if value["language"] not in (None, "en", "nl"):
        raise ValueError("Unsupported language hint")
    hints = value["glossary"]
    if not isinstance(hints, list) or len(hints) > 32 or any(not isinstance(h, str) or not h.strip() or len(h) > 128 for h in hints):
        raise ValueError("Invalid glossary hints")
    audio = value["audio"]
    prefix = "data:audio/wav;base64,"
    if not isinstance(audio, str) or not audio.startswith(prefix):
        raise ValueError("Actual WAV data URI required")
    wav = base64.b64decode(audio[len(prefix):], validate=True)
    if len(wav) > MAX_WAV or hashlib.sha256(wav).hexdigest() != value["audio_sha256"]:
        raise ValueError("WAV size or identity mismatch")
    if len(wav) < 12 or wav[:4] != b"RIFF" or int.from_bytes(wav[4:8], "little") + 8 != len(wav):
        raise ValueError("WAV container extent mismatch")
    with wave.open(io.BytesIO(wav), "rb") as reader:
        if (reader.getnchannels(), reader.getsampwidth(), reader.getframerate(), reader.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError("Expected mono 16kHz signed16 PCM")
        frames = reader.getnframes()
        if not 0 < frames <= 30 * 16000:
            raise ValueError("WAV duration must be positive and at most 30s")
        pcm = reader.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError("Truncated PCM")
    return value, pcm, frames / 16000


def validate_answer(answer, duration):
    """Apply ASRAnswer population, text and finite relative interval boundaries."""
    if len(json_bytes(answer)) > MAX_RESPONSE or len(answer["segments"]) > 128:
        raise ValueError("Answer exceeds bound")
    previous = 0.0
    for cue in answer["segments"]:
        start, end = cue["start_seconds"], cue["end_seconds"]
        if not (type(start) in (int, float) and type(end) in (int, float)
                and math.isfinite(start) and math.isfinite(end) and previous <= start < end <= duration):
            raise ValueError("Invalid segment interval")
        previous = start
        if not cue["text"].strip() or len(cue["text"]) > 8192 or cue["speaker_id"] is not None or not 0 < len(cue["words"]) <= 128:
            raise ValueError("Missing or oversized actual word output")
        word_start = start
        for word in cue["words"]:
            left, right = word["start_seconds"], word["end_seconds"]
            if not (type(left) in (int, float) and type(right) in (int, float)
                    and math.isfinite(left) and math.isfinite(right) and word_start <= left < right <= end):
                raise ValueError("Invalid word interval")
            if not word["text"].strip() or len(word["text"]) > 1024:
                raise ValueError("Invalid word text")
            word_start = left
        if "".join(cue["text"].split()) != "".join("".join(w["text"].split()) for w in cue["words"]):
            raise ValueError("Word/segment text mismatch")
    if answer["outcome"] != ("transcript" if answer["segments"] else "empty") or answer["abstentions"]:
        raise ValueError("Answer population mismatch")


def wire_time(value):
    """Preserve real model scalars as JSON numbers while refusing boolean timestamps."""
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Invalid model timestamp type")
    return float(value)


def infer(request, pcm, duration, descriptor, descriptor_digest):
    """Return actual local word inference; glossary is a hotwords hint only."""
    import numpy as np
    from faster_whisper import WhisperModel

    selected = descriptor["models"]["en" if request["language"] == "en" else "multilingual"]
    started = time.monotonic()
    model = WhisperModel(selected["directory"], device="cpu", compute_type="int8", cpu_threads=4,
                         num_workers=1, local_files_only=True)
    settings = {"language": request["language"], "task": "transcribe", "beam_size": 5, "temperature": 0,
                "word_timestamps": True, "vad_filter": False, "condition_on_previous_text": False,
                "hotwords": " ".join(request["glossary"]) or None}
    segments, info = model.transcribe(np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0, **settings)
    cues = []
    for segment in segments:
        if len(cues) == 128:
            raise ValueError("Too many segments")
        cues.append({"start_seconds": wire_time(segment.start), "end_seconds": wire_time(segment.end), "text": segment.text.strip(),
                     "speaker_id": None, "words": [{"text": w.word.strip(), "start_seconds": wire_time(w.start),
                     "end_seconds": wire_time(w.end)} for w in (segment.words or [])]})
    answer = {"outcome": "transcript" if cues else "empty", "segments": cues, "abstentions": []}
    validate_answer(answer, duration)
    return {"protocol": PROTOCOL, "answer": answer, "receipt": {
        "descriptor_sha256": descriptor_digest, "script_sha256": descriptor["script_sha256"],
        "runtime_inventory_sha256": descriptor["runtime"]["inventory_sha256"],
        "model": {k: selected[k] for k in ("repo", "revision", "files")},
        "audio_sha256": request["audio_sha256"], "audio_duration_seconds": duration, "settings": settings,
        "language_observed": info.language, "effective_compute_type": model.model.compute_type,
        "elapsed_seconds": time.monotonic() - started, "worker_pid": os.getpid(),
        "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "speech_accuracy_verified": False, "word_alignment_verified": False, "speaker_identity_verified": False}}



def main():
    """Admit all selected bytes before the optional model library imports."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--descriptor", required=True)
    parser.add_argument("--expected-descriptor-sha256", required=True)
    args = parser.parse_args()
    descriptor = admit(args.descriptor, args.expected_descriptor_sha256)
    request, pcm, duration = decode_request(sys.stdin.buffer.read(MAX_REQUEST + 1))
    response = infer(request, pcm, duration, descriptor, args.expected_descriptor_sha256)
    body = json_bytes(response)
    if len(body) > MAX_RESPONSE:
        raise ValueError("Worker response exceeds bound")
    sys.stdout.buffer.write(body)
