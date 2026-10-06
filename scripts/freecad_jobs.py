"""Own bounded native background jobs and durable terminal receipts.

Submitted code is trusted host code, restricted by contract to background-safe
OCCT/pure computation. These process controls are not a security sandbox.
"""

from __future__ import annotations

import contextlib
import io
import json
import math
import os
from pathlib import Path
import re
import threading
import time
import traceback
import uuid
from functools import wraps

DEADLINE = 60


def write_receipt(path: Path, value: dict) -> None:
    """Replace a receipt atomically so readers never observe partial JSON."""
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value))
    temporary.replace(path)


def read_receipt(session: dict, job_id: str) -> dict:
    """Read only a receipt whose identifier and session belong to this output."""
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        raise ValueError("Invalid owned job identifier")
    jobs = (Path(session["output"]) / "jobs").resolve()
    path = jobs / f"{job_id}.json"
    if not path.resolve().is_relative_to(jobs):
        raise ValueError("Job receipt escapes owned output")
    result = json.loads(path.read_text())
    if result["job_id"] != job_id or result["session"] != session["session"]:
        raise ValueError("Receipt belongs to a different native session")
    return result


class NativeJobs:
    """Run one native computation with an owned receipt and fatal timeout."""

    def __init__(self, session: dict, namespace: dict, terminate=None):
        self.session, self.namespace = session, namespace
        self.terminate = terminate or (lambda: os._exit(124))
        self.lock = threading.Lock()
        self.active = None
        self.worker = self.watchdog = None
        self.finished = threading.Event()

    def _save(self, result: dict) -> None:
        write_receipt(Path(self.session["output"]) / "jobs" / f"{result['job_id']}.json", result)

    def start(self, code: str) -> dict:
        """Start one trusted background-safe computation; return pending, never complete."""
        with self.lock:
            if self.active and self.active["state"] == "pending":
                return {"success": False, "error": "An owned background job is still pending"}
            self.finished = threading.Event()
            result = {"job_id": uuid.uuid4().hex, "session": self.session["session"],
                      "state": "pending", "started": time.time(), "deadline_seconds": DEADLINE}
            self.active = result
            self._save(result)
            self.worker = threading.Thread(target=self._run, args=(code, result, self.finished), daemon=True)
            self.watchdog = threading.Thread(target=self._watch, args=(result, self.finished), daemon=True)
            self.worker.start()
            self.watchdog.start()
            return {"success": True, **result}

    def _run(self, code: str, initial: dict, finished) -> None:
        output = io.StringIO()
        result = dict(initial)
        try:
            with contextlib.redirect_stdout(output):
                exec(code, self.namespace)
            result.update(state="complete", output=output.getvalue())
        except BaseException as error:
            result.update(state="failed", output=output.getvalue(), error=str(error),
                          traceback=traceback.format_exc())
        result["finished"] = time.time()
        with self.lock:
            if self.active["state"] == "pending":
                self.active = result
                self._save(result)
            finished.set()

    def _watch(self, initial: dict, finished) -> None:
        if finished.wait(DEADLINE):
            return
        fatal = False
        try:
            with self.lock:
                if self.active["state"] != "pending" or self.active["job_id"] != initial["job_id"]:
                    return
                self.active = {**initial, "state": "timed_out", "finished": time.time(),
                               "error": "Background computation exceeded 60 seconds; native terminated"}
                fatal = True
                self._save(self.active)
        finally:
            if fatal:
                self.terminate()

    def close(self) -> None:
        """Join completed native workers; a pending worker requires process termination."""
        self.finished.set()
        for thread in (self.worker, self.watchdog):
            if thread and thread is not threading.current_thread():
                thread.join(timeout=5)
        if self.worker and self.worker.is_alive():
            self.terminate()


class JobMonitor:
    """Retain job failure after native exit and bound a late background operation."""

    def __init__(self, session: dict, process, cleanup):
        self.session, self.process, self.cleanup = session, process, cleanup
        self.job_id = None
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def pending(self) -> bool:
        """Report whether the current owned receipt still permits no synchronous tools."""
        return bool(self.job_id and read_receipt(self.session, self.job_id)["state"] == "pending")

    def _run(self) -> None:
        while not self.stop.wait(0.05):
            if not self.job_id:
                continue
            result = read_receipt(self.session, self.job_id)
            if result["state"] != "pending":
                if result["state"] == "timed_out":
                    self.cleanup()
                continue
            expired = time.time() >= result["started"] + DEADLINE
            if expired or self.process.poll() is not None:
                self.cleanup()
                # Re-read after reaping: the native worker may have completed meanwhile.
                result = read_receipt(self.session, self.job_id)
                if result["state"] == "pending":
                    result.update(state="timed_out" if expired else "failed", finished=time.time(),
                                  error="Native job deadline exceeded" if expired else "Native exited")
                    write_receipt(Path(self.session["output"]) / "jobs" / f"{self.job_id}.json", result)

    def close(self) -> None:
        """Stop and join the owned monitor after native termination."""
        self.stop.set()
        if self.thread is not threading.current_thread():
            self.thread.join(timeout=5)
        if self.job_id:
            result = read_receipt(self.session, self.job_id)
            if result["state"] == "pending":
                result.update(state="failed", finished=time.time(), error="Session closed")
                write_receipt(Path(self.session["output"]) / "jobs" / f"{self.job_id}.json", result)


