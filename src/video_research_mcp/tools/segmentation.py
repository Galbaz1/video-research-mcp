"""Optional external segmentation with validated original-grid native artifacts."""

import json
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError
from ..image_tool_results import image_blocks
from ..models.segmentation import SegmentationRequest, SegmentationResponse
from ..native_media_results import native_error, native_operation
from ..tracing import trace

segmentation_server = FastMCP("segmentation")
_SCHEMA = TypeAdapter(SegmentationResponse | ToolError).json_schema()
_SCHEMA["type"] = "object"


@segmentation_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                                idempotentHint=False, openWorldHint=True),
)
@trace(name="image_segment", span_type="TOOL")
async def image_segment(
    request: Annotated[SegmentationRequest, Field(description="Exact original still-image digest, prompt and operator-configured service; submission requires an explicit workflow grant")],
    include_image: Annotated[bool, Field(description="Emit bounded verified native PNGs; text retains the same artifact identities")] = True,
) -> CallToolResult:
    """Plan or submit one image and preserve actual mask and overlay artifacts.

    Scores and masks are unverified proposals. Service selection and checkpoint
    declarations do not attest a loaded model or establish redistribution rights.

    Args:
        request: Exact source, selected service and explicit submission settings.
        include_image: Include bounded native image blocks after readback.

    Returns:
        Typed metadata and image delivery or an explicit structured error.
    """
    try:
        from ..segmentation import segment_image

        async with native_operation() as generated:
            metadata = await segment_image(request)
            if "error" in metadata:
                return CallToolResult(content=[TextContent(type="text", text=json.dumps(metadata))],
                                      structured_content=metadata, is_error=True)
            generated.append(metadata)
            blocks, delivery = await image_blocks(metadata, include_image)
            value = SegmentationResponse(metadata=metadata, native_images=delivery).model_dump(mode="json")
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(value)), *blocks],
                                  structured_content=value)
    except Exception as exc:
        return native_error(exc)
