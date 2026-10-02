"""Owned render workers, durable admission, reconciliation and cancellation."""

from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path

from .config import get_config
from .job_store import JobStore
from .jobs import adapter_revision, create_job, get_job, reconcile_job
from .redaction import redact_text
from .render_artifacts import file_revision, project_revision, render_outputs, verify_output
from .runner import SubprocessResult, run_cli
from .prereqs import require_render_ready
from .render_contract import project_contract, source_contract
from .render_validation import qualify_render

_background_tasks: set[asyncio.Task] = set()
_job_tasks: dict[str, tuple[str, asyncio.Task]] = {}
HEARTBEAT_SECONDS = 1
MAX_CONCURRENT_RENDERS = 2
_draining_enabled = True


def _check_dispatch_binding(request: dict) -> None:
    """Reject changed dispatch settings or console bytes without an await gap."""
    cfg = get_config()
    if (cfg.resolved_projects_path / request["project_id"]).resolve() != Path(request["project_dir"]):
        raise ValueError("Render project settings changed after admission")
    if str(Path(cfg.explainer_path).expanduser().resolve()) != request["explainer_path"]:
        raise ValueError("Render CLI settings changed after admission")
    cli = Path(request["explainer_path"]) / ".venv/bin/video-explainer"
    if request["cli_revision"] and file_revision(cli, 8 * 1024 * 1024) != request["cli_revision"]:
        raise ValueError("Render CLI changed after admission")


async def _heartbeat(job_id: str, owner: str, task: asyncio.Task) -> None:
    """Refresh the lease independently of CLI duration and observe external cancel."""
    while True:
        await asyncio.sleep(HEARTBEAT_SECONDS)
        row = get_job(job_id)
        if not row or row["status"] == "cancel_requested":
            task.cancel()
            return
        if not JobStore().heartbeat(job_id, owner):
            task.cancel()
            return


def _cancel_ack(job_id: str, owner: str) -> None:
    """Acknowledge cancellation only for an owned task whose cleanup has joined."""
    row = get_job(job_id)
    if not row or row["owner"] != owner:
        return
    JobStore().cancel(job_id)
    JobStore().checkpoint(
        job_id,
        owner,
        status="cancelled",
        error="Render cancelled; owned task joined",
        release=True,
    )


async def _execute_render(row: dict, owner: str) -> tuple[SubprocessResult, str]:
    """Execute exactly one admitted request, retaining all terminal outcomes."""
    job_id = row["job_id"]
    task = asyncio.current_task()
    _job_tasks[job_id] = (owner, task)
    heartbeat = asyncio.create_task(_heartbeat(job_id, owner, task))
    start = time.monotonic()
    try:
        result, artifact, dispatch = await _run_request(row, owner)
        stored = JobStore().checkpoint(
            job_id,
            owner,
            status="completed",
            release=True,
            result={
                "output": artifact,
                "duration_seconds": result.duration_seconds,
                "dispatch": dispatch,
            },
            artifact_hashes={artifact["path"]: artifact["sha256"]},
        )
        if not stored:
            _cancel_ack(job_id, owner)
            raise RuntimeError("Render completion rejected after ownership or cancellation change")
        accepted = await asyncio.to_thread(get_job, job_id)
        if not accepted["attestation"]["verified"]:
            raise ValueError("Completed render failed persisted request/result/artifact readback")
        return result, artifact["path"]
    except asyncio.CancelledError:
        _cancel_ack(job_id, owner)
        raise
    except Exception as exc:
        JobStore().checkpoint(
            job_id,
            owner,
            status="failed",
            error=redact_text(str(exc)),
            release=True,
            result={
                **((get_job(job_id) or {}).get("result") or {}),
                "duration_seconds": round(time.monotonic() - start, 2),
            },
        )
        raise
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)
        _job_tasks.pop(job_id, None)


async def _validate_request(row: dict) -> tuple[Path, dict]:
    """Check retained source, settings and executable bindings before dispatch."""
    request = row["request"]
    if row["attestation"]["request_integrity"] != "verified":
        raise ValueError("Render request failed integrity readback")
    if row["source_revision"] != request["source"]["sha256"]:
        raise ValueError("Render source revision differs from frozen request")
    if await asyncio.to_thread(adapter_revision) != request["adapter_revision"]:
        raise ValueError("Render implementation changed after admission")
    project_dir = Path(request["project_dir"])
    source = await asyncio.to_thread(project_revision, project_dir)
    if source != request["source"]:
        raise ValueError("Project inputs changed after render admission")
    _check_dispatch_binding(request)
    if project_contract(project_dir, request["resolution"]) != request["render_contract"]:
        raise ValueError("Render input/output route changed after admission")
    await require_render_ready(request["project_id"])
    return project_dir, source


