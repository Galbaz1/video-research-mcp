"""Actual owned byte/worker lifecycle with inert original-handler/process contracts."""

import base64
import io
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import blender_stdio
import core_dispatch as dispatch
import core_inputs
import core_session


def setup(tmp_path, body=b"one\ntwo\n", extension=".py"):
    """Provide only independently authored source bytes and original-handler contracts."""
    source = tmp_path / ("operator" + extension)
    source.write_bytes(body)
    row = {"path": str(source), "bytes": len(body), "sha256": core_inputs.sha256(body)}
    authority = core_inputs.write_json(tmp_path / "inputs.json", {"schema_version": 1, "files": [row]})
    selected = core_inputs.Inputs(authority["path"], authority["sha256"])
    output = core_session.prepare_session(tmp_path / "session")
    data = {"family_extensions": {"code": [".py"], "subtitle": [".srt"], "image": [".png"], "pdf": [".pdf"]},
            "format_clearance": {name: {"state": "verified-selected-format-profile"} for name in ("code", "subtitle", "image")},
            "runtime_fields": {"python_executable": "/selected/python"}}
    args = SimpleNamespace(source_root=tmp_path, manifest=tmp_path / "descriptor.json", manifest_sha256="a" * 64,
                           inputs=Path(authority["path"]), inputs_sha256=authority["sha256"])
    boundary = dispatch.Dispatch(args, data, selected, output, selected.readback, dispatch.Barrier(output))
    return boundary, row


def call_directory(boundary):
    directory = boundary.output / "calls" / "test-job"
    directory.mkdir()
    for leaf in ("inputs", "products"):
        (directory / leaf).mkdir()
    return directory


def selection(boundary, row, directory):
    return dispatch.prepare_call("visualize", {"file_path": row["path"], "max_pages": 4}, boundary.data, boundary.inputs, directory)


def image_block(body=None):
    if body is None:
        buffer = io.BytesIO()
        Image.new("RGB", (4, 3), (200, 10, 20)).save(buffer, format="PNG")
        body = buffer.getvalue()
    return {"type": "image", "data": base64.b64encode(body).decode(), "mimeType": "image/png"}


def fake_launch(boundary, monkeypatch, blocks=None, mutate=None):
    """Replace only external process execution; retain result persistence and core readback."""
    def launch(directory, job, deadline):
        if mutate:
            mutate()
        result = dispatch.content_result(blocks or [{"type": "text", "text": "```py\none\ntwo\n```"}], job["selection"], directory)
        binding = core_inputs.write_json(directory / "result.json", result, core_inputs.RESULT_BYTES)
        return result, binding
    monkeypatch.setattr(boundary, "launch", launch)


@pytest.mark.parametrize("name", ["read_video", "media_info", "save_view", "draw_bbox"])
def test_native_font_tools_refuse_before_original_handler(tmp_path, monkeypatch, name):
    boundary, row = setup(tmp_path)
    monkeypatch.setattr(boundary, "launch", lambda *_: pytest.fail("unqualified handler was invoked"))
    key = {"read_video": "video_path", "media_info": "path", "save_view": "file_path", "draw_bbox": "image_path"}[name]
    blocks = boundary.call(name, {key: row["path"]})
    metadata = json.loads(blocks[-1]["text"])["core_session"]
    assert metadata["state"] == "failed" and "handler was not invoked" in metadata["reason"]
    assert core_inputs.verify(row) == b"one\ntwo\n"


@pytest.mark.parametrize("arguments", [{"max_pages": 20}, {"pages": "1-5", "max_pages": 4}, {"pages": "2", "max_pages": 4}, {"file_path": "https://example.test/code.py"}, {"output_path": "/original/overwrite"}])
def test_ranges_url_and_external_outputs_refused_before_call(tmp_path, monkeypatch, arguments):
    boundary, row = setup(tmp_path)
    monkeypatch.setattr(boundary, "launch", lambda *_: pytest.fail("inadmitted handler"))
    result = boundary.call("visualize", {"file_path": row["path"], **arguments})
    assert json.loads(result[-1]["text"])["core_session"]["state"] == "failed"


