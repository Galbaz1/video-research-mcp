"""Durable render requests using the monorepo's canonical SQLite job store."""

from __future__ import annotations

import uuid
from pathlib import Path

from .config import get_config
from .job_store import JobStore
from .planning_production import freeze_render_source
from .render_contract import project_contract
from .render_artifacts import file_revision, render_outputs


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
        )
    }


def create_job(project_id: str, resolution: str = "720p", fast: bool = True) -> dict:
    """Freeze source, render settings and existing output before admitting a job."""
    cfg = get_config()
    project_dir = (cfg.resolved_projects_path / project_id).resolve()
    if not project_dir.is_relative_to(cfg.resolved_projects_path):
        raise ValueError("Render project resolves outside configured projects directory")
    source = freeze_render_source(project_dir)
    contract = project_contract(project_dir, resolution)
    cli = Path(cfg.explainer_path).expanduser().resolve() / ".venv/bin/video-explainer"
    request = {
        "project_id": project_id,
        "project_dir": str(project_dir),
        "resolution": resolution,
        "fast": fast,
        "render_timeout": cfg.render_timeout,
        "explainer_path": str(Path(cfg.explainer_path).expanduser().resolve()),
        "source": source,
        "render_contract": contract,
        "before_outputs": render_outputs(project_dir / "output"),
        "execution_token": uuid.uuid4().hex,
        "adapter_revision": adapter_revision(),
        "cli_revision": file_revision(cli) if cli.is_file() else None,
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
