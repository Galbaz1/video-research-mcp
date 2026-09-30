"""Pipeline execution tools — generate, step, render, shorts."""

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..config import get_config
from ..errors import make_tool_error
from ..redaction import redact_text
from ..jobs import JobStatus, create_job, get_job, update_job
from ..models.pipeline import RenderResult, StepResult
from ..runner import SubprocessResult, run_cli
from ..types import PipelineStep, ProjectId, RenderResolution

logger = logging.getLogger(__name__)
pipeline_server = FastMCP("pipeline")

# Prevent background render tasks from being garbage-collected mid-execution.
# See: https://docs.python.org/3/library/asyncio-task.html#asyncio.create_task
_background_tasks: set[asyncio.Task] = set()
_active_render_projects: set[Path] = set()


def _tts_args(subcommand: str) -> list[str]:
    """Build TTS CLI arguments matching the upstream subcommand's argparse.

    Args:
        subcommand: The CLI subcommand (generate, voiceover, script, etc.).

    Returns:
        List of CLI arguments for TTS configuration.
    """
    cfg = get_config()
    if cfg.tts_provider == "mock":
        if subcommand in ("generate", "voiceover"):
            return ["--mock"]
        return []
    if subcommand == "generate":
        return ["--voice-provider", cfg.tts_provider]
    if subcommand == "voiceover":
        return ["--provider", cfg.tts_provider]
    return []


def _render_outputs(output_dir: Path) -> dict[Path, tuple[int, int]]:
    """Snapshot regular, nonempty video artifacts by modification time and size."""
    outputs = {}
    for path in output_dir.glob("*"):
        if path.suffix.lower() not in {".mp4", ".webm"} or path.is_symlink() or not path.is_file():
            continue
        stamp = path.stat()
        if stamp.st_size > 0:
            outputs[path] = (stamp.st_mtime_ns, stamp.st_size)
    return outputs


async def _run_render(
    project_id: str, resolution: str, fast: bool,
) -> tuple[SubprocessResult, str]:
    """Run the CLI and require a new or updated nonempty video artifact."""
    cfg = get_config()
    project_dir = (cfg.resolved_projects_path / project_id).resolve()
    if project_dir in _active_render_projects:
        raise RuntimeError(f"Render already in progress for project: {project_id}")
    # Admission is atomic until the first await; both render tools share this guard.
    _active_render_projects.add(project_dir)
    try:
        output_dir = project_dir / "output"
        before = _render_outputs(output_dir)
        args = ["render", project_id, "-r", resolution]
        if fast:
            args.append("--fast")
        result = await run_cli(*args, timeout=cfg.render_timeout)
        after = _render_outputs(output_dir)
        changed = [path for path, stamp in after.items() if before.get(path) != stamp]
        if not changed:
            raise FileNotFoundError("Render exited successfully but produced no new nonempty video")
        output_file = max(changed, key=lambda path: after[path][0])
        return result, str(output_file)
    finally:
        _active_render_projects.remove(project_dir)


