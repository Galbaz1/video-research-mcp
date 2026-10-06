"""Local speaker workflows: exact-source WAV, one optional subprocess worker, immutable records.

Diarize, relabel and samples write only a new output directory, promoted by
rename after every artifact and its receipt exist. Only ``enroll`` writes a
voiceprint. Native work happens in ``speaker_worker.py`` under the separately
installed runtime named by a SHA-bound speaker-runtime/v1 descriptor.
"""

import asyncio
import hashlib
import logging
import os
import shutil
import tempfile
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from . import speaker_registry as registry_store
from .audio_assets import export_audio
from .config import get_config
from .media_local_io import _open_regular
from .media_process import run_media_process
from .media_snapshot import checked_path, copy_hash
from .models.scene_assets import AudioExportRequest
from .models.speakers import SpeakerRuntime, SpeakersResult
from .native_media_results import _discard_views
from .speaker_records import (
    CONFIDENCE_KIND, CONFIDENCE_MEANING, RATE, admit_centroids, admit_record, admit_turns, anonymous_turns, cards,
    cluster_intervals, diarize_config, relabel_record, rttm, select_samples, wav_bytes, wav_pcm, worker_payload,
)
from .transcript_captions import strict_json
from .transcript_formats import encoded, write_artifact

WORKER = Path(__file__).with_name("speaker_worker.py")
WORKER_TIMEOUT_SECONDS = 600
MAX_RECORD_BYTES = 4 * 1024 * 1024
MAX_DESCRIPTOR_BYTES = 64 * 1024
MAX_WAV_BYTES = 8 * 1024 * 1024
_WORKER_SLOT = asyncio.Lock()


def _result(action: str, status: str, record: dict, directory: Path | None = None,
            artifacts: list | None = None, persisted: int = 0) -> dict:
    return SpeakersResult(action=action, status=status, output_directory=str(directory) if directory else None,
                          artifacts=artifacts or [], record=record,
                          voiceprints_persisted=persisted).model_dump(mode="json")


def _absent(value: str) -> Path:
    """Output directories are created once; existing paths are never overwritten."""
    path = checked_path(value)
    if path.exists() or path.is_symlink():
        raise FileExistsError("Speaker output directory must not exist; records are never overwritten")
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Speaker output parent directory does not exist: {path.parent}")
    return path


def _read_bound(path: Path, expected: str, limit: int, label: str) -> bytes:
    with _open_regular(path) as reader:
        data = reader.read(limit + 1)
    if len(data) > limit or hashlib.sha256(data).hexdigest() != expected:
        raise ValueError(f"{label} differs from its expected SHA-256 or exceeds its size bound")
    return data


async def _runtime(path: str, expected: str) -> tuple[dict, str]:
    """Rehash the descriptor and both models before every use; nothing is defaulted."""
    data = _read_bound(checked_path(path), expected, MAX_DESCRIPTOR_BYTES, "Speaker runtime descriptor")
    runtime = SpeakerRuntime.model_validate(strict_json(data)).model_dump()
    for model in (runtime["segmentation_model"], runtime["embedding_model"]):
        if await copy_hash(Path(model["path"])) != (model["sha256"], model["bytes"]):
            raise ValueError(f"Speaker model {Path(model['path']).name} differs from its descriptor pin")
    if not Path(runtime["python"]).is_file() or not Path(runtime["site_packages"]).is_dir():
        raise FileNotFoundError("Speaker runtime interpreter or site-packages directory is missing")
    return runtime, expected


def _model_key(runtime: dict) -> dict:
    model = runtime["embedding_model"]
    return {"basename": Path(model["path"]).name, "sha256": model["sha256"], "dimension": model["dimension"]}


def _runtime_record(runtime: dict, descriptor_sha256: str) -> dict:
    pins = {key: {"basename": Path(runtime[key]["path"]).name,
                  **{k: v for k, v in runtime[key].items() if k != "path"}}
            for key in ("segmentation_model", "embedding_model")}
    return {"route": "optional_subprocess_worker", "descriptor_sha256": descriptor_sha256,
            "sherpa_onnx_version": runtime["sherpa_onnx_version"], "provider": runtime["provider"],
            "num_threads": runtime["num_threads"], **pins}


