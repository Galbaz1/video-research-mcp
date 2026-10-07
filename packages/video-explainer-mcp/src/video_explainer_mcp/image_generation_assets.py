"""Bounded credential-free image custody and actual raster qualification."""

import base64
from collections.abc import AsyncIterator
import hashlib
from io import BytesIO
from pathlib import Path
import tempfile
from urllib.parse import urlsplit, urlunsplit

from .file_io import open_regular
from .generation_assets import request_bytes
from .materials import publish
from .render_artifacts import verify_output
from .render_storyboard_sources import confined_path

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_JOB_BYTES = 32 * 1024 * 1024
RESULT_HOSTS = ["dashscope-result-bj.oss-cn-beijing.aliyuncs.com",
                "dashscope-result-sz.oss-cn-shenzhen.aliyuncs.com",
                "dashscope-result-sh.oss-cn-shanghai.aliyuncs.com",
                "dashscope-result-sh.oss-accelerate.aliyuncs.com"]


def raster(body: bytes, *, output=False) -> dict:
    """Fully decode a bounded PNG/JPEG/WebP using an independently installed Pillow."""
    from PIL import Image

    if not body or len(body) > MAX_IMAGE_BYTES:
        raise ValueError("Image bytes exceed the selected 10 MiB custody bound")
    with Image.open(BytesIO(body)) as image:
        fmt, pixels = image.format, list(image.size)
        if fmt not in {"PNG", "JPEG", "WEBP"} or pixels[0] * pixels[1] > 16 * 1024 * 1024:
            raise ValueError("Raster format or decoded pixel bound is unsupported")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Animated image intent is unsupported")
        image.verify()
    with Image.open(BytesIO(body)) as image:
        image.load()
        if output and image.convert("RGBA").getchannel("A").getextrema()[0] < 255:
            raise ValueError("Provider returned unqualified transparent output")
    return {"format": fmt, "width": pixels[0], "height": pixels[1], "full_decode": True}


def reference_bytes(project: Path, source: dict) -> bytes:
    """Read and hash the same actual regular reference bytes used in the payload."""
    with open_regular(confined_path(project, source["path"])) as (stream, info):
        if info.st_size > MAX_IMAGE_BYTES:
            raise ValueError("Reference exceeds10MiB")
        body = stream.read(MAX_IMAGE_BYTES + 1)
    if len(body) > MAX_IMAGE_BYTES or hashlib.sha256(body).hexdigest() != source["sha256"]:
        raise ValueError("Reference bytes changed")
    return body


def image_data(project: Path, source: dict) -> str:
    """Carry exact pinned reference bytes through documented Base64 image input."""
    body = reference_bytes(project, source)
    info = raster(body)
    mime = {"PNG": "png", "JPEG": "jpeg", "WEBP": "webp"}[info["format"]]
    return "data:image/" + mime + ";base64," + base64.b64encode(body).decode("ascii")


async def verify_public_reference(project: Path, reference: dict) -> None:
    """Compare the translation URL's current actual bytes to the local immutable pin."""
    from .materials_remote import public_url

    url = reference["public_url"]
    if not url or not url.isascii():
        raise ValueError("Translation requires an ASCII public HTTPS URL; no upload seam")
    host = urlsplit(url).hostname or ""
    public_url(url, [host])
    import ipaddress

    if host in {"localhost", "localhost.localdomain"} or "." not in host:
        raise ValueError("Translation reference must be public")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None and not address.is_global:
        raise ValueError("Translation reference address is private")
    from .materials_remote import _fetch
    import asyncio
    import time

    body, final_url = await asyncio.to_thread(_fetch, url, {}, [host], MAX_IMAGE_BYTES,
                                             time.monotonic() + 25)
    if final_url != url or body != reference_bytes(project, reference["source"]):
        raise ValueError("Public translation reference differs from pinned local bytes")


async def acquire_images(project: Path, job_id: str, urls: list[str], request: dict,
                         saved: list[dict]) -> AsyncIterator[dict]:
    """Download bounded images without API authorization and refuse changed prior artifacts."""
    from .materials_remote import public_url

    assets = list(saved)
    for artifact in assets:
        if not verify_output(artifact, MAX_IMAGE_BYTES):
            raise ValueError("Previously captured image changed; reconciliation required")
    total = sum(a["size_bytes"] for a in assets)
    for index, url in enumerate(urls):
        if index < len(assets):
            continue
        if not isinstance(url, str) or len(url) > 4096:
            raise ValueError("Invalid provider image URL")
        parts = urlsplit(url)
        if parts.scheme != "https":
            raise ValueError("Provider result requires HTTPS transport")
        public_url(urlunsplit((parts.scheme, parts.netloc, parts.path, "", parts.fragment)), RESULT_HOSTS)
        body = await request_bytes("GET", url, {}, None, min(MAX_IMAGE_BYTES, MAX_JOB_BYTES - total))
        info = raster(body, output=True)
        expected_format = "JPEG" if request["generation"]["mode"] == "image_translate" else "PNG"
        if info["format"] != expected_format or [info["width"], info["height"]] != request["expected_pixels"]:
            raise ValueError("Actual image format/dimensions differ from frozen contract")
        sha = hashlib.sha256(body).hexdigest()
        name = f"image-{job_id}-{index}." + ("jpg" if expected_format == "JPEG" else "png")
        target = confined_path(project, name)
        artifact = {"path": str(target), "sha256": sha, "size_bytes": len(body)}
        if target.exists():
            if not verify_output(artifact, MAX_IMAGE_BYTES):
                raise ValueError("Existing image differs; overwrite refused")
        else:
            with tempfile.TemporaryDirectory(prefix=".image-generation-", dir=project) as directory:
                temporary = Path(directory) / "asset"
                temporary.write_bytes(body)
                publish(project, temporary, name, sha)
        artifact.update(qualification={**info, "artifact_sha256": sha,
                                       "semantic_quality": "UNQUALIFIED"},
                        url_sha256=hashlib.sha256(url.encode()).hexdigest(),
                        download_origin=parts.hostname,
                        handoff={"request": request["generation"], "contract": request["contract"],
                                 "source_revision": request["adapter_revision"],
                                 "continuation_settings": request["continuation_settings"],
                                 "continuation_semantics": "explicit image anchors and controls; no conversation state"})
        assets.append(artifact)
        total += len(body)
        yield artifact
