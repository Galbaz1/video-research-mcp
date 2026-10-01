"""Fixed stdio, immutable replay and failure controls without provider or foreign execution."""

import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import threading
import time

import pytest

from video_research_mcp import audio_dsp, audio_dsp_stdio, config
from video_research_mcp.audio_dsp_backend import mono_file, parameters, profile
from video_research_mcp.audio_dsp_jobs import finish, prepare, retained
from video_research_mcp.audio_dsp_visuals import export_native_views
from video_research_mcp.image_manifest import canonical
from video_research_mcp.job_store import JobStore
from video_research_mcp.media_process import run_media_process
from video_research_mcp.models.audio_dsp import AudioDspRequest

DIGEST = "a" * 64


def request(**values):
    return AudioDspRequest(file_path="/owned/tone.wav", expected_source_sha256=DIGEST, **values)


@pytest.mark.parametrize(
    "values",
    [
        {"operation": "compare"},
        {"reference": {"file_path": "/a", "expected_source_sha256": DIGEST}},
        {"end_seconds": 31},
        {
            "operation": "compare",
            "end_seconds": 20,
            "reference": {"file_path": "/a", "expected_source_sha256": DIGEST, "end_seconds": 20},
        },
        {"native_return_format": "full"},
        {"max_events": 0},
    ],
)
def test_request_fails_before_file_or_process_work(values):
    with pytest.raises(ValueError):
        request(**values)


def test_optional_profile_missing_or_link_is_never_guessed(tmp_path, monkeypatch):
    for key in ("AUDIO_DSP_JUZZY_PATH", "AUDIO_DSP_JUZZY_SHA256"):
        monkeypatch.delenv(key, raising=False)
    assert profile("analyze") is None
    with pytest.raises(ImportError, match="AUDIO_DSP_JUZZY"):
        profile("full_analysis")
    path = tmp_path / "link"
    path.symlink_to(sys.executable)
    monkeypatch.setenv("AUDIO_DSP_JUZZY_PATH", str(path))
    monkeypatch.setenv("AUDIO_DSP_JUZZY_SHA256", DIGEST)
    with pytest.raises(ValueError, match="symlink"):
        profile("full_analysis")


def test_native_modes_use_owned_paths_fixed_limits_and_real_format_enum():
    windows = [{"path": "/own/selected.wav"}, {"path": "/own/reference.wav"}]
    assert parameters(request(operation="spectral_features"), windows)[1] == {
        "path": windows[0]["path"],
        "resolution": "low",
        "n_fft": 2048,
        "hop_length": 512,
    }
    value = request(operation="ferrous_analyze", native_return_format="visual_only")
    name, arguments = parameters(value, windows)
    assert name == "analyze_audio" and arguments["return_format"] == "visual_only"
    assert arguments["include_visuals"] and arguments["max_data_points"] == 128
    assert "cursor" not in arguments and "output_dir" not in arguments


def test_mono_derivation_retains_pcm_identity_and_explicit_conversion(tmp_path):
    import struct
    import threading
    import wave

    pcm = struct.pack("<hhhh", 1000, -1000, 2000, 0)
    selection = {
        "channels": 2,
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "source_reference": "urn:owned",
    }
    result = mono_file(pcm, selection, tmp_path, threading.Event(), time.monotonic() + 5)
    assert result["method"] == "channel_mean_round_to_even_signed16" and result["channels"] == 1
    assert result["input_pcm_sha256"] == selection["pcm_sha256"]
    with wave.open(result["path"], "rb") as reader:
        assert reader.getnchannels() == 1 and reader.readframes(2) == struct.pack("<hh", 0, 1000)


