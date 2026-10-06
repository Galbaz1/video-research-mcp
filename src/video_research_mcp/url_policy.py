"""URL validation and safe download with SSRF protection.

Enforces HTTPS-only, blocks private/loopback/link-local IP ranges,
rejects embedded credentials, and streams downloads with a size cap.
Validated address snapshots prevent DNS rebinding during connection setup.
Used by research_document to safely fetch user-supplied URLs.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from contextlib import asynccontextmanager
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlparse

import httpx

from .redaction import redact_text

logger = logging.getLogger(__name__)

_BLOCKED_RANGES_MSG = (
    "non-public, multicast, and reserved addresses are not allowed"
)


class UrlPolicyError(Exception):
    """Raised when a URL violates the security policy."""


def _is_blocked_ip(ip_str: str) -> bool:
    """Check if an IP address falls in a blocked range."""
    ip = ip_address(ip_str)
    return not ip.is_global or ip.is_multicast or ip.is_reserved


async def _resolve_dns(hostname: str) -> list:
    """Resolve hostname via async event-loop DNS (non-blocking).

    Delegates to the event loop's threadpool so the main loop stays
    responsive even under slow or hanging DNS.
    """
    loop = asyncio.get_running_loop()
    return await loop.getaddrinfo(
        hostname, None, family=socket.AF_UNSPEC, type=socket.SOCK_STREAM,
    )


async def validate_url(url: str) -> tuple[str, ...]:
    """Validate a URL against the security policy.

    Uses async DNS resolution to avoid blocking the event loop.

    Checks:
    - HTTPS scheme only
    - No embedded credentials (userinfo)
    - Hostname present and DNS-resolvable
    - Resolved IPs are not private, loopback, link-local, multicast, or reserved

    Returns:
        The ordered, deduplicated public addresses admitted for this URL.

    Raises:
        UrlPolicyError: If any check fails.
    """
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise UrlPolicyError(f"Only HTTPS URLs are allowed, got '{parsed.scheme}://'")

    if parsed.username or parsed.password:
        raise UrlPolicyError("URLs with embedded credentials are not allowed")

    hostname = httpx.URL(url).raw_host.decode("ascii")
    if not hostname:
        raise UrlPolicyError("URL has no hostname")

    try:
        addr_infos = await _resolve_dns(hostname)
    except socket.gaierror as exc:
        raise UrlPolicyError(f"DNS resolution failed for '{hostname}': {exc}") from exc

    if not addr_infos:
        raise UrlPolicyError(f"DNS resolution returned no addresses for '{hostname}'")

    addresses = []
    for _family, _type, _proto, _canonname, sockaddr in addr_infos:
        ip_str = sockaddr[0]
        if _is_blocked_ip(ip_str):
            raise UrlPolicyError(
                f"URL resolves to blocked IP range ({ip_str}) — {_BLOCKED_RANGES_MSG}"
            )
        addresses.append(ip_str)
    return tuple(dict.fromkeys(addresses))


class _PinnedTransport(httpx.AsyncHTTPTransport):
    """Connect only to admitted addresses while retaining the logical HTTP origin."""

    def __init__(self, addresses: tuple[str, ...]):
        super().__init__(
            trust_env=False,
            limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
        )
        self.addresses = addresses

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Pin each connect, preserving Host, hostname TLS and response identity."""
        original_url = request.url
        timeouts = request.extensions["timeout"]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeouts["connect"]
        request.extensions["sni_hostname"] = original_url.raw_host.decode("ascii")
        try:
            for index, address in enumerate(self.addresses):
                remaining = deadline - loop.time()
                if remaining <= 0:
                    raise httpx.ConnectTimeout("Admitted address connection budget expired", request=request)
                request.url = original_url.copy_with(host=address)
                request.extensions["timeout"] = {**timeouts, "connect": remaining}
                try:
                    return await super().handle_async_request(request)
                except (httpx.ConnectError, httpx.ConnectTimeout):
                    if index == len(self.addresses) - 1:
                        raise
        finally:
            # HTTPX extracts cookies and joins redirects after the transport returns.
            request.url = original_url
            request.extensions["timeout"] = timeouts


def _verify_peer_ip(response: httpx.Response) -> None:
    """Verify the connected peer IP is not in a blocked range.

    Fails closed if the transport cannot report a public actual peer,
    independently of its admitted address snapshot.

    Raises:
        UrlPolicyError: If the peer IP is in a blocked range.
    """
    stream = response.extensions.get("network_stream")
    if stream is None:
        raise UrlPolicyError("Cannot verify connected peer: missing network stream")

    peername = stream.get_extra_info("server_addr")
    if peername is None:
        raise UrlPolicyError("Cannot verify connected peer: missing server address")

    ip_str = peername[0]
    if _is_blocked_ip(ip_str):
        raise UrlPolicyError(
            f"DNS rebinding detected: peer IP {ip_str} is in a blocked range — "
            f"{_BLOCKED_RANGES_MSG}"
        )


@asynccontextmanager
async def checked_response(url: str, method: str = "GET", *, allowed_hosts: set[str] | None = None):
    """Open guarded HTTPS metadata or an identity-encoded response body."""
    hosts = None if allowed_hosts is None else {
        httpx.URL(host=host).raw_host for host in allowed_hosts
    }

    def check_host(value: str) -> None:
        if hosts is not None and httpx.URL(value).raw_host not in hosts:
            raise UrlPolicyError("Source domain is outside the requested allowlist")

    check_host(url)
    transport = _PinnedTransport(await validate_url(url))
    async with httpx.AsyncClient(
        follow_redirects=False, timeout=60, trust_env=False, transport=transport,
        headers={"Accept-Encoding": "identity"},
    ) as client:
        for hop in range(6):
            async with client.stream(method, url) as response:
                _verify_peer_ip(response)
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise UrlPolicyError("Redirect response missing Location header")
                    if hop == 5:
                        raise UrlPolicyError("Too many redirects (>5) while downloading URL")
                    url = str(response.url.join(location))
                    check_host(url)
                    transport.addresses = await validate_url(url)
                    continue
                response.raise_for_status()
                if method.upper() != "HEAD" and any(
                    encoding.strip().lower() != "identity"
                    for encoding in response.headers.get("content-encoding", "identity").split(",")
                ):
                    raise UrlPolicyError("Unsupported Content-Encoding: response must use identity")
                yield response
                return


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
    url_path = Path(urlparse(url).path).name
    filename = url_path if "." in url_path else "document.pdf"
    if filename in {".", ".."}:
        filename = "document.pdf"
    local = tmp_dir / filename
    accumulated = 0
    created = False
    try:
        async with checked_response(url) as resp:
            with local.open("xb") as f:
                created = True
                async for chunk in resp.aiter_bytes():
                    accumulated += len(chunk)
                    if accumulated > max_bytes:
                        raise UrlPolicyError(
                            f"Response exceeds size limit ({max_bytes} bytes)"
                        )
                    f.write(chunk)
    except BaseException:
        if created:
            local.unlink(missing_ok=True)
        raise

    logger.info("Downloaded %s (%d bytes) to %s", redact_text(url), accumulated, local)
    return local