async def _run_request(row: dict, owner: str) -> tuple[SubprocessResult, dict, dict]:
    """Bind actual dispatch inputs and output baseline to the frozen admission."""
    request = row["request"]
    project_dir, source = await _validate_request(row)
    args = ["render", request["project_id"], "-r", request["resolution"]]
    if request["fast"]:
        args.append("--fast")

    def process_started(pid: int) -> None:
        operation = f"process:{pid}:{request['execution_token']}"
        if not JobStore().checkpoint(row["job_id"], owner, external_id=operation):
            raise RuntimeError("Render lost ownership before process binding")

    before = await asyncio.to_thread(render_outputs, project_dir / "output")
    dispatch = {"source_revision": source["sha256"], "before_outputs": before}
    if not JobStore().checkpoint(row["job_id"], owner, result={"dispatch": dispatch}):
        raise RuntimeError("Render lost ownership before dispatch")
    if before != request["before_outputs"]:
        raise ValueError("Render outputs changed while queued")
    if await asyncio.to_thread(project_revision, project_dir) != source:
        raise ValueError("Project inputs changed during render readiness")
    _check_dispatch_binding(request)
    result = await run_cli(
        *args,
        timeout=request["render_timeout"],
        process_started=process_started,
    )
    _check_dispatch_binding(request)
    renderer = source_contract(Path(request["explainer_path"]))
    if not renderer["mapped_source_verified"]:
        raise ValueError(
            "Renderer source changed during execution: " + "; ".join(renderer["errors"])
        )
    after = await asyncio.to_thread(render_outputs, project_dir / "output")
    changed = [path for path, revision in after.items() if before.get(path) != revision]
    if not changed:
        raise FileNotFoundError("Render exited successfully but produced no new nonempty video")
    if await asyncio.to_thread(project_revision, project_dir) != source:
        raise ValueError("Project inputs changed during render")
    output = request["render_contract"]["expected_output"]
    if output not in changed:
        raise FileNotFoundError("Render did not produce the expected current-request MP4")
    artifact = {"path": output, **after[output]}
    if not await asyncio.to_thread(verify_output, artifact):
        raise ValueError("Rendered output changed before acceptance")
    artifact["qualification"] = await qualify_render(artifact, request["resolution"])
    if await asyncio.to_thread(project_revision, project_dir) != source:
        raise ValueError("Project inputs changed during output qualification")
    _check_dispatch_binding(request)
    return result, artifact, dispatch


async def _admit_render(project_id: str, resolution: str, fast: bool) -> tuple[dict, str]:
    """Atomically admit and acquire one project render before any subprocess starts."""
    await require_render_ready(project_id)
    row = await asyncio.to_thread(create_job, project_id, resolution, fast)
    if len(_job_tasks) >= MAX_CONCURRENT_RENDERS:
        JobStore().cancel(row["job_id"])
        raise RuntimeError("Local render worker capacity is full")
    owner = "render:" + uuid.uuid4().hex
    claimed = JobStore().claim(row["job_id"], owner)
    if not claimed:
        raise RuntimeError("Render lease unavailable")
    return claimed, owner


async def _run_render(project_id: str, resolution: str, fast: bool) -> tuple[SubprocessResult, str]:
    """Share durable project admission between blocking and background renders."""
    row, owner = await _admit_render(project_id, resolution, fast)
    try:
        return await _execute_render(row, owner)
    finally:
        _drain_queued()


async def cancel_background_renders() -> None:
    """Request, cancel and join only background tasks owned by this server process."""
    global _draining_enabled
    _draining_enabled = False
    tasks = list(_background_tasks)
    for job_id, (_, task) in list(_job_tasks.items()):
        if task in tasks:
            JobStore().cancel(job_id)
    for task in tasks:
        if not task.cancelling():
            task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


def _launch_background(row: dict, owner: str) -> None:
    """Retain an owned task, recording cancellation even before its first await."""

    async def run():
        current, holder = row, owner
        while current:
            try:
                await _execute_render(current, holder)
            except Exception:
                pass  # The owner persisted failure before returning.
            current, holder = _next_queued()

    def done(task: asyncio.Task) -> None:
        _background_tasks.discard(task)
        for job_id, (_, owned_task) in list(_job_tasks.items()):
            if owned_task is task:
                _job_tasks.pop(job_id, None)
        if task.cancelled():
            _cancel_ack(row["job_id"], owner)

    task = asyncio.create_task(run())
    _job_tasks[row["job_id"]] = (owner, task)
    _background_tasks.add(task)
    task.add_done_callback(done)


async def recover_render_jobs() -> None:
    """Claim never-launched queued requests once and reconcile stale process leases."""
    global _draining_enabled
    _draining_enabled = True
    for row in JobStore().list_active("render"):
        if row["status"] != "queued":
            await asyncio.to_thread(reconcile_job, row["job_id"])
    _drain_queued()


def _drain_queued() -> None:
    """Launch at most the available process-local worker slots."""
    while _draining_enabled and len(_job_tasks) < MAX_CONCURRENT_RENDERS:
        row, owner = _next_queued()
        if row is None:
            break
        _launch_background(row, owner)


def _next_queued() -> tuple[dict | None, str]:
    """Acquire one never-started request; stale subprocesses never enter this queue."""
    if _draining_enabled:
        for row in JobStore().list_active("render"):
            if row["status"] == "queued" and row["attempts"] == 0:
                owner = "render:" + uuid.uuid4().hex
                claimed = JobStore().claim(row["job_id"], owner)
                if claimed:
                    return claimed, owner
    return None, ""


async def start_render(project_id: str, resolution: str, fast: bool) -> dict:
    """Persist a request and launch it only when this process has worker capacity."""
    await require_render_ready(project_id)
    row = await asyncio.to_thread(create_job, project_id, resolution, fast)
    if len(_job_tasks) < MAX_CONCURRENT_RENDERS:
        owner = "render:" + uuid.uuid4().hex
        row = JobStore().claim(row["job_id"], owner)
        if not row:
            raise RuntimeError("Render lease unavailable")
        _launch_background(row, owner)
    return row
