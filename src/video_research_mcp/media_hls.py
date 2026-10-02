"""Acquire bounded HLS VOD through checked HTTP, then remux owned local resources."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import shutil
import uuid
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from .config import get_config
from .media_hls_manifest import MAX_MANIFEST_BYTES, parse_manifest

MAX_MANIFEST_DEPTH = 2


def _public_url(url: str) -> str:
    """Keep acquisition lineage without exposing signed query values or fragments."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _resource_name(path: Path, kind: str) -> str:
    """Stage only media containers, never remote playlist/control text, for local remux."""
    if kind == "manifest":
        return "resource.bin"
    with path.open("rb") as stream:
        header = stream.read(376)
    box = header[4:8]
    if kind == "initialization" and box in {b"ftyp", b"moov"}:
        return "initialization.mp4"
    if kind == "segment":
        if len(header) >= 376 and header[0] == header[188] == 0x47:
            return "segment.ts"
        if box in {b"styp", b"moof", b"sidx", b"emsg"}:
            return "segment.m4s"
    raise ValueError(f"Unsupported HLS {kind} container; require MPEG-TS or fragmented MP4")


class _Resources:
    """Share the aggregate byte ceiling across every checked manifest and media fetch."""

    def __init__(self, directory: Path, ceiling: int):
        self.directory = directory
        self.ceiling = ceiling
        self.records: list[dict] = []

    async def fetch(self, url: str, kind: str) -> dict:
        """Fetch one derived URL into a distinct owned directory with remaining budget."""
        from .media_fetch import fetch_resource

        remaining = self.ceiling - sum(record["bytes"] for record in self.records)
        if remaining <= 0:
            raise ValueError("HLS aggregate download byte limit exhausted")
        directory = self.directory / f"resource-{len(self.records):03d}"
        directory.mkdir(mode=0o700)
        limit = min(remaining, MAX_MANIFEST_BYTES) if kind == "manifest" else remaining
        resource = await fetch_resource(url, directory, max_bytes=limit)
        path = Path(resource["path"])
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(directory):
            raise ValueError("HLS fetch returned a resource outside owned staging")
        if path.stat().st_size != resource["bytes"] or not 0 < resource["bytes"] <= limit:
            raise ValueError("HLS fetched resource violates its byte budget")
        owned = directory / _resource_name(path, kind)
        if path != owned:
            path.rename(owned)
        self.records.append(
            {
                "kind": kind,
                "requested_url": _public_url(url),
                "final_url": _public_url(resource["final_url"]),
                "bytes": resource["bytes"],
                "sha256": resource["sha256"],
                "content_type": resource["content_type"],
                "content_length": resource["content_length"],
            }
        )
        return {**resource, "path": owned}


async def _select_playlist(url: str, resources: _Resources) -> tuple[dict, dict, list]:
    """Follow at most two muxed master selections using each response's final URL."""
    selected, seen = [], set()
    for depth in range(MAX_MANIFEST_DEPTH + 1):
        if url in seen:
            raise ValueError("HLS manifest cycle is unsupported")
        seen.add(url)
        resource = await resources.fetch(url, "manifest")
        try:
            text = resource["path"].read_text(encoding="utf-8-sig")
        except UnicodeError as exc:
            raise ValueError("HLS manifest is not UTF-8 text") from exc
        playlist = parse_manifest(text, resource["final_url"])
        if "variants" not in playlist:
            return playlist, resource, selected
        if depth == MAX_MANIFEST_DEPTH:
            raise ValueError("HLS exceeds master manifest depth 2")
        variant = min(playlist["variants"], key=lambda item: (item["bandwidth"], item["url"]))
        selected.append({"url": _public_url(variant["url"]), "bandwidth": variant["bandwidth"]})
        url = variant["url"]
    raise ValueError("HLS did not resolve a finite media playlist")


