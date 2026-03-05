"""YouTube URL validation and content helpers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from google.genai import types

_VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _is_youtube_host(host: str) -> bool:
    """Check if host is a youtube.com domain (including subdomains like www.youtube.com)."""
    host = host.lower().split(":", 1)[0]
    return host == "youtube.com" or host.endswith(".youtube.com")


def _is_youtu_be_host(host: str) -> bool:
    """Check if host is the youtu.be short-link domain."""
    host = host.lower().split(":", 1)[0]
    return host == "youtu.be" or host == "www.youtu.be"


def _extract_video_id_from_parsed(parsed) -> str | None:
    """Extract video ID from a pre-parsed YouTube URL.

    Handles multiple URL formats:
    - youtu.be/<id> (short links)
    - youtube.com/watch?v=<id> (standard)
    - youtube.com/shorts/<id>, /embed/<id>, /live/<id> (path-based)

    Args:
        parsed: A ``urllib.parse.ParseResult`` from ``urlparse()``.

    Returns:
        Video ID string, or None if the URL is not a recognized YouTube format.
    """
    host = parsed.netloc.lower().split(":", 1)[0]
    if _is_youtu_be_host(host):
        return parsed.path.strip("/").split("/", 1)[0] or None

    if not _is_youtube_host(host):
        return None

    video_id = parse_qs(parsed.query).get("v", [None])[0]
    if video_id:
        return video_id

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
        return parts[1]
    return None


def _normalize_youtube_url(url: str) -> str:
    """Normalize to ``https://www.youtube.com/watch?v=VIDEO_ID``."""
    url = url.replace("\\", "")
    parsed = urlparse(url)
    video_id = _extract_video_id_from_parsed(parsed)
    if not video_id:
        raise ValueError(f"Could not extract video ID from URL: {url}")
    video_id = video_id.split("&")[0].split("?")[0]
    return f"https://www.youtube.com/watch?v={video_id}"


def _extract_video_id(url: str) -> str:
    """Extract and validate video ID from a YouTube URL string.

    Strips backslash escapes and trailing query/fragment noise, then
    validates the ID against ``[A-Za-z0-9_-]`` to prevent path traversal
    when the ID is used in filesystem paths.

    Raises:
        ValueError: If no video ID can be extracted or if the ID
            contains invalid characters.
    """
    url = url.replace("\\", "")
    parsed = urlparse(url)
    vid = _extract_video_id_from_parsed(parsed)
    if not vid:
        raise ValueError(f"Not a YouTube URL: {url}")
    vid = vid.split("&")[0].split("?")[0]
    if not _VIDEO_ID_RE.match(vid):
        raise ValueError(f"Invalid YouTube video ID: {vid!r}")
    return vid


def is_youtube_url(url: str) -> bool:
    """Check if URL is a YouTube video URL.

    Recognizes youtube.com (watch, shorts, embed, live) and youtu.be short links.
    """
    parsed = urlparse(url.replace("\\", ""))
    return _is_youtube_host(parsed.netloc) or _is_youtu_be_host(parsed.netloc)


def _video_content(url: str, prompt: str) -> types.Content:
    """Build a Content with video FileData + text prompt."""
    from google.genai import types

    return types.Content(
        parts=[
            types.Part(file_data=types.FileData(file_uri=url)),
            types.Part(text=prompt),
        ]
    )


def _video_content_with_metadata(
    url: str,
    prompt: str,
    *,
    fps: float | None = None,
    start_offset: str | None = None,
    end_offset: str | None = None,
) -> types.Content:
    """Build Content with video FileData, optional VideoMetadata, and text prompt.

    When any of fps/start_offset/end_offset is set, attaches a
    ``types.VideoMetadata`` to the video Part for finer-grained control
    over how Gemini processes the video frames.

    Args:
        url: Video URI (YouTube URL or File API URI).
        prompt: Text prompt for analysis.
        fps: Frames per second to sample. Lower = faster, higher = more detail.
        start_offset: Start time offset (e.g. "10s", "1m30s").
        end_offset: End time offset.

    Returns:
        Content with video part (optionally with VideoMetadata) + text part.
    """
    from google.genai import types

    video_part = types.Part(file_data=types.FileData(file_uri=url))

    if fps is not None or start_offset is not None or end_offset is not None:
        vm = types.VideoMetadata(
            fps=fps,
            start_offset=start_offset,
            end_offset=end_offset,
        )
        video_part.video_metadata = vm

    return types.Content(parts=[video_part, types.Part(text=prompt)])