def validate_arguments(name: str, arguments: dict, identity: dict, session: dict) -> None:
    """Refuse foreign document names, unsafe library paths and unsaved reloads."""
    if "doc_name" in arguments and arguments["doc_name"] != session["document"]:
        raise ValueError("doc_name must match the owned session document")
    if name == "create_document":
        if arguments.get("name") != session["document"] or identity["documents"]:
            raise ValueError("create_document requires the exact owned name and an empty session")
    elif name == "insert_part_from_library":
        relative = Path(arguments["relative_path"])
        data = Path(session["data"]).resolve()
        library = (data / "Mod/parts_library").resolve()
        part = (library / relative).resolve()
        if (not library.is_relative_to(data) or relative.is_absolute() or ".." in relative.parts
                or not part.is_relative_to(library)
                or not part.is_file() or part.suffix != ".FCStd"):
            raise ValueError("Part must be a contained owned regular .FCStd library file")
    elif name == "reload_document":
        path = Path(identity.get("document_path", ""))
        if (path.resolve() != Path(session["document_path"]).resolve() or not path.is_file()
                or not path.resolve().is_relative_to(Path(session["data"]).resolve())):
            raise ValueError("reload_document requires the exact owned saved file")
    if name not in ("create_document", "execute_code", "execute_code_async", "list_documents",
                    "get_parts_list") and not identity["documents"]:
        raise ValueError("Tool requires the owned session document")


def normalize_fem(blocks: list, session: dict) -> list:
    """Refuse measured stock false-success cases while retaining original result evidence."""
    try:
        original = json.loads(blocks[0]["text"])
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        original = {"raw_response": blocks}
    valid = isinstance(original, dict) and original.get("success") is True
    if isinstance(original, dict) and original.get("success") is False:
        return blocks
    if valid:
        count = original.get("node_count")
        valid = isinstance(count, int) and not isinstance(count, bool) and count > 0
        valid = valid and isinstance(original.get("result_object"), str) and bool(original["result_object"].strip())
        for key in ("max_von_mises_MPa", "max_displacement_mm"):
            value = original.get(key)
            valid = valid and isinstance(value, (int, float)) and not isinstance(value, bool)
            valid = valid and math.isfinite(value) and value > 0
        working = original.get("working_dir")
        valid = valid and isinstance(working, str) and bool(working)
        if valid:
            path = Path(working)
            valid = path.is_absolute() and path.is_dir() and path.resolve().is_relative_to(Path(session["output"]).resolve())
        if valid:
            valid = any(all(p.is_file() and p.stat().st_size > 0
                            and p.resolve().is_relative_to(path.resolve())
                            for p in (inp, inp.with_suffix(".frd"), inp.with_suffix(".dat")))
                        for inp in path.glob("*.inp"))
    if valid:
        return blocks
    fields = original if isinstance(original, dict) else {}
    result = {**fields, "success": False,
              "summary": "FEM result failed the owned completion contract.",
              "error": "Missing native success, finite positive results or corresponding owned INP/FRD/DAT artifacts",
              "upstream_result": original}
    return [{"type": "text", "text": json.dumps(result)}]


def configure_specs(original, framework, connection, session, process, cleanup, monitor, verify):
    """Serialize admission, native work, screenshots and complete result readback."""
    from pydantic import BaseModel

    class ResultArgs(BaseModel):
        job_id: str

    def content(value):
        return [{"type": "text", "text": json.dumps(value)}]

    def status(arguments):
        return content(read_receipt(session, arguments["job_id"]))

    def start(arguments):
        result = connection.vrm_start_job(arguments["code"])
        if result.get("success"):
            monitor.job_id = result["job_id"]
        return content(result)

    extension = framework.ToolSpec(
        "get_async_result", "Read the owned native job receipt: pending, complete, failed or timed_out.",
        framework.tool_schema(ResultArgs), ResultArgs, status)
    specs = list(original) + [extension]
    lock = threading.Lock()

    def wrap(spec):
        handler = start if spec.name == "execute_code_async" else spec.handle

        @wraps(handler)
        def handle(arguments):
            deadline = min(arguments.get("timeout", DEADLINE), DEADLINE) if spec.name == "run_fem_analysis" else DEADLINE
            if deadline <= 0:
                raise ValueError("FEM timeout must be positive")
            timer = threading.Timer(deadline, cleanup)
            timer.start()
            try:
                if not lock.acquire(timeout=deadline):
                    raise TimeoutError("Owned caller deadline exceeded while waiting for serialization")
                try:
                    if spec.name == "get_async_result":
                        return handler(arguments)
                    if monitor.pending():
                        raise ValueError("An owned background job is pending; read get_async_result first")
                    before = connection.vrm_identity()
                    verify(before, session, process)
                    validate_arguments(spec.name, arguments, before, session)
                    if spec.name == "run_fem_analysis":
                        arguments = {**arguments, "timeout": deadline}
                    result = handler(arguments)
                    verify(connection.vrm_identity(), session, process)
                    return normalize_fem(result, session) if spec.name == "run_fem_analysis" else result
                finally:
                    lock.release()
            finally:
                timer.cancel()
                timer.join()
        return handle

    for spec in specs:
        spec.handle = wrap(spec)
    return specs
