"""YouTube Data API tools — metadata and playlist retrieval."""

from __future__ import annotations

import logging
from typing import Annotated
from urllib.parse import parse_qs, urlparse

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..redaction import redact_text
from ..types import PlaylistUrl, YouTubeUrl
from ..youtube import YouTubeClient
from ..tracing import trace
from .video_url import _extract_video_id, _is_youtube_host

logger = logging.getLogger(__name__)
youtube_server = FastMCP("youtube")

_YT_403_HINT = (
    "YouTube Data API returned 403. Common causes:\n"
    "1. API key from Google AI Studio is restricted to generativelanguage.googleapis.com\n"
    "2. YouTube Data API v3 is not enabled in your GCP project\n"
    "Fix: visit https://console.cloud.google.com/apis/library/youtube.googleapis.com "
    "to enable it, or set YOUTUBE_API_KEY to a key with YouTube Data API v3 scope."
)


def _youtube_api_error(exc: Exception) -> dict:
    """Return a structured error for YouTube API failures, with 403-specific hint."""
    try:
        from googleapiclient.errors import HttpError
    except ImportError:
        return make_tool_error(exc)

    if isinstance(exc, HttpError) and exc.resp.status == 403:
        return {
            "error": redact_text(str(exc)),
            "category": "API_PERMISSION_DENIED",
            "hint": _YT_403_HINT,
            "retryable": False,
        }
    return make_tool_error(exc)


def _extract_playlist_id(url: str) -> str:
    """Extract playlist ID from a YouTube playlist or video+playlist URL.

    Supports:
        - https://www.youtube.com/playlist?list=PLxxxxxx
        - https://www.youtube.com/watch?v=xxx&list=PLxxxxxx

    Raises:
        ValueError: If not a YouTube URL or no playlist ID found.
    """
    parsed = urlparse(url)
    host = parsed.netloc.lower().split(":", 1)[0]
    if not _is_youtube_host(host):
        raise ValueError(f"Not a YouTube URL: {url}")
    playlist_id = parse_qs(parsed.query).get("list", [None])[0]
    if not playlist_id:
        raise ValueError(
            f"Could not extract playlist ID from URL: {url}. "
            "Expected a 'list' query parameter."
        )
    return playlist_id


@youtube_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
@trace(name="video_metadata", span_type="TOOL")
async def video_metadata(
    url: YouTubeUrl,
) -> dict:
    """Fetch YouTube video metadata without Gemini analysis.

    Returns title, description, view/like/comment counts, duration,
    tags, channel info, category, and language. Costs 1 YouTube API
    unit, 0 Gemini units.

    Args:
        url: YouTube video URL.

    Returns:
        Dict matching VideoMetadata schema.
    """
    try:
        video_id = _extract_video_id(url)
    except ValueError as exc:
        return make_tool_error(exc)

    try:
        meta = await YouTubeClient.video_metadata(video_id)
        meta_dict = meta.model_dump(mode="json")
        from ..weaviate_store import store_video_metadata
        await store_video_metadata(meta_dict)
        return meta_dict
    except ValueError as exc:
        return make_tool_error(exc)
    except Exception as exc:
        return _youtube_api_error(exc)


@youtube_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
@trace(name="video_comments", span_type="TOOL")
async def video_comments(
    url: YouTubeUrl,
    max_comments: Annotated[int, Field(
        ge=1, le=500, description="Maximum comments to fetch (sorted by relevance)"
    )] = 200,
) -> dict:
    """Fetch top YouTube comments sorted by relevance.

    Returns comment text, like count, and author for each comment.
    Costs 1+ YouTube API units, 0 Gemini units.

    Args:
        url: YouTube video URL.
        max_comments: Maximum number of comments to return.

    Returns:
        Dict with video_id, comments list, and count, or error via make_tool_error().
    """
    try:
        video_id = _extract_video_id(url)
    except ValueError as exc:
        return make_tool_error(exc)

    try:
        comments = await YouTubeClient.video_comments(video_id, max_comments)
        return {
            "video_id": video_id,
            "comments": comments,
            "count": len(comments),
        }
    except Exception as exc:
        return _youtube_api_error(exc)


@youtube_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=True,
    )
)
@trace(name="video_playlist", span_type="TOOL")
async def video_playlist(
    url: PlaylistUrl,
    max_items: Annotated[int, Field(
        ge=1, le=50, description="Maximum videos to return"
    )] = 20,
) -> dict:
    """Get video IDs and titles from a YouTube playlist.

    Results can be passed to video_analyze for batch analysis.
    Costs 1 YouTube API unit per page (max 50 items/page).

    Args:
        url: YouTube playlist URL.
        max_items: Maximum number of playlist items to return.

    Returns:
        Dict matching PlaylistInfo schema.
    """
    try:
        playlist_id = _extract_playlist_id(url)
    except ValueError as exc:
        return make_tool_error(exc)

    try:
        info = await YouTubeClient.playlist_items(playlist_id, max_items)
        return info.model_dump(mode="json")
    except Exception as exc:
        return _youtube_api_error(exc)
