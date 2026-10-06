"""Pipeline execution tools — generate, step, render, shorts."""

from __future__ import annotations

import logging
import sqlite3
import stat
from contextlib import closing
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..config import get_config
from ..errors import make_tool_error
from ..models.pipeline import StepResult
from ..planning_production import generation_range, generate_steps, produce, production_transaction
from ..prereqs import require_generation_ready, require_render_ready
from ..runner import run_cli
from ..types import PipelineStep, ProjectId

from .render_jobs import (
    _background_tasks as _background_tasks,
    _run_render as _run_render,
    cancel_background_renders as cancel_background_renders,
    explainer_render as explainer_render,
    explainer_render_cancel as explainer_render_cancel,
    explainer_render_poll as explainer_render_poll,
    explainer_render_start as explainer_render_start,
    recover_render_jobs as recover_render_jobs,
    render_server,
)

logger = logging.getLogger(__name__)
pipeline_server = FastMCP("pipeline")

pipeline_server.mount(render_server)


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


async def _legacy_generate(
    project_id: str, from_step: str | None, to_step: str | None, force: bool
) -> dict:
    """Use standalone storyboard and qualified render after bulk preparation."""
    steps = generation_range(from_step, to_step, managed=False)
    render_requested = "render" in steps
    elapsed, outputs = 0.0, []
    preparation = [step for step in steps if step not in {"storyboard", "render"}]
    if preparation:
        args = ["generate", project_id]
        if from_step:
            args.extend(["--from", from_step])
        args.extend(["--to", preparation[-1]])
        if force:
            args.append("--force")
        args.extend(_tts_args("generate"))
        result = await run_cli(*args)
        elapsed += result.duration_seconds
        outputs.append(result.stdout.strip())
    if "storyboard" in steps:
        args = ["storyboard", project_id]
        if force:
            args.append("--force")
        result = await run_cli(*args)
        elapsed += result.duration_seconds
        outputs.append(result.stdout.strip())
    output = ""
    if render_requested:
        result, output = await _run_render(project_id, "720p", True)
        elapsed += result.duration_seconds
        outputs.append(result.stdout.strip())
    return {
        "project_id": project_id,
        "success": True,
        "duration_seconds": elapsed,
        "stdout": "\n".join(outputs),
        "output_file": output,
        "render_requested": render_requested,
        "playability_verified": render_requested,
        "real_renderer_verified": False,
        "actual_audio_provenance": "unknown",
        "visual_audio_semantics": "not_verified",
    }


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
        cfg = get_config()
        project = (cfg.resolved_projects_path / project_id).resolve()
        project.relative_to(cfg.resolved_projects_path)
        database = project / "planning.sqlite3"
        for suffix in ("", "-journal", "-wal", "-shm"):
            if (project / (database.name + suffix)).is_symlink():
                raise ValueError("Plan database and sidecars must not be symlinks")
        managed = False
        if database.exists():
            metadata = database.stat()
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 8 * 1024 * 1024:
                raise ValueError("Plan database must be a regular project file of at most 8 MiB")
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=0)) as reader:
                if reader.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='plan'").fetchone():
                    managed = reader.execute("SELECT 1 FROM plan WHERE id=1").fetchone() is not None
        steps = generation_range(from_step, to_step, managed=managed)
        require_generation_ready(steps, mock_llm=not managed and cfg.tts_provider == "mock")
        if "render" in steps:
            await require_render_ready(None)
        with production_transaction(project_id) as (project, connection, state):
            if state is not None:
                return await generate_steps(
                    project,
                    connection,
                    state,
                    project_id,
                    from_step,
                    to_step,
                    force,
                    run_cli,
                    _tts_args,
                )
        return await _legacy_generate(project_id, from_step, to_step, force)
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
        require_generation_ready((step,))
        args = [step, project_id]
        args.extend(_tts_args(step))
        with production_transaction(project_id) as (project, connection, state):
            if state is not None:
                if step == "storyboard":
                    args.append("--force")
                result = await produce(project, connection, state, args, run_cli)
                binding = state["bindings"].get(step, {})
                return {
                    **StepResult(
                        project_id=project_id,
                        step=step,
                        success=True,
                        output_file=str(project / binding["path"]) if binding else "",
                        duration_seconds=result.duration_seconds,
                        message=result.stdout.strip(),
                    ).model_dump(),
                    "plan_revision": state["revision"],
                    "factual_success": False,
                }
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
