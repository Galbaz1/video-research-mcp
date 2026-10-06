"""Public bounded lifecycle tool over canonical AV-memory revisions and native AV clients.

Independent protocol implementation; QwenLM/Qwen-MM-Plugins reference revision
07736672525443c7f8a3f6405eed37d2236f023f (Apache-2.0). No upstream runtime imports.
"""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..models.video_memory_lifecycle import VideoMemoryLifecycleRequest
from ..tracing import trace
from ..video_memory import lifecycle, replay

video_memory_lifecycle_server = FastMCP("video-memory-lifecycle")


@video_memory_lifecycle_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@trace(name="video_memory_lifecycle", span_type="TOOL")
async def video_memory_lifecycle(request: Annotated[VideoMemoryLifecycleRequest, Field(
    description="One bounded build, append, resume, status, watch or replay invocation; "
                "source/config/revision commitments and explicit AV submission authorization required")]) -> dict:
    """Build/resume/append canonical AV evidence with durable extracted/planned coverage.

    Status checks freshness. Watch/replay return AV observations and stored evidence;
    they require an explicitly authorized existing native route and never infer speaker
    identities or generate an answer. No invocation starts a background job or retries.

    Args:
        request: Typed action with exact sources, semantic configuration and finite limits.

    Returns:
        Durable coverage or bounded observations with attempt receipts, or a tool error.
    """
    try:
        if request.action in {"watch", "replay"}:
            return await replay.run(request)
        return await lifecycle.run(request)
    except Exception as error:
        return make_tool_error(error) | getattr(error, "report", {})
