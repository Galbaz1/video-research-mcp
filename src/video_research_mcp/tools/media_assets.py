"""Focused metadata, acquisition and owned media asset lifecycle tools."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..media_acquisition import acquire_media, source_metadata
from ..media_assets import AssetCatalog
from ..media_sources import inspect_source
from ..tracing import trace

media_assets_server = FastMCP("media_assets")
_READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True
)
_LOCAL_READ = ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False
)
_ACQUIRE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True
)
_REMOVE = ToolAnnotations(
    readOnlyHint=False, destructiveHint=True, idempotentHint=False, openWorldHint=False
)
Source = Annotated[
    str,
    Field(
        min_length=1,
        max_length=8192,
        description="Local video path, YouTube/Loom URL, or HTTPS direct video/HLS URL",
    ),
]
AssetId = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-f]{64}$",
        description="Full SHA-256 asset identity returned by media_acquire; paths are forbidden",
    ),
]


@media_assets_server.tool(annotations=_LOCAL_READ)
@trace(name="media_source_inspect", span_type="TOOL")
async def media_source_inspect(source: Source) -> dict:
    """Inspect source syntax and capabilities without contacting or downloading it.

    Args:
        source: Supported source locator or a candidate to classify.

    Returns:
        Routing capability metadata, with live access explicitly unverified.
    """
    try:
        return inspect_source(source)
    except Exception as exc:
        return make_tool_error(exc)


@media_assets_server.tool(annotations=_READ)
@trace(name="media_metadata", span_type="TOOL")
async def media_metadata(source: Source) -> dict:
    """Retrieve explicit metadata without downloading video, inference or upload.

    Args:
        source: Supported source locator.

    Returns:
        Observed metadata and its method, or an actionable error dictionary.
    """
    try:
        return await source_metadata(source)
    except Exception as exc:
        return make_tool_error(exc)


@media_assets_server.tool(annotations=_ACQUIRE)
@trace(name="media_acquire", span_type="TOOL")
async def media_acquire(source: Source) -> dict:
    """Acquire bounded media into private owned storage with exact byte identity.

    Args:
        source: Supported source; network routes require explicit caller intent.

    Returns:
        Freshly verified asset identity, local analysis path and provenance.
    """
    try:
        return await acquire_media(source)
    except Exception as exc:
        return make_tool_error(exc)


@media_assets_server.tool(annotations=_LOCAL_READ)
@trace(name="media_assets_list", span_type="TOOL")
async def media_assets_list(
    offset: Annotated[
        int, Field(ge=0, strict=True, description="Offset into SHA-256 ordered owned assets")
    ] = 0,
    limit: Annotated[
        int, Field(ge=1, le=100, strict=True, description="Maximum asset records returned")
    ] = 50,
) -> dict:
    """List a bounded page with fresh byte checks and explicit unhealthy states.

    Args:
        offset: Nonnegative identity-ordered page offset.
        limit: At most 100 asset records.

    Returns:
        Assets, denominator and continuation flag; no provider operation occurs.
    """
    try:
        return await asyncio.to_thread(lambda: AssetCatalog().list(offset, limit))
    except Exception as exc:
        return make_tool_error(exc)


@media_assets_server.tool(annotations=_REMOVE)
@trace(name="media_asset_remove", span_type="TOOL")
async def media_asset_remove(asset_id: AssetId) -> dict:
    """Remove one verified owned asset and invalidate its source-dependent caches.

    Args:
        asset_id: Exact full SHA-256 identity; original paths are never accepted.

    Returns:
        Deletion receipt, with original source files retained.
    """
    try:
        return await asyncio.to_thread(lambda: AssetCatalog().remove(asset_id))
    except Exception as exc:
        return make_tool_error(exc)
