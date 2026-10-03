"""First-party wire failures, private stderr and durable source-bound diagnostic readback."""

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import time

import pytest

from tests.test_audio_dsp_contract import fake_driver
from video_research_mcp import audio_dsp, audio_dsp_backend, audio_dsp_stdio, config
from video_research_mcp.audio_dsp_jobs import retained
from video_research_mcp.audio_dsp_diagnostics import read_diagnostic, request_binding
from video_research_mcp.image_manifest import canonical
from video_research_mcp.job_store import JobStore
from video_research_mcp.media_process import run_media_process
from video_research_mcp.models.audio_dsp import AudioDspRequest


@pytest.mark.parametrize(
    ("mode", "reason", "phase", "line_bytes", "notifications"),
    [
        ("empty", "empty_eof", 1, 0, 0),
        ("empty_call", "empty_eof", 3, 0, 0),
        ("partial", "unterminated_line", 1, 28, 0),
        ("oversize", "line_overflow", 1, 1024 * 1024 + 1, 0),
        ("aggregate", "aggregate_overflow", 1, 1024 * 1024, 4),
        ("notifications", "notification_exhaustion", 1, 128, 16),
        ("nonzero", "empty_eof", 1, 0, 0),
        ("invalid_json", "invalid_response", 1, 21, 0),
        ("noisy", "empty_eof", 1, 0, 0),
    ],
)
async def test_wire_failure_retains_exact_safe_observation(
    tmp_path, mode, reason, phase, line_bytes, notifications, record_property
):
    """GIVEN a bounded native fixture WHEN collection fails THEN retain its observed boundary."""
    directory, command = fake_driver(tmp_path, "juzzy", mode)
    started = time.monotonic()
    with pytest.raises(RuntimeError) as caught:
        await run_media_process(command, 5)
    assert time.monotonic() - started < 5
    assert "private-native-token" not in str(caught.value)
    value = json.loads((directory / "native-diagnostic.json").read_bytes())
    record_property("diagnostic", json.dumps(value, sort_keys=True))
    assert value["observation"] == reason and value["phase"]["id"] == phase
    assert value["response_bytes"] == line_bytes and value["notifications"] == notifications
    assert (
        value["request_sha256"]
        == hashlib.sha256((directory / "request.json").read_bytes()).hexdigest()
    )
    assert (
        value["helper_sha256"]
        == hashlib.sha256(Path(audio_dsp_stdio.__file__).read_bytes()).hexdigest()
    )
    assert value["terminal"] and value["native_process_joined"] and value["stderr_drain_joined"]
    assert (
        value["native_returncode"] == 17
        if mode == "nonzero"
        else isinstance(value["native_returncode"], int)
    )
    stderr = (directory / "native-stderr.bin").read_bytes()
    assert len(stderr) <= 65536 and value["stderr"]["retained_bytes"] == len(stderr)
    assert value["stderr"]["retained_sha256"] == hashlib.sha256(stderr).hexdigest()
    assert value["stderr"]["observed_bytes"] >= len(stderr) and value["stderr"]["eof"]
    if mode == "noisy":
        assert len(stderr) == 65536 and value["stderr"]["observed_bytes"] == 20 * 8000
        assert value["stderr"]["truncated"] is True
    if mode == "aggregate":
        assert value["total_response_bytes"] == 5 * 1024 * 1024
    assert (directory / "native-stderr.bin").stat().st_mode & 0o777 == 0o600
    assert (directory / "native-diagnostic.json").stat().st_mode & 0o777 == 0o600
    assert not (directory / "native-response.json").exists()
    with pytest.raises(ProcessLookupError):
        os.kill(int((directory / "pid").read_text()), 0)
    with pytest.raises(ProcessLookupError):
        os.kill(int((directory / "helper-pid").read_text()), 0)


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("mode", ["block", "block_tree"])
async def test_interrupted_helper_joins_native_and_stderr_drain(
    tmp_path, cancel, mode, record_property
):
    """GIVEN noisy blocked native work WHEN interrupted THEN preserve an honest joined snapshot."""
    directory, command = fake_driver(tmp_path, "juzzy", mode, delay_stderr=cancel)
    task = asyncio.create_task(run_media_process(command, 2))
    for _ in range(200):
        if (directory / "pid").exists():
            break
        await asyncio.sleep(0.005)
    assert (directory / "pid").exists()
    if mode == "block_tree":
        for _ in range(100):
            if (directory / "child-pid").exists():
                break
            await asyncio.sleep(0.005)
        assert (directory / "child-pid").exists()
    if cancel:
        assert not (directory / "stderr-ready").exists()
        (directory / "stderr-release").write_text("release complete payload")
    for _ in range(200):
        if (directory / "stderr-ready").exists():
            break
        await asyncio.sleep(0.005)
    assert (directory / "stderr-ready").read_text() == "160000"
    if cancel:
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else TimeoutError):
        await task
    value = json.loads((directory / "native-diagnostic.json").read_bytes())
    record_property("diagnostic", json.dumps(value, sort_keys=True))
    record_property(
        "owned_pids", json.dumps({p.name: int(p.read_text()) for p in directory.glob("*pid")})
    )
    assert value["observation"] == "interrupted"
    assert value["terminal"] and value["stderr_drain_joined"] and value["native_process_joined"]
    assert len((directory / "native-stderr.bin").read_bytes()) == 65536
    assert value["stderr"]["observed_bytes"] == 160000 and value["stderr"]["eof"]
    assert value["stderr"]["truncated"]
    with pytest.raises(ProcessLookupError):
        os.kill(int((directory / "pid").read_text()), 0)
    with pytest.raises(ProcessLookupError):
        os.kill(int((directory / "helper-pid").read_text()), 0)
    if mode == "block_tree":
        with pytest.raises(ProcessLookupError):
            os.kill(int((directory / "child-pid").read_text()), 0)
    assert not any(not t.done() for t in asyncio.all_tasks() if t is not asyncio.current_task())


