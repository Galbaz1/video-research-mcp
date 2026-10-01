"""Prepare measured source scenes and assemble explicitly approved local footage."""

import json
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError
from ..footage_edit import execute
from ..image_tool_results import image_blocks
from ..models.footage_edit import FootageEditRequest, FootageEditResponse
from ..native_media_results import native_error, native_operation
from ..tracing import trace

footage_edit_server = FastMCP("footage-edit")
_SCHEMA = TypeAdapter(FootageEditResponse | ToolError).json_schema()
_SCHEMA["type"] = "object"


@footage_edit_server.tool(
    output_schema=_SCHEMA,
    annotations=ToolAnnotations(
        readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=False
    ),
)
@trace(name="media_edit_footage", span_type="TOOL")
async def media_edit_footage(
    request: Annotated[
        FootageEditRequest,
        Field(description="Prepare exact local source scenes or assemble a digest-bound ledger with complete scene approvals"),
    ],
    include_image: Annotated[
        bool,
        Field(description="Include bounded verified scene/timeline PNGs; text retains the same artifact identities"),
    ] = False,
) -> CallToolResult:
    """Edit bounded local footage through a measured prepare and approval workflow.

    Prepare retains source intervals, actual frame clocks, grade/audio decisions
    and scene previews. Assemble requires the exact prepared manifest and every
    scene artifact approval, then gates full decoding, timeline, black spans and
    required audio loudness before delivery. Declared beat grids and approvals
    remain caller assertions; technical checks do not establish visual semantics.
    FFmpeg and Pillow must already be installed. No provider is invoked.

    Args:
        request: Typed source plan or exact prepared ledger and scene approvals.
        include_image: Include verified PNG previews alongside JSON metadata.

    Returns:
        Prepared or delivered artifact metadata with native image status, or a
        typed refusal. Restart readback uses the returned manifest digest.
    """
    try:
        async with native_operation() as generated:
            metadata = await execute(request)
            generated.append(metadata)
            blocks, delivery = await image_blocks(metadata, include_image)
            result = FootageEditResponse(metadata=metadata, native_images=delivery).model_dump(mode="json")
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, allow_nan=False)), *blocks],
                structured_content=result,
            )
    except Exception as error:
        return native_error(error)