def fake_driver(tmp_path, backend, mode):
    directory = tmp_path / (backend + "-" + mode)
    directory.mkdir()
    executable = directory / "server"
    script = f"""#!{sys.executable}
import sys,json,os,time
from pathlib import Path
mode={mode!r}; backend={backend!r}; tools={sorted(audio_dsp_stdio.TOOLS[backend])!r}
Path("pid").write_text(str(os.getpid()))
if mode=="block":
 time.sleep(60)
for line in sys.stdin:
 r=json.loads(line)
 if "id" not in r: continue
 if mode=="oversize": print("x"*(1024*1024+1),flush=True);continue
 if mode=="client_request": print(json.dumps({{"jsonrpc":"2.0","id":71,"method":"sampling/createMessage"}}),flush=True);continue
 if r["method"]=="initialize": value={{"protocolVersion":"2025-06-18","capabilities":{{}},"serverInfo":{{"name":"fixture","version":"1"}}}}
 elif r["method"]=="tools/list": value={{"tools":[{{"name":n,"inputSchema":{{"type":"object"}}}} for n in tools+([tools[0]] if mode=="duplicate" else [])]}}
 else:
  if r["params"]["name"]=="get_job_status": text=json.dumps({{"status":{{"id":"native-1","status":"complete"}}}})
  elif backend=="ferrous": text=json.dumps({{"status":"success","job_id":"native-1","summary":{{"fingerprint":"heuristic"}}}})
  else: text="Error: fixture decode" if mode=="text_error" else "Native heuristic fixture, no factual acceptance"
  value={{"content":[{{"type":"text","text":text}}]}}
 print(json.dumps({{"jsonrpc":"2.0","id":r["id"],"result":value}}),flush=True)
"""
    executable.write_text(script)
    executable.chmod(0o500)
    payload = {
        "backend": backend,
        "tool": "audio_info" if backend == "juzzy" else "analyze_audio",
        "arguments": {"path": "/owned.wav"},
        "executable": str(executable),
        "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
    }
    path = directory / "request.json"
    path.write_bytes(canonical(payload))
    return directory, [sys.executable, "-I", str(Path(audio_dsp_stdio.__file__)), str(path)]


@pytest.mark.parametrize("backend", ["juzzy", "ferrous"])
async def test_actual_bounded_stdio_discovers_all_tools_and_joins_native_job(tmp_path, backend):
    directory, command = fake_driver(tmp_path, backend, "success")
    stdout, _ = await run_media_process(command, 5)
    receipt = json.loads(stdout)
    body = Path(receipt["path"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == receipt["sha256"] and len(body) == receipt["bytes"]
    result = json.loads(body)
    assert receipt["process_joined"] and not (directory / "server").exists()
    assert len(result["discovery"]["tools"]) == len(audio_dsp_stdio.TOOLS[backend])
    assert result["native_job_observation_is_result_attestation"] is False
    assert len(result["trace"]) == (4 if backend == "ferrous" else 3)
    with pytest.raises(ProcessLookupError):
        os.kill(receipt["pid"], 0)


@pytest.mark.parametrize("mode", ["oversize", "client_request", "duplicate", "text_error"])
async def test_invalid_native_protocol_never_promotes_response(tmp_path, mode):
    directory, command = fake_driver(tmp_path, "juzzy", mode)
    with pytest.raises(RuntimeError):
        await run_media_process(command, 5)
    assert not (directory / "native-response.json").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int((directory / "pid").read_text()), 0)


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_and_repeated_cancellation_join_native_process(tmp_path, cancel):
    directory, command = fake_driver(tmp_path, "juzzy", "block")
    task = asyncio.create_task(run_media_process(command, 2 if not cancel else 10))
    for _ in range(200):
        if (directory / "pid").exists():
            break
        if task.done():
            await task
        await asyncio.sleep(0.01)
    assert (directory / "pid").exists()
    if cancel:
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    with pytest.raises(ProcessLookupError):
        os.kill(int((directory / "pid").read_text()), 0)
    assert not (directory / "native-response.json").exists()


def test_job_replay_binds_exact_artifact_and_never_claims_attempt_again(tmp_path, monkeypatch):
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))
    value = request(job_id="fixed-job")
    binding = {"source": DIGEST, "runtime": "fixed"}
    state = {}
    store, job, owner = prepare(value, binding, 10, state, threading.Event(), time.monotonic() + 10)
    artifact = tmp_path / "result.json"
    artifact.write_bytes(b'{"complete":true}')
    result = finish(
        state,
        {"status": "complete"},
        "completed",
        [{"path": str(artifact), "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest()}],
        threading.Event(),
        time.monotonic() + 10,
    )
    assert result["job_receipt"]["attestation"]["verified"]
    _, replay, owner = prepare(value, binding, 10, {}, threading.Event(), time.monotonic() + 10)
    assert owner == "" and replay["attempts"] == 1
    assert retained(replay)["metadata"] == {"status": "complete"}
    artifact.write_bytes(b'{"complete":false}')
    with pytest.raises(ValueError, match="readback"):
        retained(store.get(job["job_id"]))
    with pytest.raises(ValueError, match="immutable"):
        prepare(value, {"source": "b" * 64}, 10, {}, threading.Event(), time.monotonic() + 10)


async def test_changed_source_fails_before_job_creation_or_native_process(tmp_path, monkeypatch):
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setattr(
        config, "_config", config.ServerConfig(gemini_api_key="fixture", cache_dir=str(tmp_path))
    )
    path = tmp_path / "source.wav"
    path.write_bytes(b"current-source")
    result = await audio_dsp.execute(
        AudioDspRequest(file_path=str(path), expected_source_sha256=DIGEST)
    )
    assert "differs" in result["error"] and not Path(os.environ["VRM_JOB_DB"]).exists()


def test_interrupted_attempt_remains_unknown_without_resubmission(tmp_path, monkeypatch):
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))
    value = request(job_id="interrupted")
    _, job, owner = prepare(value, {}, 10, {}, threading.Event(), time.monotonic() + 10)
    assert owner
    _, replay, owner = prepare(value, {}, 10, {}, threading.Event(), time.monotonic() + 10)
    assert owner == "" and replay["attempts"] == 1
    assert retained(replay)["metadata"]["status"] == "unknown"
    assert JobStore().get(job["job_id"])["result"] is None