async def test_pid_markers_precede_delayed_stderr_completion(tmp_path, record_property):
    """GIVEN a writer held after PID publication WHEN cancelled early THEN retain only observed bytes."""
    directory, command = fake_driver(tmp_path, "juzzy", "block_tree", delay_stderr=True)
    task = asyncio.create_task(run_media_process(command, 5))
    async with asyncio.timeout(2):
        while not (directory / "child-pid").exists():
            await asyncio.sleep(.005)
    assert (directory / "pid").exists() and not (directory / "stderr-ready").exists()
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    value = json.loads((directory / "native-diagnostic.json").read_bytes())
    record_property("diagnostic", json.dumps(value, sort_keys=True))
    assert value["stderr"]["observed_bytes"] == value["stderr"]["retained_bytes"] == 0
    assert value["stderr"]["truncated"] is False and value["stderr"]["eof"]
    assert value["native_process_joined"] and value["stderr_drain_joined"]
    pids = [int(p.read_text()) for p in directory.glob("*pid")]
    record_property("owned_pids", json.dumps(pids))
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)
    assert not any(not t.done() for t in asyncio.all_tasks() if t is not asyncio.current_task())


async def controller_fixture(tmp_path, monkeypatch, mode):
    """Use the project controller fixtures with a real first-party optional helper."""
    directory, _ = fake_driver(tmp_path, "juzzy", mode)
    original = tmp_path / "source.wav"
    original.write_bytes(b"fixed original research fixture")
    monkeypatch.setattr(
        config,
        "_config",
        config.ServerConfig(
            gemini_api_key="fixture", cache_dir=str(tmp_path), media_acquire_timeout_seconds=2
        ),
    )
    configured = {
        "backend": "juzzy",
        "source": audio_dsp_backend.SOURCES["juzzy"],
        "executable": str(directory / "server"),
        "sha256": hashlib.sha256((directory / "server").read_bytes()).hexdigest(),
    }
    monkeypatch.setattr(audio_dsp, "profile", lambda _: configured)

    async def runtime(*args):
        return {
            "optional": {
                "sha256": configured["sha256"],
                "source": configured["source"],
                "backend": "juzzy",
            }
        }

    async def source(owned):
        return {"sha256": owned.sha256, "audio_end_seconds": 1, "first_audio_seconds": 0}

    async def analyze(owned, *args):
        artifact = owned.directory / "selected.wav"
        artifact.write_bytes(b"owned selected fixture")
        row = {
            "path": str(artifact),
            "sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
            "bytes": artifact.stat().st_size,
            "mime": "audio/wav",
            "source_clock": {"first_seconds": 0},
            "source_reference": "urn:sha256:" + owned.sha256 + "#t=0,1",
            "frames": 8192,
        }
        return {"selection": row, "measurements": {}}, b"", [row]

    monkeypatch.setattr(audio_dsp, "runtime_binding", runtime)
    monkeypatch.setattr(audio_dsp, "audio_source", source)
    monkeypatch.setattr(audio_dsp, "analyze_one", analyze)
    request = AudioDspRequest(
        file_path=str(original),
        expected_source_sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        operation="audio_info",
        end_seconds=1,
        job_id="diagnostic-job",
    )
    return request