async def cancel_background_renders() -> None:
    """Cancel and join render tasks during server shutdown."""
    tasks = list(_background_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


@pipeline_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_generate(
    project_id: ProjectId,
    from_step: Annotated[str | None, Field(description="Start from this step")] = None,
    to_step: Annotated[str | None, Field(description="Stop after this step")] = None,
    force: Annotated[bool, Field(description="Re-run already completed steps")] = False,
) -> dict:
    """Run the full explainer pipeline (or a subset of steps).

    Args:
        project_id: Target project.
        from_step: Start from this pipeline step (skip earlier steps).
        to_step: Stop after this step (skip later steps).
        force: Re-run steps even if already completed.

    Returns:
        Dict with project_id, success status, duration, and CLI output.
    """
    try:
        args = ["generate", project_id]
        if from_step:
            args.extend(["--from", from_step])
        if to_step:
            args.extend(["--to", to_step])
        if force:
            args.append("--force")
        args.extend(_tts_args("generate"))

        result = await run_cli(*args)
        return {
            "project_id": project_id,
            "success": True,
            "duration_seconds": result.duration_seconds,
            "stdout": result.stdout.strip(),
        }
    except Exception as exc:
        return make_tool_error(exc)


@pipeline_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_step(
    project_id: ProjectId,
    step: Annotated[PipelineStep, Field(description="Pipeline step to run")],
) -> dict:
    """Run a single pipeline step.

    Args:
        project_id: Target project.
        step: One of: script, narration, scenes, voiceover, storyboard.

    Returns:
        StepResult with success status and output file.
    """
    try:
        args = [step, project_id]
        args.extend(_tts_args(step))

        result = await run_cli(*args)
        return StepResult(
            project_id=project_id,
            step=step,
            success=True,
            duration_seconds=result.duration_seconds,
            message=result.stdout.strip(),
        ).model_dump()
    except Exception as exc:
        return make_tool_error(exc)


@pipeline_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_render(
    project_id: ProjectId,
    resolution: Annotated[RenderResolution, Field(description="Output resolution")] = "720p",
    fast: Annotated[bool, Field(description="Use fast/preview quality")] = True,
) -> dict:
    """Render the explainer video (blocking — waits for completion).

    For long renders, prefer ``explainer_render_start`` + ``explainer_render_poll``.

    Args:
        project_id: Project with completed pipeline steps.
        resolution: Video resolution preset.
        fast: Use fast/preview quality for quicker renders.

    Returns:
        RenderResult with output file path and duration.
    """
    try:
        result, output_file = await _run_render(project_id, resolution, fast)

        return RenderResult(
            project_id=project_id,
            success=True,
            output_file=output_file,
            duration_seconds=result.duration_seconds,
            resolution=resolution,
            message="Render complete",
        ).model_dump()
    except Exception as exc:
        return make_tool_error(exc)


@pipeline_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_render_start(
    project_id: ProjectId,
    resolution: Annotated[RenderResolution, Field(description="Output resolution")] = "720p",
    fast: Annotated[bool, Field(description="Use fast/preview quality")] = True,
) -> dict:
    """Start a background render and return immediately with a job ID.

    Poll progress with ``explainer_render_poll``.

    Args:
        project_id: Project to render.
        resolution: Video resolution preset.
        fast: Use fast/preview quality.

    Returns:
        Dict with job_id for polling.
    """
    try:
        job = create_job(project_id)
        update_job(job.job_id, status=JobStatus.RUNNING)

        async def _render_background():
            start = time.monotonic()
            try:
                _, output_file = await _run_render(project_id, resolution, fast)

                update_job(
                    job.job_id,
                    status=JobStatus.COMPLETED,
                    output_file=output_file,
                    duration_seconds=round(time.monotonic() - start, 2),
                )
            except Exception as exc:
                update_job(
                    job.job_id,
                    status=JobStatus.FAILED,
                    error=redact_text(str(exc)),
                    duration_seconds=round(time.monotonic() - start, 2),
                )

        def _render_done(task: asyncio.Task) -> None:
            """Record cancellation even when the task never reached its first await."""
            _background_tasks.discard(task)
            if task.cancelled():
                update_job(job.job_id, status=JobStatus.FAILED, error="Render cancelled on shutdown")

        task = asyncio.create_task(_render_background())
        _background_tasks.add(task)
        task.add_done_callback(_render_done)
        return {
            "job_id": job.job_id,
            "project_id": project_id,
            "status": "running",
            "message": "Render started in background — poll with explainer_render_poll",
        }
    except Exception as exc:
        return make_tool_error(exc)


@pipeline_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def explainer_render_poll(
    job_id: Annotated[str, Field(description="Job ID from explainer_render_start")],
) -> dict:
    """Check the status of a background render job.

    Args:
        job_id: The 12-char hex job identifier.

    Returns:
        Dict with current job status, output file (if complete), or error.
    """
    try:
        job = get_job(job_id)
        if job is None:
            return make_tool_error(
                KeyError(f"Job not found: {job_id}")
            )
        return {
            "job_id": job.job_id,
            "project_id": job.project_id,
            "status": job.status.value,
            "output_file": job.output_file,
            "error": job.error,
            "duration_seconds": job.duration_seconds,
            "started_at": job.started_at.isoformat(),
            "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        }
    except Exception as exc:
        return make_tool_error(exc)


@pipeline_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=True))
async def explainer_short(
    project_id: ProjectId,
) -> dict:
    """Generate a short-form video from an existing project.

    Args:
        project_id: Project with completed pipeline.

    Returns:
        Dict with success status and output info.
    """
    try:
        args = ["short", "generate", project_id]
        args.extend(_tts_args("short"))
        result = await run_cli(*args)
        return {
            "project_id": project_id,
            "success": True,
            "duration_seconds": result.duration_seconds,
            "stdout": result.stdout.strip(),
        }
    except Exception as exc:
        return make_tool_error(exc)
