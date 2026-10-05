"""Durable render requests using the monorepo's canonical SQLite job store."""

from __future__ import annotations

import uuid
from pathlib import Path

from .config import get_config
from .job_store import JobStore
from .planning_production import freeze_render_source
from .render_contract import project_contract
from .render_artifacts import file_revision, render_outputs
from .render_authored import authored_binding, authored_project, bind_fixture
from .render_storyboard import production_project
from .render_storyboard_binding import production_binding


def adapter_revision() -> dict:
    """Bind queued execution to the actual worker, runner and shared store bytes."""
    package = Path(__file__).parent
    return {
        name: file_revision((package / name).resolve())["sha256"]
        for name in (
            "jobs.py",
            "render_worker.py",
            "render_artifacts.py",
            "runner.py",
            "job_store.py",
            "render_contract.py",
            "render_validation.py",
            "prereqs.py",
            "media_process.py",
            "render_authored.py",
            "render_storyboard.py",
            "render_storyboard_sources.py",
            "render_storyboard_binding.py",
            "render_storyboard_output.py",
        )
    }


def create_job(project_id: str, resolution: str = "720p", fast: bool = True) -> dict:
    """Freeze source, render settings and existing output before admitting a job."""
    cfg = get_config()
    project_dir = (cfg.resolved_projects_path / project_id).resolve()
    if not project_dir.is_relative_to(cfg.resolved_projects_path):
        raise ValueError("Render project resolves outside configured projects directory")
    source = freeze_render_source(project_dir)
    renderer = None
    if cfg.renderer_entry:
        renderer = (production_binding(cfg) if Path(cfg.renderer_entry).name == "production_entry.mjs"
                    else authored_binding(cfg))
    if renderer and renderer.get("route") == "authored_storyboard":
        contract = production_project(project_dir, resolution, renderer["project_sha256"])
    elif renderer:
        contract = authored_project(project_dir, resolution)
        if not fast:
            raise ValueError("Authored fixture supports only the frozen fast=True request")
        bind_fixture(project_dir, renderer)
    else:
        contract = project_contract(project_dir, resolution)
    cli = Path(cfg.explainer_path).expanduser().resolve() / ".venv/bin/video-explainer"
    request = {
        "project_id": project_id,
        "project_dir": str(project_dir),
        "resolution": resolution,
        "fast": fast,
        "render_timeout": min(cfg.render_timeout, 180) if renderer else cfg.render_timeout,
        "explainer_path": str(Path(cfg.explainer_path).expanduser().resolve()),
        "source": source,
        "render_contract": contract,
        "before_outputs": render_outputs(project_dir / "output"),
        "execution_token": uuid.uuid4().hex,
        "adapter_revision": adapter_revision(),
        "cli_revision": file_revision(cli) if not renderer and cli.is_file() else None,
        "renderer": renderer,
    }
    try:
        return JobStore().create(
            "render",
            request,
            source["sha256"],
            job_id=uuid.uuid4().hex[:12],
            exclusive_key="render:" + str(project_dir),
        )
    except ValueError as exc:
        raise RuntimeError(
            f"Render already in progress or unverified for project: {project_id}"
        ) from exc


def get_job(job_id: str) -> dict | None:
    """Read back a render row without accepting records from another job kind."""
    row = JobStore().get(job_id)
    return row if row and row["kind"] == "render" else None


def reconcile_job(job_id: str) -> dict | None:
    """Preserve stale process state as unknown; never rerun or signal an old PID."""
    row = get_job(job_id)
    if not row or row["status"] not in {"running", "unknown", "cancel_requested"}:
        return row
    owner = "reconcile:" + uuid.uuid4().hex
    claimed = JobStore().claim(job_id, owner)
    if claimed:
        status = "cancel_requested" if row["status"] == "cancel_requested" else "unknown"
        JobStore().checkpoint(
            job_id,
            owner,
            status=status,
            release=True,
            error="Process ownership unavailable after restart; termination and output are unverified",
        )
    return get_job(job_id)
