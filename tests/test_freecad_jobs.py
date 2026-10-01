"""Bounded async receipts using pure computation and synthetic native processes."""

from importlib.util import module_from_spec, spec_from_file_location
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest


spec = spec_from_file_location("freecad_jobs", Path(__file__).parents[1] / "scripts/freecad_jobs.py")
jobs = module_from_spec(spec)
spec.loader.exec_module(jobs)


@pytest.fixture
def session(tmp_path):
    """Provide a receipt directory without any external package/native app."""
    (tmp_path / "jobs").mkdir()
    return {"output": str(tmp_path), "session": "owned-session"}


def await_terminal(session, job_id):
    """Read a bounded local receipt until its pure test worker terminates."""
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        result = jobs.read_receipt(session, job_id)
        if result["state"] != "pending":
            return result
        time.sleep(0.005)
    pytest.fail("Test computation did not terminate")


def test_async_completion_retains_output_and_module_result(session):
    """GIVEN pure trusted work WHEN queued THEN pending is distinct from verified completion."""
    namespace = {}
    native = jobs.NativeJobs(session, namespace)
    start = native.start("answer = 6 * 7\nprint(answer)")
    assert start["state"] == "pending" and start["success"]
    terminal = await_terminal(session, start["job_id"])
    native.close()
    assert terminal["state"] == "complete" and terminal["output"] == "42\n"
    assert namespace["answer"] == 42
    assert not native.worker.is_alive() and not native.watchdog.is_alive()


def test_async_error_retained_with_traceback(session):
    """GIVEN code error WHEN execution ends THEN failure and preceding output are durable."""
    native = jobs.NativeJobs(session, {})
    start = native.start("print('before')\nraise ValueError('retained failure')")
    result = await_terminal(session, start["job_id"])
    native.close()
    assert result["state"] == "failed" and result["output"] == "before\n"
    assert "retained failure" in result["error"] and "ValueError" in result["traceback"]


def test_one_pending_native_job_and_fixed_timeout_receipt(session, monkeypatch):
    """GIVEN hung work WHEN the deadline expires THEN terminal timeout survives late return."""
    monkeypatch.setattr(jobs, "DEADLINE", 0.03)
    gate, terminated = threading.Event(), threading.Event()
    native = jobs.NativeJobs(session, {"gate": gate}, terminated.set)
    start = native.start("gate.wait()")
    assert not native.start("print('second')")["success"]
    result = await_terminal(session, start["job_id"])
    assert result["state"] == "timed_out"
    assert terminated.wait(1)
    gate.set()
    native.close()
    assert jobs.read_receipt(session, start["job_id"])["state"] == "timed_out"


@pytest.mark.parametrize("job_id", ["../escape", "/tmp/foreign", "not-a-job", "a" * 31])
def test_receipt_path_identifier_refused(session, job_id):
    """GIVEN a foreign path WHEN status is read THEN only owned job identifiers are admitted."""
    with pytest.raises(ValueError, match="identifier"):
        jobs.read_receipt(session, job_id)


def test_receipt_foreign_session_and_symlink_refused(session, tmp_path):
    """GIVEN a replaced receipt WHEN read THEN session and containment must still match."""
    job_id = "a" * 32
    path = Path(session["output"]) / "jobs" / f"{job_id}.json"
    jobs.write_receipt(path, {"job_id": job_id, "session": "foreign", "state": "complete"})
    with pytest.raises(ValueError, match="different native session"):
        jobs.read_receipt(session, job_id)
    path.unlink()
    outside = tmp_path / "outside.json"
    outside.write_text("{}")
    path.symlink_to(outside)
    with pytest.raises(ValueError, match="escapes"):
        jobs.read_receipt(session, job_id)


def test_monitor_terminates_native_then_retains_deadline_failure(session, monkeypatch):
    """GIVEN a pending expired job WHEN monitored THEN cleanup happens before terminal receipt."""
    job_id = "b" * 32
    path = Path(session["output"]) / "jobs" / f"{job_id}.json"
    jobs.write_receipt(path, {"job_id": job_id, "session": session["session"],
                              "state": "pending", "started": time.time() - 100})
    cleaned = threading.Event()
    monitor = jobs.JobMonitor(session, SimpleNamespace(poll=lambda: None), cleaned.set)
    monitor.job_id = job_id
    result = await_terminal(session, job_id)
    monitor.close()
    assert cleaned.is_set() and result["state"] == "timed_out"
    assert not monitor.thread.is_alive()