@pytest.mark.parametrize("mutate", [False, True])
async def test_controller_keeps_original_live_through_publication_and_replay(
    tmp_path, monkeypatch, mutate
):
    """A source change during analysis clears staging and checkpoints a terminal failure."""
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setattr(
        config, "_config", config.ServerConfig(gemini_api_key="fixture", cache_dir=str(tmp_path))
    )
    path = tmp_path / "source.wav"
    path.write_bytes(b"fixed original")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    count = []

    async def runtime(*args):
        return {"version": "fixture"}

    async def source(owned):
        return {"sha256": owned.sha256, "audio_end_seconds": 1, "first_audio_seconds": 0}

    async def analyze(owned, *args):
        count.append(1)
        artifact = owned.directory / "selected.wav"
        artifact.write_bytes(b"fixed selected artifact")
        record = {
            "path": str(artifact),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "bytes": artifact.stat().st_size,
            "mime": "audio/wav",
        }
        if mutate:
            path.write_bytes(b"source mutated during analysis")
        return {"selection": record, "measurements": {}}, b"", [record]

    monkeypatch.setattr(audio_dsp, "runtime_binding", runtime)
    monkeypatch.setattr(audio_dsp, "audio_source", source)
    monkeypatch.setattr(audio_dsp, "analyze_one", analyze)
    value = AudioDspRequest(
        file_path=str(path), expected_source_sha256=digest, end_seconds=1, job_id="source-control"
    )
    result = await audio_dsp.execute(value)
    metadata = result["metadata"]
    if mutate:
        assert metadata["status"] == "failed" and "changed" in metadata["error"]
        assert list((tmp_path / "media/views").iterdir()) == []
        assert JobStore().get("source-control")["status"] == "failed"
    else:
        assert metadata["status"] == "complete" and result["job_receipt"]["attestation"]["verified"]
        assert (
            json.loads(Path(metadata["result_artifact"]["path"]).read_bytes())["status"]
            == "complete"
        )
        replay = await audio_dsp.execute(value)
        assert replay["metadata"] == metadata and len(count) == 1
        Path(metadata["result_artifact"]["path"]).unlink()
        missing = await audio_dsp.execute(value)
        assert "readback" in missing["error"] and len(count) == 1


@pytest.mark.parametrize("bad", [None, "missing", "geometry"])
def test_ferrous_visual_export_verifies_pixels_geometry_and_source(tmp_path, bad):
    """Embedded native visuals become file artifacts only after full bounded PNG admission."""
    import base64
    import io
    import threading
    from PIL import Image

    stream = io.BytesIO()
    with Image.new("RGB", (32, 32) if bad == "geometry" else (1920, 600), "navy") as image:
        image.save(stream, format="PNG")
    encoded = base64.b64encode(stream.getvalue()).decode()
    visuals = {key: encoded for key in ("waveform", "spectrogram", "power_curve")}
    if bad == "missing":
        visuals["waveform"] = None
    body = canonical(
        {"result": {"content": [{"type": "text", "text": json.dumps({"visuals": visuals})}]}}
    )
    path = tmp_path / "response.json"
    path.write_bytes(body)
    record = {
        "path": str(path),
        "sha256": hashlib.sha256(body).hexdigest(),
        "source": {"revision": "fixed"},
    }
    selection = {
        "source_reference": "urn:sha256:" + DIGEST + "#t=7,9",
        "pcm_sha256": DIGEST,
        "source_clock": {"first_seconds": 7},
    }
    args = record, selection, tmp_path, threading.Event(), time.monotonic() + 5
    if bad:
        with pytest.raises(ValueError):
            export_native_views(*args)
    else:
        result = export_native_views(*args)
        assert len(result) == 3 and all((r["width"], r["height"]) == (1920, 600) for r in result)
        for row in result:
            assert (
                row["source_reference"] == selection["source_reference"] and row["pixels_verified"]
            )
            assert row["native_axis_numerical_correctness_verified"] is False
            assert hashlib.sha256(Path(row["path"]).read_bytes()).hexdigest() == row["sha256"]
