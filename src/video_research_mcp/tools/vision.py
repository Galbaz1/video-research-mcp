"""Explicit model-vision chat, inferred OCR and strict object grounding."""

from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field, TypeAdapter

from ..models.vision import VisionFailure, VisionRequest, VisionResponse
from ..tracing import trace
from ..vision_analysis import analyze_vision

vision_server = FastMCP("vision-inference")
_SCHEMA = TypeAdapter(VisionResponse | VisionFailure).json_schema()
_SCHEMA["type"] = "object"
_INFERENCE = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                             idempotentHint=False, openWorldHint=True)
_REQUEST = Field(description="Exact original sources, instruction, selected backend, dry plan and explicit workflow submission grant")


@vision_server.tool(output_schema=_SCHEMA, annotations=_INFERENCE)
@trace(name="vision_chat", span_type="TOOL")
async def vision_chat(request: Annotated[VisionRequest, _REQUEST]) -> dict:
    """Analyze, identify or compare exact images and bounded source video samples.

    Dry plans perform local preparation with zero provider calls. A live request
    requires explicit workflow authorization and a configured model/account.
    Interpretation remains model inference, separately from source byte lineage.

    Args:
        request: Sources in comparison order, instruction and bounded backend workflow.

    Returns:
        Planned/complete source commitments, model output and usage or a structured error.
    """
    return await analyze_vision(request, "vision_chat")


@vision_server.tool(output_schema=_SCHEMA, annotations=_INFERENCE)
@trace(name="vision_ocr", span_type="TOOL")
async def vision_ocr(request: Annotated[VisionRequest, _REQUEST]) -> dict:
    """Infer visible text from exact prepared images or precise source frames.

    Model transcription is labeled inference. The separate image_ocr operation
    selects local Tesseract/Vision observations. No automatic fallback occurs.

    Args:
        request: Exact images/frames, transcription instruction and explicit workflow grant.

    Returns:
        Model text/regions, source lineage and usage or a structured error.
    """
    return await analyze_vision(request, "ocr")


@vision_server.tool(output_schema=_SCHEMA, annotations=_INFERENCE)
@trace(name="vision_grounding", span_type="TOOL")
async def vision_grounding(request: Annotated[VisionRequest, _REQUEST]) -> dict:
    """Locate objects with strict inferred boxes and optional actual original-pixel crops.

    Normalized1000 boxes map through the exact transmitted preparation to original
    stored/oriented pixels. Crop byte/geometry verification does not verify that the
    model identified the object correctly. Empty detections remain valid abstentions.

    Args:
        request: Exact images/frames, object instruction and optional crop export.

    Returns:
        Model regions, verified crop artifacts and separate provenance or a structured error.
    """
    return await analyze_vision(request, "grounding")