def test_status_survives_failed_native_and_eof_joins_monitor(session):
    """GIVEN closed native with pending work WHEN EOF closes monitor THEN status remains failed."""
    job_id = "c" * 32
    path = Path(session["output"]) / "jobs" / f"{job_id}.json"
    jobs.write_receipt(path, {"job_id": job_id, "session": session["session"],
                              "state": "pending", "started": time.time()})
    monitor = jobs.JobMonitor(session, SimpleNamespace(poll=lambda: 1), lambda: None)
    monitor.job_id = job_id
    monitor.close()
    assert not monitor.thread.is_alive()
    assert jobs.read_receipt(session, job_id)["state"] == "failed"


def test_pending_job_rejects_sync_tools_and_status_remains_available(session):
    """GIVEN pending async work WHEN sync CAD is requested THEN it fails before native admission."""
    class Spec:
        def __init__(self, name, description="", schema=None, model=None, handle=lambda args: []):
            self.name, self.handle = name, handle
    framework = SimpleNamespace(ToolSpec=Spec, tool_schema=lambda model: {})
    monitor = SimpleNamespace(pending=lambda: True)
    connection = SimpleNamespace(vrm_identity=lambda: pytest.fail("native admission"))
    specs = jobs.configure_specs([Spec("execute_code")], framework, connection, session,
                                None, lambda: None, monitor, None)
    with pytest.raises(ValueError, match="pending"):
        specs[0].handle({"code": "print('must not run')"})
    job_id = "d" * 32
    jobs.write_receipt(Path(session["output"]) / "jobs" / f"{job_id}.json",
                       {"job_id": job_id, "session": session["session"], "state": "pending"})
    result = specs[1].handle({"job_id": job_id})
    assert json.loads(result[0]["text"])["state"] == "pending"


@pytest.mark.parametrize("change", ["empty_mapping", "missing_success", "empty_result", "null_stress", "zero_nodes",
                                    "nan_displacement", "foreign_working_dir", "empty_result_object"])
def test_fem_malformed_or_empty_success_is_explicit_failure(session, change, tmp_path):
    """GIVEN measured malformed/degenerate native results WHEN promoted THEN explicit failure retains evidence."""
    original = {"success": True, "summary": "stock claimed solved", "node_count": 100,
                "max_von_mises_MPa": 12.3, "max_displacement_mm": 0.1,
                "result_object": "Result", "working_dir": str(tmp_path)}
    if change == "empty_mapping":
        original = {}
    elif change == "missing_success":
        original = {"summary": "stock failed: None"}
    elif change == "empty_result":
        original.update(node_count=0, max_von_mises_MPa=None, max_displacement_mm=None)
    elif change == "null_stress":
        original["max_von_mises_MPa"] = None
    elif change == "zero_nodes":
        original["node_count"] = 0
    elif change == "nan_displacement":
        original["max_displacement_mm"] = float("nan")
    elif change == "foreign_working_dir":
        original["working_dir"] = "/"
    else:
        original["result_object"] = ""
    response = jobs.normalize_fem([{"type": "text", "text": json.dumps(original)}], session)
    result = json.loads(response[0]["text"])
    assert result["success"] is False
    assert result["upstream_result"].get("summary") == original.get("summary")
    assert "completion contract" in result["summary"]


def test_fem_valid_nonempty_owned_result_and_native_failure_preserved(session):
    """GIVEN valid completion or explicit native failure WHEN normalized THEN original fields remain."""
    valid = {"success": True, "node_count": 4, "max_von_mises_MPa": 1.0,
             "max_displacement_mm": 0.01, "result_object": "Result",
             "working_dir": session["output"]}
    failure = {"success": False, "error": "Prerequisites failed", "working_dir": session["output"]}
    for suffix in (".inp", ".frd", ".dat"):
        (Path(session["output"]) / ("fixture" + suffix)).write_text("actual stub output")
    for result in (valid, failure):
        blocks = [{"type": "text", "text": json.dumps(result)}]
        assert jobs.normalize_fem(blocks, session) == blocks