def test_heavy_family_refused_but_explicit_denominator_preserved(tmp_path, monkeypatch):
    boundary, row = setup(tmp_path, extension=".pdf")
    monkeypatch.setattr(boundary, "launch", lambda *_: pytest.fail("PDF engine"))
    result = boundary.call("visualize", {"file_path": row["path"], "max_pages": 4})
    assert "unavailable" in json.loads(result[0]["text"])["core_session"]["reason"]


@pytest.mark.parametrize("lines,expected", [(2, "complete"), (501, "partial")])
def test_complete_vs_actual_original_code_line_cap(tmp_path, lines, expected):
    boundary, row = setup(tmp_path, b"line\n" * lines)
    directory = call_directory(boundary)
    selected = selection(boundary, row, directory)
    result = dispatch.content_result([{"type": "text", "text": "actual original fence"}], selected, directory)
    assert result["state"] == expected
    assert result["coverage"]["skipped_lines"] == max(0, lines - 500)
    assert result["blocks"][0]["text"] == "actual original fence"


@pytest.mark.parametrize("text,state", [("Error: refused", "failed"), ("Error rendering .py file", "failed"), ("Warning: no output", "abstained"), ("actual cue", "complete")])
def test_error_abstention_and_actual_subtitle_text_are_distinct(tmp_path, text, state):
    boundary, row = setup(tmp_path, b"cue\n", ".srt")
    directory = call_directory(boundary)
    result = dispatch.content_result([{"type": "text", "text": text}], selection(boundary, row, directory), directory)
    assert result["state"] == state
    assert result["coverage"]["timestamp_alignment_validated"] is False


@pytest.mark.parametrize("blocks", [[], [{"type": "audio", "data": "x"}], [{"type": "text", "text": 1}], [{"type": "text", "text": "x" * core_inputs.RESULT_BYTES}], [{"type": "image", "data": "not-base64", "mimeType": "image/png"}]])
def test_malformed_and_oversized_return_refused_without_truncation(tmp_path, blocks):
    boundary, row = setup(tmp_path)
    directory = call_directory(boundary)
    with pytest.raises((ValueError, KeyError)):
        dispatch.content_result(blocks, selection(boundary, row, directory), directory)


def test_actual_encoded_image_and_pixels_are_bound(tmp_path):
    boundary, row = setup(tmp_path)
    directory = call_directory(boundary)
    block = image_block()
    result = dispatch.content_result([block], selection(boundary, row, directory), directory)
    image = result["images"][0]
    assert core_inputs.verify(image) == base64.b64decode(block["data"])
    assert image["dimensions"] == [4, 3]
    assert image["pixel_sha256"] == core_inputs.sha256(bytes([200, 10, 20, 255]) * 12)


def test_actual_image_format_cannot_be_relabelled(tmp_path):
    boundary, row = setup(tmp_path)
    directory = call_directory(boundary)
    block = {**image_block(), "mimeType": "image/jpeg"}
    with pytest.raises(ValueError, match="MIME"):
        dispatch.content_result([block], selection(boundary, row, directory), directory)


def test_crop_saved_product_not_silently_unbound(tmp_path):
    boundary, row = setup(tmp_path)
    directory = call_directory(boundary)
    selected = selection(boundary, row, directory)
    body = base64.b64decode(image_block()["data"])
    (directory / "products/result.png").write_bytes(body)
    result = dispatch.content_result([{"type": "text", "text": "Saved crop"}], selected, directory)
    assert result["artifacts"][0]["sha256"] == core_inputs.sha256(body)


def test_large_valid_text_durable_receipt_does_not_duplicate_raw_text(tmp_path, monkeypatch):
    boundary, row = setup(tmp_path)
    fake_launch(boundary, monkeypatch, [{"type": "text", "text": "x" * 200000}])
    blocks = boundary.call("visualize", {"file_path": row["path"], "max_pages": 4})
    metadata = json.loads(blocks[-1]["text"])["core_session"]
    assert metadata["state"] == "complete"
    assert len(blocks[0]["text"]) == 200000


def test_source_change_after_handler_refuses_and_preserves_pending_evidence(tmp_path, monkeypatch):
    boundary, row = setup(tmp_path)
    fake_launch(boundary, monkeypatch, mutate=lambda: Path(row["path"]).write_bytes(b"changed"))
    blocks = boundary.call("visualize", {"file_path": row["path"], "max_pages": 4})
    metadata = json.loads(blocks[-1]["text"])["core_session"]
    assert metadata["state"] == "failed"
    directory = next((boundary.output / "calls").iterdir())
    assert (directory / "result.json").exists() and (directory / "receipt.json").exists()


