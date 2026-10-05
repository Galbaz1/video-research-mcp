"""Standalone optional sherpa-onnx speaker worker; the core server never imports this file.

Run as ``<runtime python> -I speaker_worker.py <request.json>`` with a
speaker_worker_v1 request. The worker verifies the WAV and both model digests
before importing native code, contains no network code, writes nothing and
prints one JSON answer. ``diarize`` returns anonymous turns with a similarity
scalar only; ``embed`` returns unit centroids for explicit matching/enrollment.
"""

import hashlib
import io
import json
import math
import os
import stat
import sys
import wave
from pathlib import Path

PROTOCOL = "speaker_worker_v1"
RATE = 16000
MAX_WAV_BYTES = 8 * 1024 * 1024


def _sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        while chunk := stream.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _verified_pcm(request: dict) -> bytes:
    """Refuse substituted models or audio before any native import."""
    runtime, wav = request["runtime"], request["wav"]
    for model in (runtime["segmentation_model"], runtime["embedding_model"]):
        if _sha256(model["path"]) != model["sha256"]:
            raise SystemExit("speaker worker: model digest differs from the runtime descriptor")
    fd = os.open(wav["path"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise SystemExit("speaker worker: WAV must be a regular file")
        data = stream.read(MAX_WAV_BYTES + 1)
    if len(data) > MAX_WAV_BYTES or hashlib.sha256(data).hexdigest() != wav["sha256"]:
        raise SystemExit("speaker worker: WAV digest differs from the request or exceeds 8 MiB")
    if type(wav["sample_count"]) is not int or wav["sample_count"] <= 0:
        raise SystemExit("speaker worker: WAV sample count must be a positive integer")
    with wave.open(io.BytesIO(data), "rb") as audio:
        shape = (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype(), audio.getnframes())
        if shape != (1, 2, RATE, "NONE", wav["sample_count"]):
            raise SystemExit("speaker worker: WAV is not the submitted 16 kHz mono PCM16 population")
        pcm = audio.readframes(wav["sample_count"])
    if len(pcm) != 2 * wav["sample_count"]:
        raise SystemExit("speaker worker: WAV sample population is empty or incomplete")
    return pcm


def _modules(runtime: dict):
    sys.path.insert(0, runtime["site_packages"])
    import numpy
    import sherpa_onnx

    if sherpa_onnx.__version__ != runtime["sherpa_onnx_version"]:
        raise SystemExit("speaker worker: sherpa-onnx version differs from the runtime descriptor")
    return numpy, sherpa_onnx


def _embedding_config(sherpa, runtime: dict):
    return sherpa.SpeakerEmbeddingExtractorConfig(model=runtime["embedding_model"]["path"],
        num_threads=runtime["num_threads"], provider=runtime["provider"], debug=False)


def _extractor(sherpa, runtime: dict):
    config = _embedding_config(sherpa, runtime)
    if not config.validate():
        raise SystemExit("speaker worker: embedding config invalid")
    extractor = sherpa.SpeakerEmbeddingExtractor(config)
    if extractor.dim != runtime["embedding_model"]["dimension"]:
        raise SystemExit("speaker worker: embedding dimension differs from the runtime descriptor")
    return extractor


def _unit(vector: list) -> list | None:
    norm = math.sqrt(math.fsum(value * value for value in vector))
    return [value / norm for value in vector] if norm and math.isfinite(norm) else None


def _embed(extractor, samples) -> list | None:
    """Unit embedding of one sample span, or None when the extractor cannot use it."""
    if not len(samples):
        return None
    stream = extractor.create_stream()
    stream.accept_waveform(sample_rate=RATE, waveform=samples)
    stream.input_finished()
    if not extractor.is_ready(stream):
        return None
    return _unit([float(value) for value in extractor.compute(stream)])


def _mean(vectors: list) -> list | None:
    return _unit([math.fsum(column) / len(vectors) for column in zip(*vectors)]) if vectors else None


def _segments(sherpa, runtime: dict, config: dict, samples) -> list[tuple[int, float, float]]:
    segmentation = sherpa.OfflineSpeakerSegmentationModelConfig(
        pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(
            model=runtime["segmentation_model"]["path"], window_shift_ratio=config["window_shift_ratio"]),
        num_threads=runtime["num_threads"], provider=runtime["provider"], debug=False)
    clustering = sherpa.FastClusteringConfig(num_clusters=config["num_clusters"], threshold=config["threshold"])
    settings = sherpa.OfflineSpeakerDiarizationConfig(segmentation=segmentation,
        embedding=_embedding_config(sherpa, runtime), clustering=clustering,
        min_duration_on=config["min_duration_on"], min_duration_off=config["min_duration_off"])
    if not settings.validate():
        raise SystemExit("speaker worker: diarization config invalid")
    diarizer = sherpa.OfflineSpeakerDiarization(settings)
    if diarizer.sample_rate != RATE:
        raise SystemExit("speaker worker: diarizer sample rate is not 16 kHz")
    result = diarizer.process(samples).sort_by_start_time()
    return [(int(s.speaker), float(s.start), float(s.end)) for s in result]


def _turns(extractor, samples, segments: list) -> list[dict]:
    """Per-turn cosine to the turn's own cluster centroid; singletons and failures stay null."""
    vectors = [_embed(extractor, samples[round(start * RATE):round(end * RATE)]) for _, start, end in segments]
    members: dict[int, list] = {}
    for (speaker, _, _), vector in zip(segments, vectors):
        if vector is not None:
            members.setdefault(speaker, []).append(vector)
    centroids = {speaker: _mean(group) for speaker, group in members.items() if len(group) > 1}
    turns = []
    for (speaker, start, end), vector in zip(segments, vectors):
        similarity, reason = None, "embedding_failed" if vector is None else "singleton_cluster"
        if vector is not None and centroids.get(speaker) is not None:
            similarity = max(-1.0, min(1.0, math.fsum(a * b for a, b in zip(vector, centroids[speaker]))))
            reason = None
        turns.append({"native_cluster_id": speaker, "start_seconds": start, "end_seconds": end,
                      "similarity": similarity, "similarity_unavailable_reason": reason})
    return turns


def _centroids(extractor, samples, groups: dict) -> dict:
    result = {}
    for key, intervals in groups.items():
        vectors = [v for v in (_embed(extractor, samples[a:b]) for a, b in intervals) if v is not None]
        centroid = _mean(vectors)
        if centroid is None:
            raise SystemExit(f"speaker worker: no usable embedding for group {key}")
        result[key] = centroid
    return result


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: speaker_worker.py <request.json>")
    request = json.loads(Path(sys.argv[1]).read_bytes())
    if request.get("protocol") != PROTOCOL or request.get("operation") not in {"diarize", "embed"}:
        raise SystemExit("speaker worker: unsupported request")
    runtime, operation = request["runtime"], request["operation"]
    pcm = _verified_pcm(request)
    numpy, sherpa = _modules(runtime)
    samples = numpy.frombuffer(pcm, dtype="<i2").astype(numpy.float32) / numpy.float32(32768)
    extractor = _extractor(sherpa, runtime)
    if operation == "diarize":
        answer = {"turns": _turns(extractor, samples, _segments(sherpa, runtime, request["config"], samples))}
    else:
        answer = {"centroids": _centroids(extractor, samples, request["groups"])}
    receipt = {"descriptor_sha256": request["descriptor_sha256"], "wav_sha256": request["wav"]["sha256"],
               "sample_count": request["wav"]["sample_count"], "config": request["config"],
               "sherpa_onnx_version": sherpa.__version__, "embedding_dimension": int(extractor.dim),
               "speaker_identity_verified": False}
    sys.stdout.write(json.dumps({"protocol": PROTOCOL, "operation": operation, "receipt": receipt, **answer},
                                allow_nan=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