@pytest.mark.parametrize("mode", ["empty", "block", "cancel", "killed_helper"])
async def test_failed_and_cancelled_job_diagnostics_survive_staging_removal(
    tmp_path, monkeypatch, mode, record_property
):
    """GIVEN the actual caller WHEN staging is removed THEN safe metadata remains attested and replayable."""
    request = await controller_fixture(tmp_path, monkeypatch, "block" if mode == "cancel" else mode)
    task = asyncio.create_task(audio_dsp.execute(request))
    if mode == "cancel":
        for _ in range(300):
            if list((tmp_path / "media").rglob("pid")):
                break
            await asyncio.sleep(0.005)
        assert list((tmp_path / "media").rglob("pid"))
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        result = await task
        assert result["metadata"]["status"] == "failed"
    assert list((tmp_path / "media/views").iterdir()) == []
    job = JobStore().get("diagnostic-job")
    assert job["status"] == ("cancelled" if mode == "cancel" else "failed")
    value = retained(job)
    record_property("failed_job_readback", json.dumps(value, sort_keys=True))
    diagnostic = value["metadata"]["diagnostics"]
    assert diagnostic["job_request_sha256"] == job["request_sha256"]
    assert diagnostic["component_revision"] == job["source_revision"]
    assert diagnostic["source"] == audio_dsp_backend.SOURCES["juzzy"]
    assert diagnostic["helper_terminal"] is (mode != "killed_helper")
    if mode == "killed_helper":
        assert diagnostic["native_returncode"] is None
        assert diagnostic["stderr"]["observed_bytes"] is None
        assert diagnostic["stderr"]["truncated"] is None
        assert not diagnostic["native_process_joined"] and not diagnostic["stderr_drain_joined"]
    assert value["job_receipt"]["attestation"]["verified"] and job["attempts"] == 1
    assert "private-native-token" not in json.dumps(value)
    replay = await audio_dsp.execute(request)
    assert replay["metadata"] == value["metadata"]
    assert JobStore().get("diagnostic-job")["attempts"] == 1
    hostile = copy.deepcopy(job)
    hostile["result"]["diagnostics"]["job_request_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="diagnostic"):
        retained(hostile)


@pytest.mark.parametrize(
    "mutate",
    ["request", "helper", "executable", "extra", "pending_terminal", "oversize", "link", "nested"],
)
async def test_hostile_or_mismatched_helper_diagnostic_is_rejected(tmp_path, mutate):
    """GIVEN untrusted helper data WHEN identity or schema differs THEN reject before public readback."""
    directory, command = fake_driver(tmp_path, "juzzy", "empty")
    with pytest.raises(RuntimeError):
        await run_media_process(command, 5)
    path = directory / "native-diagnostic.json"
    value = json.loads(path.read_bytes())
    binding = {
        key: value[key]
        for key in ("request_sha256", "helper_sha256", "executable_sha256", "backend", "tool")
    }
    if mutate in ("request", "helper", "executable"):
        value[mutate + "_sha256"] = "b" * 64
    elif mutate == "extra":
        value["raw_stderr"] = "private-native-token"
    elif mutate == "pending_terminal":
        value["terminal"] = False
    elif mutate == "oversize":
        path.write_bytes(b"x" * (65536 + 1))
    elif mutate == "nested":
        path.write_bytes(b"[" * 60000)
    elif mutate == "link":
        path.unlink()
        path.symlink_to(directory / "request.json")
    if mutate not in ("oversize", "link", "nested"):
        path.write_bytes(canonical(value))
    with pytest.raises(ValueError, match="diagnostic"):
        read_diagnostic(directory, binding)


@pytest.mark.parametrize("mutate", ["phase", "line", "notifications"])
async def test_inconsistent_observations_rejected(tmp_path, mutate):
    """GIVEN correctly bound data WHEN the claimed boundary contradicts counts THEN reject it."""
    directory, command = fake_driver(tmp_path, "juzzy", "empty")
    with pytest.raises(RuntimeError):
        await run_media_process(command, 5)
    path = directory / "native-diagnostic.json"
    value = json.loads(path.read_bytes())
    binding = {
        key: value[key]
        for key in ("request_sha256", "helper_sha256", "executable_sha256", "backend", "tool")
    }
    if mutate == "phase":
        value["phase"] = None
    elif mutate == "line":
        value["observation"] = "line_overflow"
    else:
        value["observation"] = "notification_exhaustion"
    path.write_bytes(canonical(value))
    with pytest.raises(ValueError, match="diagnostic"):
        read_diagnostic(directory, binding)


@pytest.mark.parametrize(
    ("fault", "ending"),
    [
        ("nested", "cancel"),
        ("nested", "timeout"),
        ("changed_helper", "failure"),
        ("changed_helper", "cancel"),
        ("absent", "failure"),
    ],
)
async def test_native_caller_repair_preserves_terminal_semantics(
    tmp_path, monkeypatch, fault, ending, record_property
):
    """GIVEN malformed/absent/changed-helper data WHEN real owned work ends THEN checkpoint its true ending."""
    value = await controller_fixture(
        tmp_path, monkeypatch, "empty" if ending == "failure" else "block"
    )
    if fault == "changed_helper":
        helper = tmp_path / "audio_dsp_stdio.py"
        helper.write_bytes(
            Path(audio_dsp_stdio.__file__).read_bytes()
            + b"\n# changed first-party helper fixture\n"
        )
        monkeypatch.setattr(audio_dsp_backend, "__file__", str(tmp_path / "audio_dsp_backend.py"))
    original = audio_dsp_backend.run_media_process
    pids = []

    async def run(command, timeout):
        assert timeout <= 5
        try:
            return await original(command, timeout)
        except BaseException:
            directory = Path(command[-1]).parent
            pids.extend(int((directory / name).read_text()) for name in ("pid", "helper-pid"))
            path = directory / "native-diagnostic.json"
            if fault == "nested":
                path.write_bytes(b"[" * 60000)
            elif fault == "absent":
                path.unlink(missing_ok=True)
            raise

    monkeypatch.setattr(audio_dsp_backend, "run_media_process", run)
    task = asyncio.create_task(audio_dsp.execute(value))
    if ending == "cancel":
        for _ in range(300):
            if list((tmp_path / "media").rglob("pid")):
                break
            await asyncio.sleep(0.005)
        assert list((tmp_path / "media").rglob("pid"))
        task.cancel()
    propagated = None
    try:
        await task
    except BaseException as error:
        propagated = error
    job = JobStore().get("diagnostic-job")
    record_property("terminal_job", json.dumps(job, sort_keys=True))
    record_property("owned_pids", json.dumps(pids))
    record_property("propagated_exception", type(propagated).__name__)
    assert job["status"] == ("cancelled" if ending == "cancel" else "failed")
    metadata = retained(job)["metadata"]
    assert "diagnostics" not in metadata
    assert metadata.get("diagnostic_rejected", False) is (fault != "absent")
    assert (
        isinstance(propagated, asyncio.CancelledError) if ending == "cancel" else propagated is None
    )
    if ending == "timeout":
        assert "2-second deadline" in metadata["error"]
    assert list((tmp_path / "media/views").iterdir()) == []
    assert (await audio_dsp.execute(value))["metadata"] == metadata
    assert JobStore().get("diagnostic-job")["attempts"] == 1
    for pid in pids:
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)