async def _export_wav(file_path: str, sha256: str, start: float, end: float) -> tuple[bytes, dict]:
    """Native boundary: reuse exact-source 16 kHz mono export, refuse partial coverage, discard the view."""
    result = await export_audio(AudioExportRequest(
        file_path=file_path, expected_source_sha256=sha256, start_seconds=start, end_seconds=end))
    primary = None
    try:
        artifact, selected = result["artifact"], result["selected_window"]
        data = _read_bound(Path(artifact["path"]), artifact["sha256"], MAX_WAV_BYTES, "Exported speaker WAV")
        if abs(selected["start_seconds"] - start) > 1 / RATE or abs(selected["end_seconds"] - end) > 1 / RATE:
            raise ValueError("Source audio does not cover the complete requested speaker selection")
        keys = ("requested_window", "selected_window", "source_audio_clock", "clock_relationship")
        return data, {key: result[key] for key in keys}
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            _discard_views([result], Path(get_config().cache_dir).expanduser().resolve() / "media" / "views")
        except Exception as cleanup:
            if primary is None:
                raise
            primary.add_note(f"Speaker view cleanup failed: {cleanup!r}")
            logging.getLogger(__name__).error("Speaker view cleanup failed", exc_info=True)


async def _run_worker(runtime: dict, payload: dict) -> bytes:
    """Native boundary: one isolated worker process at a time, bounded time and output."""
    async with _WORKER_SLOT:
        with tempfile.TemporaryDirectory(prefix="vrm-speaker-") as scratch:
            request = Path(scratch) / "request.json"
            request.write_bytes(encoded(payload))
            command = [runtime["python"], "-I", str(WORKER), str(request)]
            stdout, _ = await run_media_process(command, WORKER_TIMEOUT_SECONDS, cwd=Path(scratch))
    return stdout


@contextmanager
def _staged(target: Path):
    """Write into a private sibling, then rename; failures leave no output directory."""
    staging = target.parent / f".{target.name}.{uuid.uuid4().hex}.pending"
    staging.mkdir(mode=0o700)
    primary = None
    try:
        yield staging
        if target.exists() or target.is_symlink():
            raise FileExistsError("Speaker output directory appeared during the run")
        os.rename(staging, target)
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            if staging.exists():
                shutil.rmtree(staging)
        except Exception as cleanup:
            if primary is None:
                raise
            primary.add_note(f"Speaker staging cleanup failed at {staging}: {cleanup!r}")
            logging.getLogger(__name__).error("Speaker staging cleanup failed at %s", staging, exc_info=True)


def _finish(staging: Path, action: str, artifacts: list, summary: dict) -> list:
    receipt = {"schema": "speaker-receipt/v1", "operation": action, "artifacts": list(artifacts), **summary}
    return [*artifacts, write_artifact(staging, "receipt.json", encoded(receipt), "receipt")]


def _parent(reference) -> tuple[Path, dict, dict]:
    """Read one SHA-bound diarization record; relabel records are never chained."""
    path = checked_path(reference.diarization_record_path)
    data = _read_bound(path, reference.expected_record_sha256, MAX_RECORD_BYTES, "Diarization record")
    record = strict_json(data)
    if not isinstance(record, dict) or record.get("schema") != "speaker-diarization/v1":
        raise ValueError("Expected a speaker-diarization/v1 record; relabel records are never chained")
    admit_record(record)
    _parent_wav(path, record)
    return path, record, {"path": str(path), "sha256": reference.expected_record_sha256, "schema": record["schema"]}


def _parent_wav(path: Path, record: dict) -> tuple[dict, bytes]:
    """Verify the retained input WAV against the record before any slice or embedding."""
    audio = record["audio"]
    if Path(audio["path"]).name != audio["path"]:
        raise ValueError("Diarization record audio path must be a bare retained filename")
    wav = checked_path(str(path.parent / audio["path"]))
    data = _read_bound(wav, audio["sha256"], MAX_WAV_BYTES, "Retained diarization WAV")
    pcm, count = wav_pcm(data)
    if count != audio["sample_count"] or len(data) != audio["bytes"]:
        raise ValueError("Retained diarization WAV byte/sample count differs from its record")
    return {"path": str(wav), "sha256": audio["sha256"], "sample_count": count}, pcm


async def _source_digest(value: str, expected: str) -> Path:
    path = checked_path(value)
    if (await copy_hash(path))[0] != expected:
        raise ValueError("Source differs from expected_source_sha256")
    return path


