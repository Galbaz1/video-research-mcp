"""Operator-pinned optional Rust DSP calls with owned PCM, binary and stdio lifetimes."""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import wave

from .audio_fingerprints import numpy_runtime
from .image_manifest import canonical
from .image_preprocessing import check_worker, image_worker
from .media_local_io import _copy_hash, _open_regular
from .media_process import run_media_process
from .audio_dsp_pcm import RATE
from .audio_dsp_diagnostics import read_diagnostic, request_binding

SOURCES = {
    "juzzy": {
        "repository": "JuzzyDee/audio-analyzer-rs",
        "revision": "0387fe1630ff0fc7f71bf656be81f3b1f400dda8",
    },
    "ferrous": {
        "repository": "willibrandon/ferrous-waves",
        "revision": "d28ec11361123eb3778454deddf164f1fb6d25e4",
    },
}


def profile(operation):
    """Read only the requested operator profile; missing optional binaries launch nothing."""
    if operation in {"analyze", "compare"}:
        return None
    backend = "ferrous" if operation.startswith("ferrous_") else "juzzy"
    key = "AUDIO_DSP_" + backend.upper()
    path, digest = os.getenv(key + "_PATH", ""), os.getenv(key + "_SHA256", "")
    if not path or not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ImportError(
            f"Configure {key}_PATH and {key}_SHA256 for the separately built optional DSP server"
        )
    executable = Path(path)
    if not executable.is_absolute() or any(
        item.is_symlink() for item in (executable, *executable.parents)
    ):
        raise ValueError(
            "Optional DSP executable must be an absolute regular path without symlinks"
        )
    return {"backend": backend, "executable": path, "sha256": digest, "source": SOURCES[backend]}


def binary_identity(path, target, expected, cancelled, deadline):
    """Hash/copy one bounded regular executable and join admission before dispatch."""
    check_worker(cancelled, deadline)
    digest, size = _copy_hash(Path(path), target, cancelled=cancelled, max_bytes=256 * 1024 * 1024)
    if expected and digest != expected:
        raise ValueError("Optional DSP executable differs from the operator-pinned SHA256")
    if target:
        target.chmod(0o500)
    check_worker(cancelled, deadline)
    return {"path": path, "sha256": digest, "bytes": size}


