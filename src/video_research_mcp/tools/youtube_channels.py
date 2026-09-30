"""Channel inspection and uploads catalog tools on the existing YouTube server."""

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ..tracing import trace
from ..youtube_channels import channel_catalog, channel_metadata
from .youtube import _youtube_api_error, youtube_server


@youtube_server.tool(annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True,
))
@trace(name='youtube_channel_inspect', span_type='TOOL')
async def youtube_channel_inspect(
    reference: Annotated[str, Field(description='YouTube UC channel ID, @handle or canonical channel URL')],
) -> dict:
    """Inspect channel metadata through YouTube Data API without downloading media.

    Args:
        reference: Explicit channel identity.

    Returns:
        Channel metadata with provider provenance, or an actionable tool error.
    """
    try:
        return await channel_metadata(reference)
    except Exception as exc:
        return _youtube_api_error(exc)


@youtube_server.tool(annotations=ToolAnnotations(
    readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=True,
))
@trace(name='youtube_channel_catalog', span_type='TOOL')
async def youtube_channel_catalog(
    reference: Annotated[str, Field(description='YouTube UC channel ID, @handle or canonical channel URL')],
    max_items: Annotated[int, Field(ge=1, le=50, description='Maximum upload entries in this API page')] = 20,
    page_token: Annotated[str | None, Field(max_length=1024, description='Optional next_page_token from a prior response')] = None,
) -> dict:
    """List one channel uploads page and retain any continuation token.

    A channel video count and playlist reported total are provider metadata. The
    returned items establish this page's coverage; no video bytes are fetched.

    Args:
        reference: Explicit channel identity.
        max_items: Page size from one to fifty entries.
        page_token: Continuation token for another page.

    Returns:
        Upload entries and explicit page coverage, or an actionable tool error.
    """
    try:
        if not 1 <= max_items <= 50:
            raise ValueError('max_items must be between 1 and 50')
        return await channel_catalog(reference, max_items, page_token)
    except Exception as exc:
        return _youtube_api_error(exc)
