"""Deterministic bounded local media tools with native and text MCP results."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
from pathlib import Path
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field, StrictInt, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..image_ops import CropCancellation, crop_png
from ..models.media import CropResult
from ..tracing import trace

media_server = FastMCP("media")
INLINE_IMAGE_BYTES = 1024 * 1024
_OUTPUT_SCHEMA = TypeAdapter(CropResult | ToolError).json_schema()
_OUTPUT_SCHEMA["type"] = "object"


@media_server.tool(
    output_schema=_OUTPUT_SCHEMA,
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    ),
)
@trace(name="image_crop", span_type="TOOL")
async def image_crop(
    file_path: Annotated[str, Field(description="Local 8-bit RGB/RGBA noninterlaced PNG")],
    output_path: Annotated[str, Field(description="Fresh local PNG output path; never overwrites")],
    crop_box: Annotated[
        list[StrictInt],
        Field(
            min_length=4,
            max_length=4,
            description="Integer x, y, width, height in original image pixels",
        ),
    ],
    include_image: Annotated[
        bool,
        Field(
            description="Include a native PNG block up to 1 MiB; false returns identical text metadata"
        ),
    ] = True,
) -> CallToolResult:
    """Crop local PNG pixels without model inference or provider uploads.

    Requires an independently installed FFmpeg and respects LOCAL_FILE_ACCESS_ROOT.
    A source hash binds the crop to bytes; it does not establish factual support
    or whether the input was synthetic. Large outputs retain metadata/path only.

    Args:
        file_path: Original PNG.
        output_path: Fresh output path within the server's local access fence.
        crop_box: Four original-pixel integer coordinates.
        include_image: Whether to emit a bounded native image block.

    Returns:
        Native/text content plus structured CropResult, or a redacted ToolError.
    """
    try:
        cancellation = CropCancellation()
        worker = asyncio.create_task(
            asyncio.to_thread(
                crop_png,
                file_path,
                output_path,
                tuple(crop_box),
                cancellation=cancellation,
            )
        )
        try:
            metadata = await asyncio.shield(worker)
        except asyncio.CancelledError:
            cancellation.cancel()
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            if not worker.cancelled():
                worker.exception()
            raise
        image = None
        status = "text_only"
        if include_image:
            with Path(metadata["artifact"]).open("rb") as stream:
                data = stream.read(INLINE_IMAGE_BYTES + 1)
            status = "inline_byte_limit"
            if len(data) <= INLINE_IMAGE_BYTES:
                if hashlib.sha256(data).hexdigest() != metadata["artifact_sha256"]:
                    raise ValueError("Crop artifact changed before native transport")
                image = ImageContent(
                    type="image", mimeType="image/png", data=base64.b64encode(data).decode()
                )
                status = "included"
        result = CropResult(**metadata, native_image_status=status).model_dump(mode="json")
        content = [TextContent(type="text", text=json.dumps(result))]
        if image is not None:
            content.append(image)
        return CallToolResult(content=content, structured_content=result)
    except Exception as exc:
        error = make_tool_error(exc)
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(error))],
            structured_content=error,
            is_error=True,
        )
