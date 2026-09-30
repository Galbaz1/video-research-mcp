"""Deterministic image editing, OCR and source-bound export readback."""

import json
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field, TypeAdapter

from ..errors import ToolError, make_tool_error
from ..image_tool_results import image_blocks
from ..models.image_delivery import ImageEditResponse, ImageManifestResponse
from ..models.image_edit import ImageEditRequest
from ..models.image_ocr import ImageOCRRequest, ImageOCRResult
from ..models.media_export import ClipExportRequest, ClipExportResult
from ..native_media_results import native_error, native_operation
from ..tracing import trace

image_server = FastMCP("image-operations")
_LOCAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False,
                         idempotentHint=False, openWorldHint=False)
_READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False,
                        idempotentHint=True, openWorldHint=False)


def _schema(model: type) -> dict:
    """Declare each deterministic success model and the existing error shape."""
    value = TypeAdapter(model | ToolError).json_schema()
    value["type"] = "object"
    return value


def _local_error(exc: Exception) -> dict:
    """Expose an unavailable optional runtime without a generic retry suggestion."""
    value = make_tool_error(exc)
    if isinstance(exc, ImportError):
        value.update(category="DEPENDENCY_MISSING", hint=value["error"], retryable=False)
    return value


@image_server.tool(output_schema=_schema(ImageEditResponse), annotations=_LOCAL)
@trace(name="image_edit", span_type="TOOL")
async def image_edit(
    request: Annotated[ImageEditRequest, Field(description="Bounded preparation, crop, resize, five annotation kinds, polygon/flood cutout and PNG/JPEG/WebP/BMP/GIF conversion")],
    include_image: Annotated[bool, Field(description="Emit actual native image blocks up to 1 MiB each; text retains identical provenance")] = True,
) -> CallToolResult:
    """Edit a source image or decoded video frame and persist its exact manifest.

    Coordinates use the oriented source grid before crop and resize. Requires
    the optional images extra; frame selection also requires local FFmpeg.
    Source-derived edits and annotations retain explicit provenance.

    Args:
        request: Validated local operations and source revision.
        include_image: Return bounded native images alongside metadata.

    Returns:
        Typed source, transforms, artifacts and manifest or a structured error.
    """
    from ..image_edit import edit_image

    try:
        async with native_operation() as generated:
            metadata = await edit_image(request)
            generated.append(metadata)
            blocks, delivery = await image_blocks(metadata, include_image)
            value = ImageEditResponse(metadata=metadata, native_images=delivery).model_dump(mode="json")
            return CallToolResult(content=[TextContent(type="text", text=json.dumps(value)), *blocks],
                                  structured_content=value)
    except Exception as exc:
        return native_error(exc)


@image_server.tool(output_schema=_schema(ImageManifestResponse), annotations=_READ)
@trace(name="image_manifest_read", span_type="TOOL")
async def image_manifest_read(
    manifest_path: Annotated[str, Field(min_length=1, max_length=4096, description="Owned export manifest within the configured local fence")],
    expected_sha256: Annotated[str, Field(pattern="^[0-9a-f]{64}$", description="Required previously recorded full manifest digest")],
    include_image: Annotated[bool, Field(description="Include verified native image artifacts where bounded")] = False,
) -> CallToolResult:
    """Read an exact manifest after restart and verify its source and artifact bytes.

    Args:
        manifest_path: Previously returned owned manifest path.
        expected_sha256: Caller-held manifest digest.
        include_image: Include bounded image blocks after verification.

    Returns:
        Verified manifest and delivery metadata or a structured error.
    """
    from ..image_manifest import read_manifest

    try:
        metadata = await read_manifest(manifest_path, expected_sha256)
        blocks, delivery = await image_blocks(metadata, include_image)
        value = ImageManifestResponse(manifest=metadata, native_images=delivery).model_dump(mode="json")
        return CallToolResult(content=[TextContent(type="text", text=json.dumps(value)), *blocks],
                              structured_content=value)
    except Exception as exc:
        return native_error(exc)


@image_server.tool(output_schema=_schema(ImageOCRResult), annotations=_LOCAL)
@trace(name="image_ocr", span_type="TOOL")
async def image_ocr(
    request: Annotated[ImageOCRRequest, Field(description="Explicit optional local Tesseract or Apple Vision observations; source and prepared coordinate mappings retained")],
) -> dict:
    """Observe text and geometry using an explicitly selected local OCR engine.

    Source OCR and detected geometry do not establish semantic table structure
    or factual support. Missing local runtimes return an explicit limitation.

    Args:
        request: Local engine, source, geometry and lexical locate settings.

    Returns:
        Typed observed OCR geometry and source lineage or a structured error.
    """
    from ..image_ocr import recognize_image

    try:
        async with native_operation() as generated:
            metadata = await recognize_image(request)
            generated.append(metadata)
            return ImageOCRResult.model_validate(metadata).model_dump(mode="json")
    except Exception as exc:
        return _local_error(exc)


@image_server.tool(output_schema=_schema(ClipExportResult), annotations=_LOCAL)
@trace(name="video_clip_export", span_type="TOOL")
async def video_clip_export(
    request: Annotated[ClipExportRequest, Field(description="Finite local source interval and explicit output/crop/audio limits; actual decoded times are measured")],
) -> dict:
    """Export a bounded source clip and verify its encoded output and manifest.

    Requested bounds, selected original PTS and actual encoded timing remain
    separate. This operation preserves the original and invokes no provider.

    Args:
        request: Source revision, half-open window and output limits.

    Returns:
        Typed source-derived clip provenance or a structured error.
    """
    from ..media_clip_export import export_clip

    try:
        async with native_operation() as generated:
            metadata = await export_clip(request)
            generated.append(metadata)
            return ClipExportResult.model_validate(metadata).model_dump(mode="json")
    except Exception as exc:
        return _local_error(exc)
