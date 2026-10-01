"""Project management tools — create, inject, status, list."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..config import get_config
from ..errors import make_tool_error
from ..evidence import atomic_write, prepare_injection
from ..models.pipeline import InjectResult
from ..planning import plan_transaction
from ..runner import run_cli
from ..scanner import list_projects, scan_project
from ..types import ProjectId

logger = logging.getLogger(__name__)
project_server = FastMCP("project")


@project_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_create(
    project_id: ProjectId,
) -> dict:
    """Create a new explainer video project.

    Args:
        project_id: Unique identifier for the project (alphanumeric, hyphens, underscores).

    Returns:
        Dict with project_id, path, and confirmation message.
    """
    try:
        cfg = get_config()
        if not cfg.explainer_enabled:
            return make_tool_error(FileNotFoundError("EXPLAINER_PATH not configured"))
        result = await run_cli("create", project_id)
        project_path = str(cfg.resolved_projects_path / project_id)
        return {
            "project_id": project_id,
            "path": project_path,
            "message": f"Project '{project_id}' created successfully",
            "stdout": result.stdout.strip(),
        }
    except Exception as exc:
        return make_tool_error(exc)


@project_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def explainer_inject(
    project_id: ProjectId,
    content: Annotated[
        str, Field(description="Content to inject (markdown, text, or research output)")
    ],
    filename: Annotated[
        str, Field(description="Target filename in input/ directory")
    ] = "content.md",
) -> dict:
    """Inject content into a project's input directory.

    Writes content directly to the project's ``input/`` directory without
    calling the CLI. Use this to feed research output into the pipeline.

    Args:
        project_id: Target project identifier.
        content: The content to write.
        filename: Output filename within ``input/``.

    Returns:
        InjectResult with files_written list.
    """
    try:
        cfg = get_config()
        if not cfg.explainer_enabled:
            return make_tool_error(FileNotFoundError("EXPLAINER_PATH not configured"))

        project_dir = cfg.resolved_projects_path / project_id
        if not project_dir.is_dir():
            return make_tool_error(FileNotFoundError(f"Project not found: {project_id}"))

        if Path(filename).name != filename or filename in {"", ".", ".."}:
            raise ValueError("filename must be a single filename within input/")
        project_dir = project_dir.resolve()
        project_dir.relative_to(cfg.resolved_projects_path.resolve())
        input_dir = (project_dir / "input").resolve()
        input_dir.relative_to(project_dir)
        input_dir.mkdir(exist_ok=True)
        target = (input_dir / filename).resolve()
        target.relative_to(input_dir)
        with plan_transaction(project_dir):
            evidence_report = prepare_injection(content, filename, input_dir)
            atomic_write(target, content)

        result = InjectResult(
            project_id=project_id,
            files_written=[str(target)],
            message=f"Injected {len(content)} chars into {filename}",
        ).model_dump()
        if evidence_report is not None:
            result["evidence_validation"] = evidence_report
        return result
    except Exception as exc:
        return make_tool_error(exc)


@project_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def explainer_status(
    project_id: ProjectId,
) -> dict:
    """Check the status of an explainer project.

    Scans the project directory for completed pipeline steps without
    calling the CLI.

    Args:
        project_id: Project to inspect.

    Returns:
        ProjectInfo dict with step completion status.
    """
    try:
        cfg = get_config()
        if not cfg.explainer_enabled:
            return make_tool_error(FileNotFoundError("EXPLAINER_PATH not configured"))
        info = await scan_project(project_id)
        if info is None:
            return make_tool_error(FileNotFoundError(f"Project not found: {project_id}"))
        return info.model_dump()
    except Exception as exc:
        return make_tool_error(exc)


@project_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def explainer_list() -> dict:
    """List all explainer projects with completion status.

    Returns:
        Dict with projects list and total count.
    """
    try:
        cfg = get_config()
        if not cfg.explainer_enabled:
            return make_tool_error(FileNotFoundError("EXPLAINER_PATH not configured"))
        projects = await list_projects()
        return {
            "projects": [p.model_dump() for p in projects],
            "total": len(projects),
        }
    except Exception as exc:
        return make_tool_error(exc)
