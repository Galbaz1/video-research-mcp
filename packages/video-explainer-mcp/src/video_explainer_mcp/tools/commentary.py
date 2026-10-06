"""Source-linked movie commentary tools: project, plan check, frozen shards, delivery.

Root mounts ``commentary_server``. No tool spawns agents, synthesizes narration or
renders shards; host execution is limited to an explicitly approved frozen shard.
"""

from __future__ import annotations

from typing import Annotated, Literal

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field

from ..commentary import delivery, project, shards
from ..commentary.plan import validate_plan
from ..errors import make_tool_error
from ..redaction import redact_text
from ..types import ProjectId

commentary_server = FastMCP("commentary")
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
ShardId = Annotated[str, Field(pattern=r"^shard_(?:0[1-9]|[1-9][0-9]{1,2}|1[0-9]{3}|2000)$")]


class ShardApproval(BaseModel):
    """Caller-declared approval for one exact frozen shard; it authenticates no principal."""

    model_config = ConfigDict(extra="forbid")
    approved_by: str = Field(min_length=1, max_length=200)
    shard_sha256: Digest
    source_sha256: Digest
    media_authority: str = Field(min_length=1, max_length=1000,
                                 description="Caller statement of rights/permission for this source media")
    scope: Literal["render_frozen_shard_only"] = "render_frozen_shard_only"


@commentary_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def commentary_prepare(
    project_id: ProjectId,
    source_path: Annotated[str, Field(min_length=1, max_length=4096, description="Local source movie file")],
    expected_source_sha256: Digest,
    target: Annotated[Literal["analysis_only", "plan_only", "full"], Field(description="Stop stage")] = "full",
    language: Annotated[str, Field(min_length=2, max_length=16)] = "en",
    style_brief: Annotated[str, Field(max_length=2000)] = "",
    source_cut_max_sec: Annotated[float | None, Field(gt=0, description="Caller-asserted cut ceiling, e.g. credits start")] = None,
) -> dict:
    """Create a durable project bound to exact source bytes and a pinned ffprobe receipt.

    Args:
        project_id: New project identifier.
        source_path: Local movie path; its SHA256 must equal expected_source_sha256.
        expected_source_sha256: Exact source revision.
        target: analysis_only, plan_only or full.
        language: Narration language tag.
        style_brief: Caller style notes, stored verbatim.
        source_cut_max_sec: Optional latest source time any cut may use.

    Returns:
        Project state with source revision, probe facts and next stage, or a tool error.
    """
    try:
        return await project.prepare(project_id, source_path, expected_source_sha256, target=target,
                                     language=language, style_brief=style_brief,
                                     source_cut_max_sec=source_cut_max_sec)
    except Exception as exc:
        return make_tool_error(exc)


@commentary_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def commentary_inspect(project_id: ProjectId) -> dict:
    """Report durable project state, source freshness and the next stage.

    Args:
        project_id: Existing commentary project.

    Returns:
        State summary or a tool error.
    """
    try:
        return project.inspect(project_id)
    except Exception as exc:
        return make_tool_error(exc)


@commentary_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def commentary_validate_plan(project_id: ProjectId) -> dict:
    """Check segment IDs, narration parity, evidence paths, cut ceilings and audio decisions.

    Args:
        project_id: Project whose plan/editing_plan.json and narration script are checked.

    Returns:
        valid, every error and the digests a freeze would bind, or a tool error.
    """
    try:
        root, manifest = project.load(project_id)
        project.verify_source(manifest)
        return validate_plan(root, manifest)
    except Exception as exc:
        return make_tool_error(exc)


@commentary_server.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, openWorldHint=False))
async def commentary_freeze_shards(
    project_id: ProjectId,
    segments_per_shard: Annotated[int, Field(ge=1, le=20)] = 10,
) -> dict:
    """Validate the plan, then write immutable content-addressed shard manifests.

    Args:
        project_id: Project with a valid plan.
        segments_per_shard: Consecutive segments per shard.

    Returns:
        Set ID, shard digests and index digest, or a tool error.
    """
    try:
        return shards.freeze(project_id, segments_per_shard)
    except Exception as exc:
        return make_tool_error(exc)


@commentary_server.tool(annotations=ToolAnnotations(readOnlyHint=False, idempotentHint=True, openWorldHint=False))
async def commentary_approve_shard(project_id: ProjectId, shard_id: ShardId, approval: ShardApproval) -> dict:
    """Record explicit approval for one frozen shard and return its exact execution scope.

    Args:
        project_id: Project with a current frozen shard set.
        shard_id: Shard to approve.
        approval: Approver, exact shard/source digests and media authority statement.

    Returns:
        Host execution scope and required report contract; nothing is executed.
    """
    try:
        return shards.approve(project_id, shard_id, approval.model_dump())
    except Exception as exc:
        return make_tool_error(exc)


@commentary_server.tool(annotations=ToolAnnotations(readOnlyHint=False, openWorldHint=False))
async def commentary_assemble(
    project_id: ProjectId,
    tolerance_sec: Annotated[float, Field(gt=0, le=2)] = 0.1,
) -> dict:
    """Concatenate valid approved shards, fully decode the cut and check its duration.

    Args:
        project_id: Project whose shards all have successful reports and MP4s.
        tolerance_sec: Allowed difference from the summed shard durations.

    Returns:
        Final QA receipt with commands, executables, lineage and checks, or a tool error.
    """
    try:
        return await delivery.assemble(project_id, tolerance_sec)
    except Exception as exc:
        result = make_tool_error(exc)
        if notes := getattr(exc, "__notes__", []):
            result["cleanup_liability"] = [redact_text(note)[:512] for note in notes[:2]]
        return result


@commentary_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False))
async def commentary_validate_delivery(project_id: ProjectId) -> dict:
    """Refuse delivery when source, plan, shards, reports, MP4s or final QA changed or are missing.

    Args:
        project_id: Project to validate.

    Returns:
        valid with every error, or a tool error.
    """
    try:
        return delivery.validate_delivery(project_id)
    except Exception as exc:
        return make_tool_error(exc)
