"""Hash-bound legacy WAV admission and exact measured scene-segment PCM assembly."""

import hashlib
import io
import re
import wave
from pathlib import Path
from urllib.parse import urlparse

from .audio_dsp_pcm import read_pcm
from .education_domain import source_gate
from .education_review import read_bytes, riff_gate, safe_path, strict_json
from .education_timing import IDS, timeline_from_counts
from .image_preprocessing import check_worker
from .models.education import LESSON_INPUT


def digest(body, expected):
    """Require the independently supplied complete byte commitment."""
    if not isinstance(expected, str) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise ValueError("Lesson requires an explicit full expected SHA256")
    if hashlib.sha256(body).hexdigest() != expected:
        raise ValueError("Lesson exact expected SHA256 differs from actual bytes")


def measure_wav(body, path):
    """Inspect complete PCM from admitted RIFF bytes without a second mutable file read."""
    riff_gate(body, expected_samples=None)
    with wave.open(io.BytesIO(body), "rb") as reader:
        count = reader.getnframes()
        pcm = reader.readframes(count + 1)
    if len(pcm) != count * 2:
        raise ValueError("Narration segment has an incomplete PCM population")
    return pcm, {"path": str(path), "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body),
                 "pcm_sha256": hashlib.sha256(pcm).hexdigest(), "frames": count,
                 "sample_rate": 48000, "channels": 1, "sample_format": "signed16_little_endian",
                 "duration_seconds": count / 48000, "mime": "audio/wav", "role": "selected_audio"}


def _segments(spec, parent, cancelled, deadline):
    """Bind each complete original and concatenate only its actual PCM in scene order."""
    if [s.scene_id for s in spec.narration_segments] != IDS:
        raise ValueError("Narration requires exactly triangle,curve,circuit segments in order")
    bodies, originals, measured, samples = {}, {}, [], []
    for segment in spec.narration_segments:
        check_worker(cancelled, deadline)
        if urlparse(segment.path).scheme:
            raise PermissionError("Local paths must be filesystem paths, not URIs")
        relative = Path(segment.path)
        path = safe_path(relative if relative.is_absolute() else parent / relative)
        body = read_bytes(path, 8388608, cancelled, deadline)
        digest(body, segment.sha256)
        pcm, record = measure_wav(body, path)
        record["scene_id"] = segment.scene_id
        measured.append(record)
        samples.append(pcm)
        bodies[f"segment-{segment.scene_id}.wav"] = body
        originals[f"segment_{segment.scene_id}"] = {"path": str(path), "sha256": segment.sha256, "bytes": len(body)}
        if sum(len(b) for b in bodies.values()) > 8388608:
            raise ValueError("Narration segment WAV population exceeds8MiB")
    timeline = timeline_from_counts([m["frames"] for m in measured])
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(48000)
        writer.writeframes(b"".join(samples))
    audio_body = buffer.getvalue()
    _, audio = measure_wav(audio_body, "narration.wav")
    audio.update(segments=measured, timeline=timeline)
    check_worker(cancelled, deadline)
    return audio_body, audio, originals, bodies


def admit(spec_path, spec_sha, audio_path, audio_sha, cancelled, deadline):
    """Select the typed caller route before any native work or output allocation."""
    spec_path = safe_path(spec_path)
    source = read_bytes(spec_path, 131072, cancelled, deadline)
    digest(source, spec_sha)
    value = strict_json(source)
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise ValueError("Lesson schema_version must be an exact integer")
    spec = LESSON_INPUT.validate_python(value)
    originals = {"spec": {"path": str(spec_path), "sha256": spec_sha, "bytes": len(source)}}
    if spec.schema_version == 1:
        if audio_path is None or audio_sha is None:
            raise ValueError("Schema1 requires explicit audio_path and expected_audio_sha256")
        audio_path = safe_path(audio_path)
        audio_body = read_bytes(audio_path, 8388608, cancelled, deadline)
        digest(audio_body, audio_sha)
        riff_gate(audio_body)
        _, audio = read_pcm(audio_path, 1, cancelled, deadline)
        if audio["sha256"] != audio_sha:
            raise ValueError("Narration bytes changed during measured PCM admission")
        originals["audio"] = {"path": str(audio_path), "sha256": audio_sha, "bytes": len(audio_body)}
        bodies = {}
    else:
        if audio_path is not None or audio_sha is not None:
            raise ValueError("Schema2 uses only its three committed narration_segments; omit legacy audio arguments")
        audio_body, audio, segment_originals, bodies = _segments(spec, spec_path.parent, cancelled, deadline)
        originals.update(segment_originals)
    report = source_gate(spec, audio)
    return spec, source, audio_body, audio, report, originals, bodies