def mono_file(pcm, selection, directory, cancelled, deadline):
    """Derive explicit mono for the pinned Ferrous planar/interleaved decoder mismatch."""
    check_worker(cancelled, deadline)
    np = numpy_runtime()
    values = np.frombuffer(pcm, dtype="<i2").reshape(-1, selection["channels"])
    samples = np.rint(np.mean(values.astype(np.float64), axis=1)).astype("<i2").tobytes()
    stream = io.BytesIO()
    with wave.open(stream, "wb") as writer:
        writer.setparams((1, 2, RATE, len(samples) // 2, "NONE", "not compressed"))
        writer.writeframes(samples)
    body = stream.getvalue()
    path = directory / "ferrous-mono.wav"
    with path.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        writer.write(body)
    check_worker(cancelled, deadline)
    return {
        "path": str(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body),
        "mime": "audio/wav",
        "role": "ferrous_derived_mono",
        "pcm_sha256": hashlib.sha256(samples).hexdigest(),
        "method": "channel_mean_round_to_even_signed16",
        "input_pcm_sha256": selection["pcm_sha256"],
        "channels": 1,
        "frames": len(samples) // 2,
        "sample_rate": RATE,
        "source_reference": selection["source_reference"],
    }


def parameters(request, selections):
    """Select concrete pinned tool arguments; no native path, cursor or arbitrary command input."""
    paths = [row["path"] for row in selections]
    if request.operation == "ferrous_compare":
        return "compare_audio", {"file_a": paths[0], "file_b": paths[1]}
    if request.operation == "ferrous_analyze":
        full = request.native_return_format == "full"
        return "analyze_audio", {
            "file_path": paths[0],
            "return_format": request.native_return_format,
            "analysis_profile": "standard",
            "max_data_points": 128,
            "include_visuals": request.native_return_format == "visual_only",
            "include_spectral": full,
            "include_temporal": full,
        }
    if request.operation == "juzzy_compare":
        return "compare", {"path_a": paths[0], "path_b": paths[1]}
    arguments = {"path": paths[0]}
    if request.operation != "audio_info":
        arguments["resolution"] = "low"
    if request.operation == "spectral_features":
        arguments.update(n_fft=2048, hop_length=512)
    if request.operation == "rhythm_analysis":
        arguments.update(min_bpm=60, max_bpm=180)
    return request.operation, arguments


def response_record(body, directory, cancelled, deadline):
    """Bind the small driver receipt to the full bounded native response bytes."""
    check_worker(cancelled, deadline)
    record = json.loads(body)
    path = directory / "native-response.json"
    if record["path"] != str(path) or not record.get("process_joined"):
        raise ValueError("Native DSP collector did not join or returned an unrelated artifact")
    with _open_regular(path) as reader:
        response = reader.read(4 * 1024 * 1024 + 1)
    if len(response) > 4 * 1024 * 1024 or (hashlib.sha256(response).hexdigest(), len(response)) != (
        record["sha256"],
        record["bytes"],
    ):
        raise ValueError("Native DSP response artifact failed exact bounded readback")
    check_worker(cancelled, deadline)
    return record


def attributed_record(record, configured, selections):
    """Keep native source, heuristic limits and clip-zero clock mappings beside exact bytes."""
    return {
        **record,
        "source": configured["source"],
        "executable_sha256": configured["sha256"],
        "declared_source_build_provenance_verified": False,
        "results_are_untrusted_native_observations": True,
        "quality_music_content_fingerprint_labels_are_heuristic": True,
        "standards_conformance_verified": False,
        "clock_mapping": [
            {
                "native_zero_absolute_source_seconds": row["source_clock"]["first_seconds"],
                "source_reference": row["source_reference"],
            }
            for row in selections
        ],
        "ferrous_cache": "enabled_in_fresh_private_cwd_with_unique_owned_input_paths"
        if configured["backend"] == "ferrous"
        else None,
    }


def failure_diagnostic(directory, binding, configured, state):
    """Copy only admitted metadata into the concrete caller before it removes failed staging."""
    try:
        diagnostic = read_diagnostic(directory, binding)
        if diagnostic is None:
            return
        diagnostic.update(
            source=configured["source"],
            phase_binding=binding["phases"],
            job_request_sha256=state["job"]["request_sha256"],
            component_revision=state["job"]["source_revision"],
        )
        state["diagnostics"] = diagnostic
    except ValueError:
        state["diagnostic_rejected"] = True


async def native_call(owned, request, configured, selections, state):
    """Run the fixed collector inside the existing joined process group and private temp/cache cwd."""
    if any(row.get("frames", 8192) < 8192 for row in selections):
        raise ValueError(
            "Optional DSP requires at least8192 selected samples to avoid unqualified short-input calculations"
        )
    directory = owned.directory / "native"
    directory.mkdir(mode=0o700)
    executable = directory / "dsp-server"
    binary_path, digest = configured["executable"], configured["sha256"]
    await image_worker(binary_identity, binary_path, executable, digest, deadline=owned.deadline)
    tool, arguments = parameters(request, selections)
    payload = {
        "backend": configured["backend"],
        "tool": tool,
        "arguments": arguments,
        "executable": str(executable),
        "executable_sha256": digest,
    }
    path = directory / "request.json"
    with path.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        writer.write(canonical(payload))
    helper = Path(__file__).with_name("audio_dsp_stdio.py")
    helper_sha256 = state["job"]["request"]["diagnostic_contract"]["helper_sha256"]
    diagnostic_binding = request_binding(canonical(payload), helper_sha256)
    try:
        await image_worker(
            binary_identity, str(helper), None, helper_sha256, deadline=owned.deadline
        )
        try:
            stdout, _ = await run_media_process(
                [sys.executable, "-I", str(helper), str(path)], owned.remaining()
            )
        except BaseException as error:
            failure_diagnostic(directory, diagnostic_binding, configured, state)
            if not isinstance(error, Exception) or isinstance(error, TimeoutError):
                raise
            raise RuntimeError(
                "Native DSP collection failed; inspect safe job diagnostics"
            ) from None
        record = await image_worker(response_record, stdout, directory, deadline=owned.deadline)
        await image_worker(binary_identity, binary_path, None, digest, deadline=owned.deadline)
        await image_worker(
            binary_identity, str(helper), None, helper_sha256, deadline=owned.deadline
        )
        return attributed_record(record, configured, selections)
    finally:
        for item in directory.iterdir():
            if item.name != "native-response.json":
                shutil.rmtree(item) if item.is_dir() else item.unlink()
