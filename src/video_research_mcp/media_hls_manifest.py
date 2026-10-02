"""Parse the finite, unencrypted, muxed HLS VOD subset supported by acquisition."""

from __future__ import annotations

import math
import re
from urllib.parse import urljoin

MAX_SEGMENTS = 200
MAX_DURATION_SECONDS = 3600
MAX_MANIFEST_BYTES = 128 * 1024


def _attributes(value: str) -> dict[str, str]:
    """Read HLS attributes without splitting commas inside quoted URI values."""
    attributes = {}
    pattern = re.compile(r'([A-Z0-9-]+)=(?:"([^"\r\n]*)"|([^,\s]+))(?:,|$)')
    while value:
        match = pattern.match(value)
        if not match or match[1] in attributes:
            raise ValueError("Malformed HLS attribute list")
        attributes[match[1]] = match[2] if match[2] is not None else match[3]
        value = value[match.end() :]
    return attributes


def _positive_duration(value: str) -> float:
    """Reject missing, nonfinite, zero and negative segment intervals."""
    try:
        duration = float(value.split(",", 1)[0])
    except ValueError as exc:
        raise ValueError("Malformed HLS EXTINF duration") from exc
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("HLS segment duration must be finite and positive")
    return duration


def _metadata_tag(line: str) -> None:
    """Validate metadata that does not change the selected media resource graph."""
    if line.startswith("#EXT-X-PLAYLIST-TYPE:"):
        if line != "#EXT-X-PLAYLIST-TYPE:VOD":
            raise ValueError("Only finite HLS VOD is supported; EVENT playlists are unsupported")
    elif line.startswith(("#EXT-X-VERSION:", "#EXT-X-MEDIA-SEQUENCE:")):
        value = line.split(":", 1)[1]
        if not value.isdigit():
            raise ValueError("Malformed HLS integer metadata")
    elif line == "#EXT-X-INDEPENDENT-SEGMENTS":
        return
    elif line.startswith("#EXT-X-PROGRAM-DATE-TIME:"):
        return
    elif line.startswith("#EXT"):
        raise ValueError(f"Unsupported HLS tag: {line.split(':', 1)[0]}")


def _append_segment(segments: list, line: str, duration: float | None, base_url: str) -> None:
    """Bind exactly one URI to each finite segment interval and enforce cohort bounds."""
    if duration is None:
        raise ValueError("HLS segment URI lacks EXTINF duration")
    segments.append({"url": urljoin(base_url, line), "duration": duration})
    if len(segments) > MAX_SEGMENTS:
        raise ValueError(f"HLS exceeds {MAX_SEGMENTS} segments")
    if sum(segment["duration"] for segment in segments) > MAX_DURATION_SECONDS:
        raise ValueError(f"HLS exceeds {MAX_DURATION_SECONDS} seconds")


def _media_playlist(lines: list[str], base_url: str) -> dict:
    """Read a complete media playlist; unsupported resource-changing tags fail closed."""
    segments, duration, initialization, target, ended = [], None, None, None, False
    for line in lines:
        if ended:
            raise ValueError("HLS has content after ENDLIST")
        if line == "#EXT-X-ENDLIST":
            ended = True
        elif line.startswith("#EXT-X-TARGETDURATION:"):
            value = line.split(":", 1)[1]
            if not value.isdigit() or int(value) <= 0 or target is not None:
                raise ValueError("Malformed HLS target duration")
            target = int(value)
        elif line.startswith("#EXTINF:"):
            if duration is not None:
                raise ValueError("HLS EXTINF lacks a segment URI")
            duration = _positive_duration(line.split(":", 1)[1])
        elif line.startswith("#EXT-X-MAP:"):
            attrs = _attributes(line.split(":", 1)[1])
            if initialization or segments or "BYTERANGE" in attrs or not attrs.get("URI"):
                raise ValueError("Unsupported HLS initialization map or byte range")
            initialization = urljoin(base_url, attrs["URI"])
        elif line.startswith("#EXT-X-KEY:"):
            if _attributes(line.split(":", 1)[1]) != {"METHOD": "NONE"}:
                raise ValueError("Encrypted HLS is unsupported")
        elif line.startswith("#"):
            _metadata_tag(line)
        else:
            _append_segment(segments, line, duration, base_url)
            duration = None
    if not ended or not segments or duration is not None or target is None:
        raise ValueError("HLS requires a finite VOD with target duration, segments and ENDLIST")
    return {
        "segments": segments,
        "initialization_url": initialization,
        "duration_seconds": sum(segment["duration"] for segment in segments),
        "target_duration": target,
    }


def _master_playlist(lines: list[str], base_url: str) -> dict:
    """Retain muxed variants only; external audio/video renditions need another route."""
    variants, pending = [], None
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            if pending is not None:
                raise ValueError("HLS variant lacks URI")
            attrs = _attributes(line.split(":", 1)[1])
            bandwidth = attrs.get("BANDWIDTH", "")
            if not bandwidth.isdigit() or int(bandwidth) <= 0:
                raise ValueError("Malformed HLS variant bandwidth")
            if any(key in attrs for key in ("AUDIO", "VIDEO", "SUBTITLES")):
                raise ValueError("Separate HLS renditions are unsupported; use muxed VOD")
            pending = int(bandwidth)
        elif line.startswith("#EXT-X-SESSION-KEY:"):
            raise ValueError("Encrypted HLS master is unsupported")
        elif line.startswith(("#EXT-X-MEDIA:", "#EXT-X-I-FRAME-STREAM-INF:")):
            raise ValueError("Separate HLS renditions are unsupported; use muxed VOD")
        elif line.startswith("#"):
            _metadata_tag(line)
        else:
            if pending is None:
                raise ValueError("HLS variant URI lacks STREAM-INF")
            variants.append({"url": urljoin(base_url, line), "bandwidth": pending})
            pending = None
            if len(variants) > MAX_SEGMENTS:
                raise ValueError("HLS exceeds 200 variant candidates")
    if not variants or pending is not None:
        raise ValueError("HLS master requires complete muxed variants")
    return {"variants": variants}


def parse_manifest(text: str, base_url: str) -> dict:
    """Parse supported HLS into resolved resources without fetching any derived URL."""
    if len(text.encode("utf-8")) > MAX_MANIFEST_BYTES:
        raise ValueError(f"HLS manifest exceeds {MAX_MANIFEST_BYTES} bytes")
    lines = [line.strip() for line in text.removeprefix("\ufeff").splitlines() if line.strip()]
    if not lines or lines.pop(0) != "#EXTM3U":
        raise ValueError("Malformed HLS manifest: missing EXTM3U header")
    if any(line.startswith("#EXT-X-STREAM-INF:") for line in lines):
        return _master_playlist(lines, base_url)
    return _media_playlist(lines, base_url)
