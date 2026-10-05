"""Deterministic local temporal OCR with receipt-only speech and explicit inference."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..models.video_evidence import TemporalOCRRequest, TemporalOCRResult
from ..tracing import trace

video_evidence_server = FastMCP("video-evidence")
_SCHEMA = TypeAdapter(TemporalOCRResult | ToolError).json_schema()
_SCHEMA["type"] = "object"


@video_evidence_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
    ),
)
@trace(name="video_ocr_timeline", span_type="TOOL")
async def video_ocr_timeline(
    request: Annotated[
        TemporalOCRRequest,
        Field(
            description="1..6 source-bound local OCR points, original geometry/PTS, optional verified transcript readback and uncertain numeric decreases",
        ),
    ],
) -> dict:
    """Observe selected text states with original clocks and separate evidence channels.

    Sparse points do not establish transient or continuous state coverage.
    OCR is backend observation, supplied captions are source assertions and
    model-derived words/speakers remain inference. No ASR/provider is dispatched.

    Args:
        request: Explicit source points, local OCR policy and optional receipt readback.

    Returns:
        Bounded source-bound point, speech and heuristic records or a structured error.
    """
    from ..temporal_ocr import build_ocr_timeline

    try:
        return await build_ocr_timeline(request)
    except Exception as exc:
        return make_tool_error(exc)
