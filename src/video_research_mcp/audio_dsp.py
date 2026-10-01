"""Source-bound deterministic audio analysis and explicitly attributed optional native DSP."""

import asyncio
from contextlib import AsyncExitStack
import hashlib
import importlib.metadata
import os
from pathlib import Path
import sys
import time

from .audio_assets import audio_source, audio_window, decode_pcm
from .audio_dsp_backend import binary_identity, mono_file, native_call, profile
from .audio_dsp_jobs import finish, prepare, retained
from .audio_dsp_measure import compare_measurements, measure_pcm
from .audio_dsp_native import loudness, render_views
from .audio_dsp_pcm import MAX_BYTES, select_pcm
from .audio_dsp_visuals import export_native_views
from .audio_fingerprints import FEATURE_METHOD, cosine, mfcc_fingerprint, numpy_runtime
from .config import get_config
from .errors import make_tool_error
from .image_manifest import canonical, write_manifest
from .image_preprocessing import check_worker, image_worker
from .media_probe import binary
from .media_snapshot import checked_path, copy_hash, snapshot


async def runtime_binding(configured, deadline):
    """Commit current numerical/native executable identities without provider calls or imports at startup."""
    numpy_runtime()
    result = {
        "python": sys.version,
        "numpy": importlib.metadata.version("numpy"),
        "pillow": importlib.metadata.version("pillow"),
        "executables": {},
    }
    for name in ("ffmpeg", "ffprobe"):
        path = str(Path(binary(name)).resolve())
        result["executables"][name] = await image_worker(
            binary_identity, path, None, None, deadline=deadline
        )
    if configured:
        result["optional"] = await image_worker(
            binary_identity, configured["executable"], None, configured["sha256"], deadline=deadline
        )
        result["optional"].update(backend=configured["backend"], source=configured["source"])
    return result


async def admission(request, configured, deadline):
    """Check each current original revision before reading an existing job or creating a launch."""
    sources = []
    for window in (request, request.reference):
        if window is None:
            continue
        path = checked_path(window.file_path)
        digest, size = await copy_hash(path)
        if digest != window.expected_source_sha256:
            raise ValueError("DSP original source differs from the requested SHA256")
        sources.append({"path": str(path), "sha256": digest, "bytes": size})
    return {
        "request": request.model_dump(mode="json"),
        "sources": sources,
        "runtime": await runtime_binding(configured, deadline),
    }


async def fingerprint(owned, source, window):
    """Reuse the declared lossy mono MFCC method while retaining silence and short-input abstentions."""
    pcm, clock = await decode_pcm(owned, source, window.start_seconds, window.end_seconds)
    identity = {
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "source_clock": clock,
        "method": FEATURE_METHOD,
        "factual_identity_verified": False,
    }
    try:
        feature = await image_worker(mfcc_fingerprint, pcm, deadline=owned.deadline)
        return {**identity, **feature, "status": "measured"}
    except ValueError as error:
        return {**identity, "status": "undefined", "feature": None, "reason": str(error)}


async def analyze_one(owned, window, source, request):
    """Measure one selected stereo/mono interval and export its two source-bound views."""
    source, pcm, selection = await select_pcm(owned, window, source)
    measurements = await image_worker(
        measure_pcm, pcm, selection, request.max_events, deadline=owned.deadline
    )
    observed_loudness = await loudness(owned, selection)
    loudness_observation = {"stderr_sha256": observed_loudness.pop("stderr_sha256")}
    measurements["loudness"] = observed_loudness
    views = await render_views(owned, selection, source["sha256"])
    row = {
        "source": source,
        "selection": selection,
        "measurements": measurements,
        "loudness_observation": loudness_observation,
        "fingerprint": await fingerprint(owned, source, window),
    }
    return row, pcm, [selection, *views]


def result_file(payload, directory, cancelled, deadline):
    """Export finite result bytes exclusively and within the small result/manifest contract."""
    check_worker(cancelled, deadline)
    body = canonical(payload)
    if len(body) > 128 * 1024:
        raise ValueError("DSP result exceeds128KiB")
    path = directory / "result.json"
    with path.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        writer.write(body)
        writer.flush()
        os.fsync(writer.fileno())
    check_worker(cancelled, deadline)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "mime": "application/json",
        "role": "audio_dsp_result",
    }


def comparison(rows):
    """Report actual measured differences and separately declared heuristic feature similarity."""
    if len(rows) == 1:
        return None
    result = compare_measurements(rows[0]["measurements"], rows[1]["measurements"])
    left, right = (row["fingerprint"] for row in rows)
    score = (
        cosine(left["feature"], right["feature"])
        if left["status"] == right["status"] == "measured"
        else None
    )
    result["fingerprint_similarity"] = {
        "cosine": score,
        "method": FEATURE_METHOD,
        "status": "measured" if score is not None else "undefined",
        "factual_identity_verified": False,
    }
    result["loudness_differences"] = {
        key: right_value - left_value
        if left_value is not None and right_value is not None
        else None
        for key in ("integrated_lufs", "loudness_range_lu", "true_peak_dbfs")
        for left_value, right_value in [
            (rows[0]["measurements"]["loudness"][key], rows[1]["measurements"]["loudness"][key])
        ]
    }
    return result