def test_whole_handler_lock_includes_result_readback(tmp_path, monkeypatch):
    boundary, row = setup(tmp_path)
    active, overlap, calls = 0, [], []
    def launch(directory, job, deadline):
        nonlocal active
        active += 1
        overlap.append(active)
        time.sleep(0.02)
        result = {"state": "complete", "blocks": [{"type": "text", "text": "actual"}]}
        binding = core_inputs.write_json(directory / "result.json", result)
        active -= 1
        return result, binding
    monkeypatch.setattr(boundary, "launch", launch)
    threads = [threading.Thread(target=lambda: calls.append(boundary.call("visualize", {"file_path": row["path"], "max_pages": 4}))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(1)
    assert len(calls) == 2 and max(overlap) == 1


def test_queued_admission_deadline_has_terminal_receipt(tmp_path, monkeypatch):
    boundary, row = setup(tmp_path)
    boundary.lock = SimpleNamespace(acquire=lambda **_: False)
    result = boundary.call("visualize", {"file_path": row["path"]})
    assert result
    receipts = list((boundary.output / "calls").glob("*/receipt.json"))
    assert len(receipts) == 1 and json.loads(receipts[0].read_bytes())["state"] == "failed"


@pytest.mark.parametrize("event,arguments", [("socket.connect", (1, "address")), ("subprocess.Popen", ("native", ["native"])), ("os.system", ("native",)), ("os.posix_spawn", ("native", [], {})), ("import", ("shared.api_openai",)), ("import", ("matplotlib",)), ("open", ("/unowned/file", "w", os.O_WRONLY)), ("os.putenv", (b"QWEN_MM_NATIVE_MODE", b"0"))])
def test_python_denial_survives_swallowed_original_exception(tmp_path, event, arguments):
    boundary = dispatch.Barrier(tmp_path)
    with pytest.raises(PermissionError):
        boundary.audit(event, arguments)
    with pytest.raises(PermissionError):
        boundary.check()


class Process:
    """Owned process-group contract only; never launches a binary."""
    pid = 123456

    def __init__(self, running=False):
        self.returncode = None if running else 0
        self.waits = []

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        self.waits.append(timeout)
        return self.returncode


@pytest.mark.parametrize("wrong", [None, "pid", "session", "job_id"])
def test_exact_worker_arguments_identity_and_absent_bytecode_prefix(tmp_path, monkeypatch, wrong):
    boundary, row = setup(tmp_path)
    directory = call_directory(boundary)
    job = {"job_id": directory.name, "selection": selection(boundary, row, directory)}
    captured = {}
    process = Process()
    def popen(command, **kwargs):
        captured.update(command=command, **kwargs)
        result = {"state": "complete", "pid": process.pid, "session": str(boundary.output), "job_id": directory.name}
        if wrong:
            result[wrong] = "unrelated"
        core_inputs.write_json(directory / "result.json", result)
        return process
    monkeypatch.setattr(dispatch.subprocess, "Popen", popen)
    if wrong:
        with pytest.raises(ValueError, match="identity"):
            boundary.launch(directory, job, time.monotonic() + 30)
    else:
        result, _ = boundary.launch(directory, job, time.monotonic() + 30)
        assert result["pid"] == process.pid
    command = captured["command"]
    assert command[0:4] == ["/selected/python", "-I", "-B", "-X"]
    assert command[4] == f"pycache_prefix={directory / 'bytecode'}" and not (directory / "bytecode").exists()
    assert captured["start_new_session"] is True
    assert json.loads((directory / "process.json").read_bytes())["pid"] == process.pid


async def test_active_stdin_eof_reaps_before_shielded_handler_join(tmp_path, monkeypatch):
    boundary, row = setup(tmp_path)
    process, started, received = Process(running=True), threading.Event(), []
    def popen(*_, **kwargs):
        started.set()
        return process
    def killpg(pid, sig):
        assert pid == process.pid and sig == signal.SIGTERM
        received.append("kill")
        process.returncode = -sig
    monkeypatch.setattr(dispatch.subprocess, "Popen", popen)
    monkeypatch.setattr(dispatch.os, "killpg", killpg)
    results = []
    worker = threading.Thread(target=lambda: results.append(boundary.call("visualize", {"file_path": row["path"], "max_pages": 4})))
    worker.start()
    assert started.wait(1) and worker.is_alive()
    async def closed_stdin():
        if False:
            yield None
    class Outgoing:
        async def aclose(self):
            assert received == ["kill"] and process.waits
            received.append("stdin-closed-after-reap")
    await blender_stdio.forward_input(closed_stdin(), Outgoing(), boundary.close)
    worker.join(1)
    assert not worker.is_alive() and results
    assert json.loads(results[0][-1]["text"])["core_session"]["state"] == "interrupted"
    assert received == ["kill", "stdin-closed-after-reap"]
    assert boundary.closed and boundary.process is None


def test_deadline_kills_reaps_and_retains_terminal_failure(tmp_path, monkeypatch):
    boundary, row = setup(tmp_path)
    process, killed = Process(running=True), []
    clocks = iter([0, 0, 0, 31])
    monkeypatch.setattr(dispatch, "time", SimpleNamespace(monotonic=lambda: next(clocks, 31), sleep=lambda _: None))
    monkeypatch.setattr(dispatch.subprocess, "Popen", lambda *a, **k: process)
    def killpg(pid, sig):
        killed.append((pid, sig))
        process.returncode = -sig
    monkeypatch.setattr(dispatch.os, "killpg", killpg)
    blocks = boundary.call("visualize", {"file_path": row["path"], "max_pages": 4})
    assert json.loads(blocks[0]["text"])["core_session"]["state"] == "failed"
    assert killed == [(process.pid, signal.SIGTERM)] and process.waits
    assert boundary.process is None
    boundary.close()
    late = boundary.call("visualize", {"file_path": row["path"], "max_pages": 4})
    assert json.loads(late[0]["text"])["core_session"]["state"] == "interrupted"


@pytest.mark.parametrize("outcome", ["success", "exception", "swallowed-network"])
def test_worker_runs_original_handler_contract_and_retains_errors(tmp_path, outcome):
    boundary, row = setup(tmp_path)
    directory = call_directory(boundary)
    selected = selection(boundary, row, directory)
    job = {"directory": str(directory), "parent_pid": os.getppid(), "deadline": time.monotonic() + 30,
           "job_id": directory.name, "selection": selected, "tool": "visualize"}
    binding = core_inputs.write_json(directory / "job.json", job)
    barrier = dispatch.Barrier(boundary.output)
    def original(arguments):
        assert arguments["file_path"] == selected["copy"]["path"]
        if outcome == "exception":
            raise RuntimeError("raw provider diagnostic must not escape")
        if outcome == "swallowed-network":
            try:
                barrier.audit("socket.connect", (1, "unavailable"))
            except PermissionError:
                pass
        return [{"type": "text", "text": "actual original contract"}]
    package = SimpleNamespace(get_handler=lambda _: original)
    args = SimpleNamespace(worker_job=binding["path"], worker_sha256=binding["sha256"], output=boundary.output, source_root=tmp_path)
    code = dispatch.execute_handler(args, {}, boundary.inputs, lambda *_: (package, None, barrier), lambda *_: {"files": []})
    result = json.loads((directory / "result.json").read_bytes())
    assert code == (0 if outcome == "success" else 2)
    assert result["pid"] == os.getpid() and result["job_id"] == directory.name
    assert result["state"] == ("complete" if outcome == "success" else "failed")
    assert "raw provider diagnostic" not in json.dumps(result)


def test_entire_return_budget_refuses_instead_of_truncated_complete(tmp_path, monkeypatch):
    boundary, row = setup(tmp_path)
    fake_launch(boundary, monkeypatch, [{"type": "text", "text": "x" * (core_inputs.RESULT_BYTES - 512)}])
    result = boundary.call("visualize", {"file_path": row["path"], "max_pages": 4})
    assert json.loads(result[-1]["text"])["core_session"]["state"] == "failed"
    assert len(json.dumps(result).encode()) < core_inputs.RESULT_BYTES