async def diarize(request) -> dict:
    """Anonymous timestamped turns with similarity scalars; never reads the registry or names anyone."""
    target = _absent(request.output_directory)
    runtime, descriptor = await _runtime(request.runtime_descriptor_path, request.expected_runtime_descriptor_sha256)
    source = await _source_digest(request.file_path, request.expected_source_sha256)
    config = diarize_config(request.num_speakers)
    outputs = ["diarization-input.wav", "diarization.json", *(["diarization.rttm"] * request.export_rttm), "receipt.json"]
    if request.dry_run:
        return _result("diarize", "planned", {"outputs": outputs, "config": config, "worker": "not started",
            "runtime": _runtime_record(runtime, descriptor),
            "selection": {"start_seconds": request.start_seconds, "end_seconds": request.end_seconds}}, target)
    data, clock = await _export_wav(request.file_path, request.expected_source_sha256,
                                    request.start_seconds, request.end_seconds)
    _, count = wav_pcm(data)
    with _staged(target) as staging:
        artifacts = [write_artifact(staging, "diarization-input.wav", data, "diarization_input_wav")]
        wav = {"path": str(staging / "diarization-input.wav"), "sha256": artifacts[0]["sha256"], "sample_count": count}
        payload = worker_payload("diarize", runtime, descriptor, wav, config)
        turns = anonymous_turns(admit_turns(await _run_worker(runtime, payload), payload),
                                clock["selected_window"]["start_seconds"])
        summary = cards(turns)
        record = {"schema": "speaker-diarization/v1",
                  "source": {"path": str(source), "sha256": request.expected_source_sha256},
                  "selection": {**clock["selected_window"], "requested": clock["requested_window"],
                                "source_audio_clock": clock["source_audio_clock"],
                                "clock_relationship": clock["clock_relationship"]},
                  "audio": {"path": "diarization-input.wav", "sha256": wav["sha256"], "bytes": len(data),
                            "sample_count": count, "sample_rate": RATE, "channels": 1},
                  "runtime": _runtime_record(runtime, descriptor), "config": config,
                  "num_speakers_hint": request.num_speakers, "turns": turns, "cards": summary,
                  "observed_cluster_count": len(summary), "confidence_kind": CONFIDENCE_KIND,
                  "confidence_interpretation": CONFIDENCE_MEANING, "names_assigned": False,
                  "registry_read": False, "embeddings_persisted": False, "speaker_identity_verified": False}
        admit_record(record)
        artifacts.append(write_artifact(staging, "diarization.json", encoded(record), "speaker_diarization_record"))
        if request.export_rttm:
            artifacts.append(write_artifact(staging, "diarization.rttm",
                                            rttm(turns, request.expected_source_sha256, "cluster"), "rttm"))
        artifacts = _finish(staging, "diarize", artifacts, {"source": record["source"], "voiceprints_persisted": 0})
    return _result("diarize", "complete", record, target, artifacts)


async def _match(request, path: Path, parent: dict) -> tuple[dict, dict]:
    """Explicitly requested, read-only ranking; centroids stay in memory and are never applied."""
    registry_path = checked_path(request.registry_path)
    registry, before = registry_store.read(registry_path)
    runtime, descriptor = await _runtime(request.runtime_descriptor_path, request.expected_runtime_descriptor_sha256)
    model = _model_key(runtime)
    _, ignored = registry_store.rank(registry, model, {}, request.expected_speakers)
    wav, _ = _parent_wav(path, parent)
    match = {"registry_path": str(registry_path), "registry_sha256": before, "model": model,
             "expected_speakers": list(request.expected_speakers), "ignored_other_model_entries": ignored,
             "suggestions_applied": False, "worker": "not started"}
    if request.dry_run:
        return {}, match
    payload = worker_payload("embed", runtime, descriptor, wav, {}, cluster_intervals(parent))
    centroids = admit_centroids(await _run_worker(runtime, payload), payload)
    suggestions, _ = registry_store.rank(registry, model, centroids, request.expected_speakers)
    if registry_store.read(registry_path)[1] != before:
        raise ValueError("Speaker registry changed during matching; suggestions discarded")
    return suggestions, {**match, "worker": "complete"}


async def relabel(request) -> dict:
    """Write a new relabel record; the parent, other recordings and the registry stay byte-identical."""
    target = _absent(request.output_directory)
    path, parent, reference = _parent(request)
    suggestions, match = await _match(request, path, parent) if request.match_registry else ({}, None)
    record = relabel_record(parent, reference, request, suggestions, match)
    if request.dry_run:
        outputs = ["relabel.json", *(["relabel.rttm"] * request.export_rttm), "receipt.json"]
        return _result("relabel", "planned", {"outputs": outputs, "labels": record["labels"],
                                              "registry_match": match}, target)
    with _staged(target) as staging:
        artifacts = [write_artifact(staging, "relabel.json", encoded(record), "speaker_relabel_record")]
        if request.export_rttm:
            artifacts.append(write_artifact(staging, "relabel.rttm",
                                            rttm(record["turns"], parent["source"]["sha256"], "label"), "rttm"))
        artifacts = _finish(staging, "relabel", artifacts, {"parent": reference, "registry_written": False})
    return _result("relabel", "complete", record, target, artifacts)


