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
from .runner import SubprocessResult, run_cli, run_entry
from .prereqs import require_render_ready
from .render_contract import project_contract, source_contract
from .render_validation import qualify_render
from .render_authored import authored_binding, authored_project, qualify_authored
from .render_storyboard import production_project
from .render_storyboard_binding import production_binding
from .render_storyboard_output import qualify_production
from .errors import SubprocessError

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
    if request.get("renderer"):
        if not cfg.renderer_entry:
            raise ValueError("Authored renderer changed after admission")
        current = (production_binding(cfg) if Path(cfg.renderer_entry).name == "production_entry.mjs"
                   else authored_binding(cfg))
        if current != request["renderer"]:
            raise ValueError("Authored renderer changed after admission")
        return
    if cfg.renderer_entry:
        raise ValueError("Render route changed after admission")
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


def _failure_result(row: dict, exc: Exception, start: float) -> dict:
    """Retain bounded authored process logs alongside any completed dispatch checkpoint."""
    result = {**((get_job(row["job_id"]) or {}).get("result") or {}),
              "duration_seconds": round(time.monotonic() - start, 2)}
    if isinstance(exc, SubprocessError) and row["request"].get("renderer"):
        result["subprocess"] = {"command": exc.command, "returncode": exc.returncode,
                                "stdout": exc.stdout, "stderr": exc.stderr}
    return result


async def _execute_render(row: dict, owner: str) -> tuple[SubprocessResult, str]:
    """Execute exactly one admitted request, retaining all terminal outcomes."""
    job_id = row["job_id"]
    task = asyncio.current_task()
    _job_tasks[job_id] = (owner, task)
    heartbeat = asyncio.create_task(_heartbeat(job_id, owner, task))
    start = time.monotonic()
    try:
        deadline = row["request"]["render_timeout"] if row["request"].get("renderer") else None
        async with asyncio.timeout(deadline):
            result, artifact, dispatch = await _run_request(row, owner)
        hashes = {artifact["path"]: artifact["sha256"]}
        receipt = (artifact["qualification"].get("authored_storyboard", {})
                   or artifact["qualification"].get("authored_fixture", {})).get("receipt")
        if receipt:
            hashes[receipt["path"]] = receipt["sha256"]
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
            artifact_hashes=hashes,
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
            error=redact_text(str(exc) or "Authored render deadline exceeded; owned cleanup joined"),
            release=True,
            result=_failure_result(row, exc, start),
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
    renderer = request.get("renderer")
    if renderer and renderer.get("route") == "authored_storyboard":
        contract = production_project(project_dir, request["resolution"], renderer["project_sha256"])
    elif renderer:
        contract = authored_project(project_dir, request["resolution"])
    else:
        contract = project_contract(project_dir, request["resolution"])
    if contract != request["render_contract"]:
        raise ValueError("Render input/output route changed after admission")
    if renderer and renderer.get("route") == "authored_storyboard":
        await require_render_ready(request["project_id"], resolution=request["resolution"])
    else:
        await require_render_ready(request["project_id"])
    return project_dir, source


async def _dispatch_render(row: dict, owner: str, dispatch: dict) -> SubprocessResult:
    """Bind the owned process identity and dispatch exactly the admitted route."""
    request = row["request"]
    def process_started(pid: int) -> None:
        operation = f"process:{pid}:{request['execution_token']}"
        if not JobStore().checkpoint(row["job_id"], owner, external_id=operation):
            raise RuntimeError("Render lost ownership before process binding")
    def dispatch_updated(receipt: dict) -> None:
        dispatch["cleanup"] = receipt
        if not JobStore().checkpoint(row["job_id"], owner, result={"dispatch": dispatch}):
            raise RuntimeError("Authored render cleanup checkpoint rejected")
    renderer = request.get("renderer")
    if renderer:
        output = str(Path(request["render_contract"]["expected_output"]).relative_to(request["project_dir"]))
        if renderer.get("route") == "authored_storyboard":
            command = [renderer["node"]["path"], renderer["entry"],
                       "--project", request["project_dir"], "--resolution", request["resolution"],
                       "--spec", renderer["spec"], "--spec-sha256", renderer["spec_sha256"],
                       "--output-relative", output]
            if request["fast"]:
                command.append("--fast")
            command.extend(["--execution-token", request["execution_token"]])
        else:
            command = [renderer["node"]["path"], renderer["entry"], request["project_dir"],
                       request["resolution"], renderer["spec"], renderer["spec_sha256"], output,
                       request["execution_token"]]
        return await run_entry(command, cwd=str(Path(renderer["entry"]).parent),
                               timeout=request["render_timeout"], process_started=process_started,
                               dispatch_updated=dispatch_updated)
    args = ["render", request["project_id"], "-r", request["resolution"]]
    if request["fast"]:
        args.append("--fast")
    return await run_cli(*args, timeout=request["render_timeout"], process_started=process_started)