@pytest.mark.parametrize("kind", ["absent", "dangling"])
def test_missing_diagnostic_is_unknown_but_dangling_link_rejected(tmp_path, kind):
    """GIVEN no real diagnostic WHEN reading THEN distinguish absence from a hostile symlink."""
    if kind == "dangling":
        (tmp_path / "native-diagnostic.json").symlink_to(tmp_path / "nonexistent")
        with pytest.raises(ValueError, match="diagnostic"):
            read_diagnostic(tmp_path, {})
    else:
        assert read_diagnostic(tmp_path, {}) is None


async def test_native_controller_success_preserves_payload(tmp_path, monkeypatch, record_property):
    """GIVEN configured first-party native success WHEN execute publishes THEN preserve success and replay."""
    value = await controller_fixture(tmp_path, monkeypatch, "success")
    result = await audio_dsp.execute(value)
    record_property("successful_controller", json.dumps(result, sort_keys=True))
    metadata = result["metadata"]
    assert metadata["status"] == "complete" and result["job_receipt"]["attestation"]["verified"]
    assert set(metadata) == {
        "status",
        "operation",
        "analyses",
        "comparison",
        "native",
        "artifacts",
        "limits",
        "provenance",
        "result_artifact",
        "manifest",
    }
    assert "diagnostics" not in metadata and "diagnostic_rejected" not in metadata
    native = metadata["native"]
    body = Path(native["path"]).read_bytes()
    assert hashlib.sha256(body).hexdigest() == native["sha256"]
    assert json.loads(body)["result"] == {
        "content": [{"type": "text", "text": "Native heuristic fixture, no factual acceptance"}]
    }
    assert native["source"] == audio_dsp_backend.SOURCES["juzzy"]
    assert native["results_are_untrusted_native_observations"] and native["process_joined"]
    assert native["declared_source_build_provenance_verified"] is False
    exported = json.loads(Path(metadata["result_artifact"]["path"]).read_bytes())
    assert exported["native"] == native and exported["status"] == "complete"
    assert "diagnostics" not in exported and "diagnostic_rejected" not in exported
    assert (await audio_dsp.execute(value))["metadata"] == metadata
    assert JobStore().get("diagnostic-job")["attempts"] == 1
    with pytest.raises(ProcessLookupError):
        os.kill(native["pid"], 0)