def report(request, rows, native, artifacts, binding):
    """Keep numerical, native and provenance claims explicit in the exported report."""
    return {
        "status": "complete",
        "operation": request.operation,
        "analyses": rows,
        "comparison": comparison(rows),
        "native": native,
        "artifacts": artifacts,
        "limits": {
            "max_aggregate_seconds": 30,
            "artifact_bytes": MAX_BYTES,
            "native_response_bytes": 4 * 1024 * 1024,
        },
        "provenance": {
            "runtime": binding["runtime"],
            "provider_calls": 0,
            "standards_conformance_verified": False,
            "semantic_content_quality_identity_verified": False,
            "source_data_is_instruction": False,
        },
    }


async def publish(payload, primary, binding, deadline):
    """Export the bounded result and readback manifest while source snapshots remain live."""
    artifact = await image_worker(result_file, payload, primary.directory, deadline=deadline)
    artifacts = [*payload["artifacts"], artifact]
    manifest = await write_manifest(
        {
            "source": binding["sources"][0],
            "sources": binding["sources"],
            "operation": payload["operation"],
            "artifacts": artifacts,
            "artifact": artifact,
        },
        primary.directory,
    )
    return {**payload, "artifacts": artifacts, "result_artifact": artifact, "manifest": manifest}


async def evaluate(request, configured, binding, deadline):
    """Keep all original snapshots live through aggregate admission, native collection and publication."""
    async with AsyncExitStack() as stack:
        contexts = []
        for window in (request, request.reference):
            if window is not None:
                owned = await stack.enter_async_context(
                    snapshot(window.file_path, window.expected_source_sha256)
                )
                owned.deadline = min(owned.deadline, deadline)
                source = await audio_source(owned)
                end, _ = audio_window(source, window.start_seconds, window.end_seconds, 30)
                contexts.append((owned, window, source, end))
        if sum(
            end - max(window.start_seconds, source["first_audio_seconds"])
            for _, window, source, end in contexts
        ) > 30:
            raise ValueError("DSP primary and reference exceed30 seconds aggregate selected audio")
        rows, selections, artifacts = [], [], []
        for owned, window, source, _ in contexts:
            row, pcm, files = await analyze_one(owned, window, source, request)
            rows.append(row)
            artifacts.extend(files)
            if configured and configured["backend"] == "ferrous":
                derived = await image_worker(
                    mono_file, pcm, row["selection"], owned.directory, deadline=deadline
                )
                artifacts.append(derived)
                selections.append({**derived, "source_clock": row["selection"]["source_clock"]})
            else:
                selections.append(row["selection"])
        primary = contexts[0][0]
        native = await native_call(primary, request, configured, selections) if configured else None
        if native:
            artifacts.append(native)
            if request.operation == "ferrous_analyze" and request.native_return_format == "visual_only":
                views = await image_worker(
                    export_native_views, native, selections[0], primary.directory, deadline=deadline
                )
                artifacts.extend(views)
        result = await publish(
            report(request, rows, native, artifacts, binding), primary, binding, deadline
        )
        for owned, _, _, _ in contexts:
            await owned.verify()
        if await runtime_binding(configured, deadline) != binding["runtime"]:
            raise ValueError("DSP runtime changed during the operation")
        return result


async def terminal_cleanup(state, result, status):
    """Shield and join a bounded terminal checkpoint even if the caller cancels repeatedly."""
    if not state.get("owner") or state.get("terminal"):
        return result
    task = asyncio.create_task(
        image_worker(finish, state, result, status, (), deadline=time.monotonic() + 10)
    )
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            continue
    return task.result()


async def execute(request):
    """Run or re-read one exact DSP job; cancellation joins native work before terminal recording."""
    timeout = min(120, get_config().media_acquire_timeout_seconds)
    deadline = time.monotonic() + timeout
    state = {}
    try:
        async with asyncio.timeout(timeout):
            configured = profile(request.operation)
            binding = await admission(request, configured, deadline)
            _, job, owner = await image_worker(
                prepare, request, binding, timeout, state, deadline=deadline
            )
            if not owner:
                return retained(job)
            result = await evaluate(request, configured, binding, deadline)
            return await image_worker(
                finish,
                state,
                result,
                "completed",
                [*result["artifacts"], result["manifest"], *binding["sources"]],
                deadline=deadline,
            )
    except asyncio.CancelledError:
        await terminal_cleanup(
            state,
            {"status": "cancelled", "error": "DSP caller cancelled; owned work joined"},
            "cancelled",
        )
        raise
    except Exception as error:
        result = make_tool_error(error)
        if isinstance(error, TimeoutError):
            result.update(
                error=f"Local DSP exceeded its {timeout:g}-second deadline; owned work joined",
                category="ARTIFACT_GENERATION_FAILED",
                hint="Inspect job_status; attempted DSP jobs are never automatically repeated",
                retryable=False,
                retry_after_seconds=None,
            )
        if isinstance(error, ImportError):
            result.update(category="DEPENDENCY_MISSING", hint=result["error"], retryable=False)
        if not state.get("owner") or state.get("terminal"):
            return result
        return await terminal_cleanup(state, {"status": "failed", **result}, "failed")