async def _qualify_output(artifact: dict, request: dict) -> dict:
    """Apply the selected output bound before decoding, then join its exact proof."""
    renderer = request.get("renderer")
    output_limit = 512 if renderer and renderer.get("route") == "authored_storyboard" else 16
    if renderer and artifact["size_bytes"] > output_limit * 1024 * 1024:
        raise ValueError(f"Authored output exceeds {output_limit} MiB")
    qualification = await qualify_render(artifact, request["resolution"])
    if (request.get("renderer") or {}).get("route") == "authored_storyboard":
        qualification["renderer_identity"] = "authored project scene registry"
        qualification["authored_storyboard"] = await qualify_production(artifact, qualification, request)
    elif request.get("renderer"):
        qualification["renderer_identity"] = "authored fixed-fixture entry"
        qualification["authored_fixture"] = await qualify_authored(artifact, qualification, request)
        qualification["authored_fixture"].update(quality="fixed", fast_applied=False)
    return qualification


async def _run_request(row: dict, owner: str) -> tuple[SubprocessResult, dict, dict]:
    """Bind actual dispatch inputs and output baseline to the frozen admission."""
    request = row["request"]
    project_dir, source = await _validate_request(row)

    before = await asyncio.to_thread(render_outputs, project_dir / "output")
    dispatch = {"source_revision": source["sha256"], "before_outputs": before}
    if not JobStore().checkpoint(row["job_id"], owner, result={"dispatch": dispatch}):
        raise RuntimeError("Render lost ownership before dispatch")
    if before != request["before_outputs"]:
        raise ValueError("Render outputs changed while queued")
    if await asyncio.to_thread(project_revision, project_dir) != source:
        raise ValueError("Project inputs changed during render readiness")
    _check_dispatch_binding(request)
    result = await _dispatch_render(row, owner, dispatch)
    if request.get("renderer"):
        dispatch.update(stdout=result.stdout, stderr=result.stderr, command=result.command)
        if not JobStore().checkpoint(row["job_id"], owner, result={"dispatch": dispatch}):
            raise RuntimeError("Authored render lost ownership before dispatch log readback")
    _check_dispatch_binding(request)
    renderer = None if request.get("renderer") else source_contract(Path(request["explainer_path"]))
    if renderer and not renderer["mapped_source_verified"]:
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
    artifact["qualification"] = await _qualify_output(artifact, request)
    if await asyncio.to_thread(project_revision, project_dir) != source:
        raise ValueError("Project inputs changed during output qualification")
    _check_dispatch_binding(request)
    return result, artifact, dispatch


async def _admit_render(project_id: str, resolution: str, fast: bool) -> tuple[dict, str]:
    """Atomically admit and acquire one project render before any subprocess starts."""
    if Path(get_config().renderer_entry).name == "production_entry.mjs":
        await require_render_ready(project_id, resolution=resolution)
    else:
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
    if Path(get_config().renderer_entry).name == "production_entry.mjs":
        await require_render_ready(project_id, resolution=resolution)
    else:
        await require_render_ready(project_id)
    row = await asyncio.to_thread(create_job, project_id, resolution, fast)
    if len(_job_tasks) < MAX_CONCURRENT_RENDERS:
        owner = "render:" + uuid.uuid4().hex
        row = JobStore().claim(row["job_id"], owner)
        if not row:
            raise RuntimeError("Render lease unavailable")
        _launch_background(row, owner)
    return row
