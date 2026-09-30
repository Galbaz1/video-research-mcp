"""Pure media source classification and explicit Loom metadata resolution.

Platform support is a routing decision, not evidence of live access. Loom parsing
is independently implemented for explicit Open Graph/VideoObject media fields;
the pinned upstream audit contains registration but no Loom adapter body.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

from .redaction import redact_text
from .url_policy import UrlPolicyError, _is_blocked_ip

VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".webm": "video/webm",
    ".mov": "video/quicktime",
    ".avi": "video/x-msvideo",
    ".mkv": "video/x-matroska",
    ".mpeg": "video/mpeg",
    ".wmv": "video/x-ms-wmv",
    ".3gpp": "video/3gpp",
}
_YOUTUBE = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}
_LOOM = {"loom.com", "www.loom.com"}


def checked_url_shape(url: str) -> str:
    """Check URL syntax without DNS or fetching; network helpers enforce peers."""
    try:
        p = urlsplit(url)
        if p.scheme != "https" or not p.hostname or p.username or p.password:
            raise ValueError
        if p.port not in (None, 443) or any(ord(c) < 33 for c in url):
            raise ValueError
        try:
            if _is_blocked_ip(p.hostname):
                raise ValueError
        except ValueError as exc:
            if ":" in p.hostname or re.fullmatch(r"[\d.]+", p.hostname):
                raise UrlPolicyError("Media URL has a blocked or invalid IP address") from exc
        return url
    except ValueError as exc:
        raise UrlPolicyError(
            "Media URLs require HTTPS, no credentials, and the default port"
        ) from exc


def inspect_source(source: str) -> dict:
    """Classify a supported source without contacting it or reading media bytes.

    Args:
        source: Local video path, supported platform URL, or direct video/HLS URL.

    Returns:
        Routing capabilities and a redacted source display. Access is unverified.
    """
    if not source or len(source) > 8192 or "\x00" in source:
        raise ValueError("Expected a nonempty media source of at most 8192 characters")
    p = urlsplit(source)
    kind, identifier = "unsupported", None
    if not p.scheme and not source.startswith("//"):
        kind = "local" if Path(source).suffix.lower() in VIDEO_TYPES else "unsupported"
    else:
        checked_url_shape(source)
        host = p.hostname.lower()
        parts = p.path.strip("/").split("/")
        if host in _YOUTUBE:
            identifier = (
                parts[0]
                if host == "youtu.be"
                else parse_qs(p.query).get("v", [""])[0]
                if p.path == "/watch"
                else parts[1]
                if len(parts) == 2 and parts[0] in {"shorts", "embed"}
                else ""
            )
            if not re.fullmatch(r"[A-Za-z0-9_-]{11}", identifier):
                raise ValueError("Expected a canonical eleven-character YouTube video ID")
            kind = "youtube"
        elif host in _LOOM:
            if (
                len(parts) != 2
                or parts[0] not in {"share", "embed"}
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,64}", parts[1])
            ):
                raise ValueError("Expected a Loom share or embed URL with a video ID")
            kind, identifier = "loom", parts[1]
        elif Path(p.path).suffix.lower() == ".m3u8":
            kind = "hls"
        elif Path(p.path).suffix.lower() in VIDEO_TYPES:
            kind = "direct"
    metadata_runtime = {"local": ["ffprobe"], "youtube": ["YouTube Data API access"]}.get(kind, [])
    acquisition_runtime = {"youtube": ["yt-dlp"], "hls": ["ffmpeg", "ffprobe"]}.get(kind, [])
    return {
        "source_kind": kind,
        "source": redact_text(source),
        "source_id": identifier,
        "metadata_supported": kind != "unsupported",
        "acquisition_supported": kind != "unsupported",
        "inspection_performed": "syntax_only",
        "access_state": "unverified",
        "metadata_prerequisites": metadata_runtime,
        "acquisition_prerequisites": acquisition_runtime,
        "required_runtime": list(dict.fromkeys(metadata_runtime + acquisition_runtime)),
        "hint": "Provide a local video, YouTube/Loom URL, or HTTPS direct video/HLS URL"
        if kind == "unsupported"
        else "",
    }


class _LoomFields(HTMLParser):
    """Read only explicit metadata; never execute embedded page code."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.meta: dict[str, str] = {}
        self.json_text: list[str] = []
        self._script: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "meta":
            key = values.get("property") or values.get("name")
            if key and values.get("content"):
                self.meta[key] = values["content"]
        if tag == "script" and values.get("type") == "application/ld+json":
            self._script = []

    def handle_data(self, data: str) -> None:
        if self._script is not None:
            self._script.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self._script is not None:
            self.json_text.append("".join(self._script))
            self._script = None


def resolve_loom_metadata(body: bytes, page_url: str, content_type: str) -> dict:
    """Resolve an explicit direct video/HLS URL from bounded Loom page metadata.

    Args:
        body: At most one MiB of metadata HTML or JSON, never a media body.
        page_url: Checked final page URL, used for relative metadata URLs.
        content_type: Response content type.

    Returns:
        Resolved URL for checked acquisition and a live-unverified parser receipt.
    """
    if len(body) > 1024 * 1024:
        raise ValueError("Loom metadata exceeds the one MiB limit")
    if "html" not in content_type and "json" not in content_type:
        raise ValueError("Loom metadata requires HTML or JSON; no media body is accepted")
    parser = _LoomFields()
    text = body.decode("utf-8")
    documents = [text] if "json" in content_type else []
    if "html" in content_type:
        parser.feed(text)
        documents.extend(parser.json_text)
    candidates = [
        parser.meta.get(key) for key in ("og:video:secure_url", "og:video:url", "og:video")
    ]
    title = parser.meta.get("og:title", "")
    for document in documents:
        try:
            value = json.loads(document)
        except json.JSONDecodeError:
            continue
        nodes = value if isinstance(value, list) else [value]
        if isinstance(value, dict) and isinstance(value.get("@graph"), list):
            nodes.extend(value["@graph"])
        for node in nodes:
            if isinstance(node, dict) and node.get("@type") == "VideoObject":
                candidates.append(node.get("contentUrl"))
                title = node.get("name", title)
    for candidate in candidates:
        if isinstance(candidate, str) and candidate:
            resolved = checked_url_shape(urljoin(page_url, candidate))
            if inspect_source(resolved)["source_kind"] in {"direct", "hls"}:
                return {
                    "resolved_url": resolved,
                    "title": str(title)[:1000],
                    "resolution": "explicit_og_video_or_videoobject",
                    "live_verified": False,
                }
    raise ValueError(
        "Loom metadata exposes no supported media URL; authentication or a changed page may require an authorized local export or direct video URL"
    )