async def samples(request) -> dict:
    """Export bounded clips whose PCM equals the retained input at exact sample offsets."""
    target = _absent(request.output_directory)
    path, parent, reference = _parent(request)
    clips = select_samples(parent, request.clusters, request.per_cluster, request.max_seconds)
    if request.dry_run:
        return _result("samples", "planned", {"clips": clips, "outputs": [c["path"] for c in clips]}, target)
    _, pcm = _parent_wav(path, parent)
    with _staged(target) as staging:
        artifacts = []
        for clip in clips:
            data = wav_bytes(pcm[2 * clip["start_sample"]:2 * clip["end_sample"]])
            artifacts.append(write_artifact(staging, clip["path"], data, "speaker_sample_wav"))
            clip.update(sha256=artifacts[-1]["sha256"], bytes=artifacts[-1]["bytes"])
        record = {"schema": "speaker-samples/v1", "parent": reference, "source": parent["source"],
                  "sample_rate": RATE, "clips": clips, "speaker_identity_verified": False,
                  "total_seconds": sum(c["end_sample"] - c["start_sample"] for c in clips) / RATE}
        artifacts.append(write_artifact(staging, "samples.json", encoded(record), "speaker_samples_record"))
        artifacts = _finish(staging, "samples", artifacts, {"parent": reference})
    return _result("samples", "complete", record, target, artifacts)


async def registry_listing(request) -> dict:
    """List registry entries grouped by embedding model, without voiceprints."""
    registry, digest = registry_store.read(checked_path(request.registry_path))
    return _result("registry", "complete", {**registry_store.listing(registry), "registry_sha256": digest})


async def _enrollment_centroid(runtime: dict, descriptor: str, request, parent: tuple | None) -> list:
    """Embed the explicit source in the worker; a temporary file-window WAV is deleted afterwards."""
    with tempfile.TemporaryDirectory(prefix="vrm-enroll-") as scratch:
        source = request.source
        if parent is None:
            data, _ = await _export_wav(source.file_path, source.expected_source_sha256,
                                        source.start_seconds, source.end_seconds)
            _, count = wav_pcm(data)
            (Path(scratch) / "enroll.wav").write_bytes(data)
            wav = {"path": str(Path(scratch) / "enroll.wav"), "sha256": hashlib.sha256(data).hexdigest(),
                   "sample_count": count}
            groups = {"enrollment": [[0, count]]}
        else:
            wav, _ = _parent_wav(parent[0], parent[1])
            groups = {"enrollment": cluster_intervals(parent[1], [source.cluster])[source.cluster]}
        payload = worker_payload("embed", runtime, descriptor, wav, {}, groups)
        return admit_centroids(await _run_worker(runtime, payload), payload)["enrollment"]


async def enroll(request) -> dict:
    """Persist exactly one voiceprint for an explicit name, keyed by the embedding model."""
    registry_path = checked_path(request.registry_path)
    if not registry_path.parent.is_dir():
        raise FileNotFoundError(f"Speaker registry directory does not exist: {registry_path.parent}")
    registry, before = registry_store.read(registry_path)
    runtime, descriptor = await _runtime(request.runtime_descriptor_path, request.expected_runtime_descriptor_sha256)
    model, source, parent = _model_key(runtime), request.source, None
    exists = any((e["name"], e["model"]["sha256"]) == (request.speaker_name, model["sha256"])
                 for e in registry["speakers"])
    if exists and not request.replace_existing:
        raise FileExistsError(f"Speaker '{request.speaker_name}' already has a voiceprint for this model; "
                              "set replace_existing")
    if source.kind == "diarized_cluster":
        path, record, reference = _parent(source)
        parent = (path, record)
        provenance = {"kind": source.kind, "record": reference, "cluster": source.cluster, "source": record["source"],
                      "intervals": cluster_intervals(record, [source.cluster])[source.cluster]}
    else:
        file = await _source_digest(source.file_path, source.expected_source_sha256)
        provenance = {"kind": source.kind, "file_path": str(file), "source_sha256": source.expected_source_sha256,
                      "start_seconds": source.start_seconds, "end_seconds": source.end_seconds}
    plan = {"name": request.speaker_name, "model": model, "role": request.role, "provenance": provenance,
            "registry_path": str(registry_path), "registry_sha256_before": before, "would_replace": exists}
    if request.dry_run:
        return _result("enroll", "planned", plan)
    centroid = await _enrollment_centroid(runtime, descriptor, request, parent)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    entry = {"name": request.speaker_name, "model": model, "embedding": registry_store.unit(centroid),
             "added": now, "provenance": provenance, "consent": {"asserted_by_caller": True, "recorded_at": now}}
    if request.role:
        entry["role"] = request.role
    outcome = registry_store.enroll(registry_path, entry, request.replace_existing)
    return _result("enroll", "complete", {**plan, "entry": registry_store.public_entry(entry), **outcome}, persisted=1)


async def run_action(request) -> dict:
    """Dispatch one validated audio_speakers action."""
    handlers = {"diarize": diarize, "relabel": relabel, "samples": samples, "registry": registry_listing}
    return await handlers[request.action](request)
