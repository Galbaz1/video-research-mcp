"""Pipeline execution tools — generate, step, render, shorts."""

from __future__ import annotations

import logging
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..config import get_config
from ..errors import make_tool_error
from ..models.pipeline import StepResult
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