async def test_ferrous_phase4_is_observed_request_metadata(tmp_path, record_property):
    """GIVEN a process-local native job WHEN its phase4 read closes THEN retain observation without attestation."""
    directory, command = fake_driver(tmp_path, "ferrous", "phase4_empty")
    with pytest.raises(RuntimeError):
        await run_media_process(command, 5)
    body = (directory / "request.json").read_bytes()
    helper_hash = hashlib.sha256(Path(audio_dsp_stdio.__file__).read_bytes()).hexdigest()
    binding = request_binding(body, helper_hash)
    diagnostic = read_diagnostic(directory, binding)
    record_property("phase4_observation", json.dumps(diagnostic, sort_keys=True))
    message = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {"name": "get_job_status", "arguments": {"job_id": "native-1"}},
    }
    assert diagnostic["phase"] == {
        "id": 4,
        "method": "tools/call",
        "request_sha256": hashlib.sha256(audio_dsp_stdio.encode(message)).hexdigest(),
    }
    assert diagnostic["observation"] == "empty_eof" and diagnostic["response_bytes"] == 0
    assert (
        diagnostic["helper_terminal"]
        and diagnostic["native_process_joined"]
        and diagnostic["stderr_drain_joined"]
    )
    assert "native_job_observation" not in diagnostic and "attestation" not in diagnostic
    assert not (directory / "native-response.json").exists()
    wrong = {**binding, "backend": "juzzy", "tool": "audio_info"}
    with pytest.raises(ValueError, match="diagnostic"):
        read_diagnostic(directory, wrong)
    for name in ("pid", "helper-pid"):
        with pytest.raises(ProcessLookupError):
            os.kill(int((directory / name).read_text()), 0)