def configured_handler(name, handler, session, cleanup=lambda: None, verify=lambda *a: None):
    """Bind a concrete caller to owned policy without an external framework import."""
    class Spec:
        def __init__(self, name, description="", schema=None, model=None, handle=handler):
            self.name, self.handle = name, handle
    framework = SimpleNamespace(ToolSpec=Spec, tool_schema=lambda model: {})
    connection = SimpleNamespace(vrm_identity=lambda: {"documents": ["Owned"], "active": "Owned"})
    owned = {**session, "document": "Owned"}
    return jobs.configure_specs([Spec(name)], framework, connection, owned, None,
                                cleanup, SimpleNamespace(pending=lambda: False), verify)[0].handle


@pytest.mark.parametrize("requested,received", [(5, 5), (600, 60)])
def test_fem_requested_timeout_is_capped_without_expansion(session, requested, received):
    """GIVEN caller timeout WHEN FEM dispatches THEN a smaller promised wait survives."""
    seen = []
    def native(arguments):
        seen.append(arguments["timeout"])
        return [{"type": "text", "text": json.dumps({"success": False, "error": "fixed prerequisite failure"})}]
    handler = configured_handler("run_fem_analysis", native, session)
    handler({"doc_name": "Owned", "analysis_name": "Analysis", "timeout": requested})
    assert seen == [received]


@pytest.mark.parametrize("requested", [0, -1])
def test_nonpositive_fem_timeout_fails_before_native(session, requested):
    """GIVEN invalid timeout WHEN dispatched THEN no native identity/work is requested."""
    handler = configured_handler("run_fem_analysis", lambda a: pytest.fail("native work"), session)
    with pytest.raises(ValueError, match="positive"):
        handler({"doc_name": "Owned", "analysis_name": "Analysis", "timeout": requested})


def test_queued_callers_cannot_outlive_complete_deadline(session, monkeypatch):
    """GIVEN serialized work within individual limits WHEN queue expires THEN late success is refused."""
    monkeypatch.setattr(jobs, "DEADLINE", .2)
    reaped = threading.Event()
    start = threading.Barrier(3)
    def native(arguments):
        time.sleep(.12)
        return []
    def verify(*arguments):
        if reaped.is_set():
            raise RuntimeError("owned native reaped")
    handler = configured_handler("execute_code", native, session, reaped.set, verify)
    def caller(n):
        start.wait()
        began = time.monotonic()
        try:
            handler({"code": str(n)})
            return "success", time.monotonic() - began
        except (RuntimeError, TimeoutError):
            return "refused", time.monotonic() - began
    with ThreadPoolExecutor(3) as pool:
        outcomes = list(pool.map(caller, range(3)))
    assert reaped.is_set()
    assert sum(state == "success" for state, _ in outcomes) == 1
    assert max(duration for _, duration in outcomes) < .32


@pytest.mark.parametrize("change", ["missing", "empty", "different_stem", "escape"])
def test_fem_completion_requires_actual_corresponding_artifacts(session, tmp_path, change):
    """GIVEN positive native results WHEN advertised directory lacks its artifacts THEN promotion fails."""
    work = Path(session["output"]) / "work"
    work.mkdir()
    for suffix in (".inp", ".frd", ".dat"):
        (work / ("fixture" + suffix)).write_text("actual stub output")
    result = {"success": True, "node_count": 4, "max_von_mises_MPa": 1,
              "max_displacement_mm": .001, "result_object": "Result", "working_dir": str(work)}
    frd = work / "fixture.frd"
    if change == "missing":
        frd.unlink()
    elif change == "empty":
        frd.write_text("")
    elif change == "different_stem":
        frd.rename(work / "unrelated.frd")
    else:
        frd.unlink()
        outside = tmp_path / "outside.frd"
        outside.write_text("foreign output")
        frd.symlink_to(outside)
    promoted = json.loads(jobs.normalize_fem([{"type": "text", "text": json.dumps(result)}], session)[0]["text"])
    assert promoted["success"] is False and promoted["upstream_result"] == result
