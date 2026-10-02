"""Pure routing and explicit metadata resolver controls; no live platform access."""

import json
from unittest.mock import patch

import pytest

from video_research_mcp.media_sources import inspect_source, resolve_loom_metadata
from video_research_mcp.url_policy import UrlPolicyError


@pytest.mark.parametrize(
    "source,kind",
    [
        ("/original/owned.mp4", "local"),
        ("missing.webm", "local"),
        ("https://youtu.be/Abcdefgh_12", "youtube"),
        ("https://www.youtube.com/watch?v=Abcdefgh_12&token=private", "youtube"),
        ("https://www.youtube.com/shorts/Abcdefgh_12", "youtube"),
        ("https://www.loom.com/share/0123456789abcdef0123456789abcdef", "loom"),
        ("https://cdn.example.invalid/owned.mp4?signature=private", "direct"),
        ("https://cdn.example.invalid/owned.m3u8", "hls"),
        ("https://vimeo.com/123", "unsupported"),
        ("original.txt", "unsupported"),
    ],
)
def test_source_classification_is_pure_and_redacted(source, kind):
    """GIVEN candidate sources WHEN inspected THEN no bytes, DNS, or provider are touched."""
    with (
        patch("socket.getaddrinfo", side_effect=AssertionError("no DNS")),
        patch("pathlib.Path.open", side_effect=AssertionError("no local read")),
    ):
        result = inspect_source(source)
    assert result["source_kind"] == kind
    assert result["access_state"] == "unverified"
    assert result["inspection_performed"] == "syntax_only"
    assert "private" not in result["source"]


def test_prerequisites_distinguish_metadata_from_acquisition():
    youtube = inspect_source("https://youtu.be/Abcdefgh_12")
    assert youtube["metadata_prerequisites"] == ["YouTube Data API access"]
    assert youtube["acquisition_prerequisites"] == ["yt-dlp"]
    hls = inspect_source("https://cdn.example.invalid/owned.m3u8")
    assert hls["acquisition_prerequisites"] == ["ffmpeg", "ffprobe"]
    assert inspect_source("original.mp4")["acquisition_prerequisites"] == []


@pytest.mark.parametrize(
    "source",
    [
        "http://cdn.example.invalid/video.mp4",
        "file:///owned.mp4",
        "//cdn.example.invalid/video.mp4",
        "https://user:password@example.invalid/video.mp4",
        "https://127.0.0.1/video.mp4",
        "https://[::1]/video.mp4",
        "https://example.invalid:444/video.mp4",
        "https://example.invalid/video.mp4\n",
        "https://youtube.com/watch?v=bad",
        "https://loom.com/share/bad",
        "",
        "a" * 8193,
    ],
)
def test_invalid_inputs_fail_before_any_effect(source):
    with pytest.raises((ValueError, UrlPolicyError)):
        inspect_source(source)


@pytest.mark.parametrize(
    "body,content_type",
    [
        (
            b'<meta property="og:title" content="Owned demo"><meta property="og:video:secure_url" content="https://cdn.example.invalid/owned.mp4?sig=private">',
            "text/html",
        ),
        (
            json.dumps(
                {
                    "@type": "VideoObject",
                    "name": "Owned demo",
                    "contentUrl": "https://cdn.example.invalid/owned.mp4?sig=private",
                }
            ).encode(),
            "application/json",
        ),
        (
            b'<script type="application/ld+json">{"@graph":[{"@type":"VideoObject","name":"Owned demo","contentUrl":"https://cdn.example.invalid/owned.mp4?sig=private"}]}</script>',
            "text/html",
        ),
    ],
)
def test_owned_loom_metadata_resolves_actual_video_route(body, content_type):
    """GIVEN explicit original page fields WHEN parsed THEN a checked media route is resolved."""
    result = resolve_loom_metadata(body, "https://loom.com/share/0123456789abcdef", content_type)
    assert result["title"] == "Owned demo"
    assert inspect_source(result["resolved_url"])["source_kind"] == "direct"
    assert result["live_verified"] is False


@pytest.mark.parametrize(
    "body,content_type",
    [
        (b"<html>Please sign in</html>", "text/html"),
        (
            b'{"@type":"VideoObject","embedUrl":"https://loom.com/embed/0123456789abcdef"}',
            "application/json",
        ),
        (b'<meta property="og:video" content="https://127.0.0.1/owned.mp4">', "text/html"),
        (b"original video bytes", "video/mp4"),
        (b"x" * (1024 * 1024 + 1), "text/html"),
    ],
)
def test_missing_unsafe_or_nonmetadata_loom_fields_fail_closed(body, content_type):
    with pytest.raises((ValueError, UrlPolicyError)):
        resolve_loom_metadata(body, "https://loom.com/share/0123456789abcdef", content_type)