async def _local_manifest(playlist: dict, resources: _Resources) -> Path:
    """Rewrite only fetched, generated local paths; remote URLs never reach FFmpeg."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:7", "#EXT-X-PLAYLIST-TYPE:VOD"]
    lines.append(f"#EXT-X-TARGETDURATION:{playlist['target_duration']}")
    if playlist["initialization_url"]:
        initialization = await resources.fetch(playlist["initialization_url"], "initialization")
        relative = initialization["path"].relative_to(resources.directory)
        lines.append(f'#EXT-X-MAP:URI="{relative.as_posix()}"')
    for segment in playlist["segments"]:
        resource = await resources.fetch(segment["url"], "segment")
        lines.extend(
            (
                f"#EXTINF:{segment['duration']},",
                resource["path"].relative_to(resources.directory).as_posix(),
            )
        )
    lines.append("#EXT-X-ENDLIST")
    path = resources.directory / "local.m3u8"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _probe_result(raw: bytes, expected_duration: float) -> dict:
    """Validate observed stream/container metadata without claiming decoded quality."""
    try:
        probe = json.loads(raw)
        streams = probe["streams"]
        duration = float(probe["format"]["duration"])
        media = any(stream["codec_type"] in {"video", "audio"} for stream in streams)
    except (ValueError, TypeError, KeyError) as exc:
        raise ValueError("HLS remux probe returned malformed media metadata") from exc
    if not media or not math.isfinite(duration) or not 0 < duration <= 3600:
        raise ValueError("HLS remux requires finite audio/video streams within 3600 seconds")
    if abs(duration - expected_duration) > max(0.25, expected_duration * 0.01):
        raise ValueError("HLS remux duration differs from declared segment coverage")
    return {"streams": streams, "duration_seconds": duration}


async def _remux(local: Path, duration: float, ceiling: int, timeout: float) -> tuple[Path, dict]:
    """Copy streams from local HLS only and inspect the resulting MP4 container."""
    from .media_process import run_media_process

    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    output = local.parent / "acquired.mp4"
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-protocol_whitelist",
        "file",
        "-i",
        str(local),
        "-map",
        "0",
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        "-fs",
        str(ceiling),
        "-y",
        str(output),
    ]
    await run_media_process(command, timeout, cwd=local.parent)
    if output.is_symlink() or not output.is_file() or not 0 < output.stat().st_size <= ceiling:
        raise ValueError("HLS remux produced no bounded, nonempty MP4")
    raw, _ = await run_media_process(
        [
            ffprobe,
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-show_entries",
            "format=duration:stream=codec_type,codec_name,width,height",
            "-of",
            "json",
            str(output),
        ],
        timeout,
        cwd=local.parent,
    )
    return output, _probe_result(raw, duration)


def _output_revision(path: Path) -> dict:
    """Hash the completed local remux without reading the whole asset into memory."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def _provenance(
    url: str,
    playlist: dict,
    manifest: dict,
    selection: list,
    resources: _Resources,
    revision: dict,
    probe: dict,
) -> dict:
    """Separate actual downloaded/output bytes, observed metadata and unknown quality/rights."""
    return {
        "adapter": "hls-vod",
        "source_url": _public_url(url),
        "final_url": _public_url(manifest["final_url"]),
        "resources": resources.records,
        "selection": selection,
        "manifest_depth": len(selection),
        "segment_count": len(playlist["segments"]),
        "duration_seconds": playlist["duration_seconds"],
        "downloaded_bytes": sum(record["bytes"] for record in resources.records),
        "output": revision,
        "container_probe": probe,
        "decoded_media": "unverified",
        "ffmpeg_network": "disabled",
        "authentication": "unknown",
        "rights": "unknown",
    }


async def acquire_hls(url: str, staging_dir: Path) -> dict:
    """Fetch finite unencrypted HLS VOD under one timeout, retaining acquisition lineage.

    Args:
        url: HTTPS HLS manifest URL, checked independently for every derived resource.
        staging_dir: Caller-owned staging directory; siblings are preserved.

    Returns:
        Owned MP4 path and explicit download, container-probe and rights provenance.
    """
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise FileNotFoundError("HLS acquisition requires configured local ffmpeg and ffprobe")
    cfg = get_config()
    directory = staging_dir.resolve() / ("hls-" + uuid.uuid4().hex)
    directory.mkdir(parents=True, mode=0o700)
    resources = _Resources(directory, cfg.media_max_input_bytes)
    try:
        async with asyncio.timeout(cfg.media_acquire_timeout_seconds):
            playlist, manifest, selection = await _select_playlist(url, resources)
            local = await _local_manifest(playlist, resources)
            output, probe = await _remux(
                local,
                playlist["duration_seconds"],
                cfg.media_max_input_bytes,
                cfg.media_acquire_timeout_seconds,
            )
            revision = await asyncio.to_thread(_output_revision, output)
            return {
                "path": output,
                "provenance": _provenance(
                    url, playlist, manifest, selection, resources, revision, probe
                ),
            }
    except BaseException:
        shutil.rmtree(directory)
        raise
