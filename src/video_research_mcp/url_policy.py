"""URL validation and safe download with SSRF protection.

Enforces HTTPS-only, blocks private/loopback/link-local IP ranges,
rejects embedded credentials, and streams downloads with a size cap.
Post-connect peer IP verification guards against DNS rebinding.
Used by research_document to safely fetch user-supplied URLs.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_BLOCKED_RANGES_MSG = (
    "private, loopback, link-local, multicast, and reserved addresses are not allowed"
)


class UrlPolicyError(Exception):
    """Raised when a URL violates the security policy."""


def _is_blocked_ip(ip_str: str) -> bool:
    """Check if an IP address falls in a blocked range."""
    ip = ip_address(ip_str)
    return (
        ip.is_loopback or ip.is_private or ip.is_link_local
        or ip.is_multicast or ip.is_reserved
    )


async def _resolve_dns(hostname: str) -> list:
    """Resolve hostname via async event-loop DNS (non-blocking).

    Delegates to the event loop's threadpool so the main loop stays
    responsive even under slow or hanging DNS.
    """
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(
        hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
    )


async def validate_url(url: str) -> None:
    """Validate a URL against the security policy.

    Uses async DNS resolution to avoid blocking the event loop.

    Checks:
    - HTTPS scheme only
    - No embedded credentials (userinfo)
    - Hostname present and DNS-resolvable
    - Resolved IPs are not private, loopback, link-local, multicast, or reserved

    Raises:
        UrlPolicyError: If any check fails.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise UrlPolicyError(f"Only HTTPS URLs are allowed, got '{parsed.scheme}://'")

    if parsed.username or parsed.password:
        raise UrlPolicyError("URLs with embedded credentials are not allowed")

    hostname = parsed.hostname
    if not hostname:
        raise UrlPolicyError("URL has no hostname")

    try:
        addr_infos = await _resolve_dns(hostname)
    except socket.gaierror as exc:
        raise UrlPolicyError(f"DNS resolution failed for '{hostname}': {exc}") from exc

    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise UrlPolicyError(
                f"URL resolves to blocked IP range ({ip_str}) — {_BLOCKED_RANGES_MSG}"
            )


def _verify_peer_ip(response: httpx.Response) -> None:
    """Verify the connected peer IP is not in a blocked range.

    Guards against DNS rebinding: even though we pre-validated DNS,
    the HTTP client performs its own resolution. This post-connect
    check catches cases where DNS returned a different (internal) IP
    for the actual fetch.

    Raises:
        UrlPolicyError: If the peer IP is in a blocked range.
    """
    stream = response.extensions.get("network_stream")
    if stream is None:
        return

    peername = stream.get_extra_info("peername")
    if peername is None:
        return

    ip_str = peername[0]
    if _is_blocked_ip(ip_str):
        raise UrlPolicyError(
            f"DNS rebinding detected: peer IP {ip_str} is in a blocked range — "
            f"{_BLOCKED_RANGES_MSG}"
        )


async def download_checked(url: str, tmp_dir: Path, *, max_bytes: int) -> Path:
    """Download a URL with SSRF protection and size limits.

    Uses async DNS pre-validation and post-connect peer IP verification
    to guard against DNS rebinding attacks.

    Args:
        url: HTTPS URL to download.
        tmp_dir: Directory to write the downloaded file into.
        max_bytes: Maximum response body size in bytes.

    Returns:
        Path to the downloaded file.

    Raises:
        UrlPolicyError: If the URL fails validation, DNS rebinding is
            detected, or the response exceeds max_bytes.
        httpx.HTTPStatusError: If the server returns an error status.
    """
    await validate_url(url)

    url_path = url.rsplit("/", 1)[-1].split("?")[0]
    filename = url_path if "." in url_path else "document.pdf"
    local = tmp_dir / filename

    max_redirects = 5
    current_url = url
    redirects_followed = 0

    async with httpx.AsyncClient(follow_redirects=False, timeout=60) as client:
        while True:
            async with client.stream("GET", current_url) as resp:
                _verify_peer_ip(resp)

                if resp.status_code in {301, 302, 303, 307, 308}:
                    location = resp.headers.get("location")
                    if not location:
                        raise UrlPolicyError(
                            f"Redirect response missing Location header (status {resp.status_code})"
                        )
                    if redirects_followed >= max_redirects:
                        raise UrlPolicyError(
                            f"Too many redirects (>{max_redirects}) while downloading URL"
                        )

                    next_url = str(resp.url.join(location))
                    await validate_url(next_url)
                    current_url = next_url
                    redirects_followed += 1
                    continue

                resp.raise_for_status()
                accumulated = 0
                with local.open("wb") as f:
                    async for chunk in resp.aiter_bytes():
                        accumulated += len(chunk)
                        if accumulated > max_bytes:
                            raise UrlPolicyError(
                                f"Response exceeds size limit ({max_bytes} bytes)"
                            )
                        f.write(chunk)
                break

    logger.info("Downloaded %s (%d bytes) to %s", url, accumulated, local)
    return local
