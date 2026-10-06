"""Single, bounded authenticated HTTP exchanges with pre-transmission peer proof."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
import ipaddress
import logging
import socket
from urllib.parse import urlsplit

import httpx

MAX_REQUEST_BYTES = 32 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
EXCHANGE_TIMEOUT_SECONDS = 120
CLEANUP_TIMEOUT_SECONDS = 5
_private_exchange = ContextVar("vision_http_private_exchange", default=False)


class _ExchangeLogFilter(logging.Filter):
    """Suppress URL/response-header/exception logs only in this exchange's task."""

    def filter(self, record):
        return not _private_exchange.get()


@contextmanager
def _quiet_transport_logs():
    """httpx logs query strings and httpcore DEBUG logs can include credentials."""
    loggers = [logging.getLogger(name) for name in (
        "httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2",
    )]
    owned_filter = _ExchangeLogFilter()
    for logger in loggers:
        logger.addFilter(owned_filter)
    token = _private_exchange.set(True)
    try:
        yield
    finally:
        _private_exchange.reset(token)
        for logger in loggers:
            logger.removeFilter(owned_filter)


def _public(address):
    return address.is_global and not address.is_multicast and not address.is_unspecified


async def _destination(url, local):
    """Reject unsafe authorities, then pin one address from an entirely public DNS set."""
    if not isinstance(url, str) or any(ord(char) <= 32 or ord(char) == 127 for char in url):
        raise ValueError("Vision HTTP URL contains invalid characters")
    try:
        parsed = urlsplit(url)
        original = httpx.URL(url)
        explicit_port = parsed.port
    except (ValueError, httpx.InvalidURL):
        raise ValueError("Vision HTTP URL is invalid") from None
    if not parsed.hostname or parsed.username is not None or parsed.password is not None or "#" in url:
        raise ValueError("Vision HTTP URL requires a host without userinfo or fragment")
    if parsed.scheme not in ({"http", "https"} if local else {"https"}):
        raise ValueError("Remote vision HTTP requires HTTPS")
    hostname = original.raw_host.decode("ascii")
    port = explicit_port if explicit_port is not None else 443 if parsed.scheme == "https" else 80
    if not 1 <= port <= 65535:
        raise ValueError("Vision HTTP port is invalid")
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None
    if local:
        if hostname not in {"127.0.0.1", "::1"}:
            raise ValueError("Local vision HTTP requires literal 127.0.0.1 or ::1")
        selected = literal
    elif literal is not None:
        if not _public(literal):
            raise ValueError("Remote vision HTTP requires a public address")
        selected = literal
    else:
        try:
            answers = await asyncio.get_running_loop().getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
            addresses = [ipaddress.ip_address(answer[4][0]) for answer in answers]
        except (OSError, ValueError):
            raise ValueError("Vision HTTP DNS resolution failed") from None
        if not addresses or any(not _public(address) for address in addresses):
            raise ValueError("Vision HTTP DNS must contain only public addresses")
        selected = addresses[0]
    host = f"[{hostname}]" if ":" in hostname else hostname
    authority = f"{host}:{explicit_port}" if explicit_port is not None else host
    return original.copy_with(host=str(selected)), hostname, authority, selected, port


def _request_headers(headers, authority, content):
    """Prevent caller-controlled Host/framing and reject header injection before DNS."""
    if not isinstance(headers, dict):
        raise ValueError("Vision HTTP headers must be a string mapping")
    result = {}
    for key, value in headers.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ValueError("Vision HTTP headers must be a string mapping")
        try:
            key.encode("ascii")
            value.encode("ascii")
        except UnicodeEncodeError:
            raise ValueError("Vision HTTP headers must be ASCII") from None
        if any(ord(char) < 32 or ord(char) == 127 for char in key + value):
            raise ValueError("Vision HTTP header contains invalid characters")
        if key.lower() in {"transfer-encoding", "content-length"}:
            raise ValueError("Vision HTTP framing headers are managed internally")
        if key.lower() not in {"host", "accept-encoding"}:
            result[key] = value
    result.update({"Host": authority, "Accept-Encoding": "identity", "Content-Length": str(len(content))})
    return result


def _peer_trace(selected, port, streams, require_limited=False):
    """httpcore calls connect_tcp.complete before TLS or any request header/body write."""
    attested = False

    async def trace(event, info):
        nonlocal attested
        if event == "connection.connect_tcp.complete":
            stream = info.get("return_value")
            if stream is not None:
                streams.append(stream)
            if require_limited and not isinstance(stream, _LimitedStream):
                raise PermissionError("Vision HTTP receive limit could not be verified")
            try:
                peer = stream.get_extra_info("server_addr")
                matches = isinstance(peer, tuple) and len(peer) >= 2 and (
                    ipaddress.ip_address(peer[0]) == selected and type(peer[1]) is int and peer[1] == port
                )
            except Exception:
                matches = False
            if not matches:
                raise PermissionError("Vision HTTP connected peer could not be verified")
            attested = True
        elif event in {"http11.send_request_headers.started", "http2.send_request_headers.started"}:
            if not attested:
                raise PermissionError("Vision HTTP peer attestation is required before transmission")
        elif event in {"http11.send_request_headers.failed", "http11.send_request_body.failed"}:
            # httpcore otherwise suppresses WriteError and may accept a later response.
            raise RuntimeError("Vision HTTP exchange failed") from None

    return trace, lambda: attested


class _LimitedStream:
    """Cap native HTTP reception, including headers, before parser allocation."""

    def __init__(self, stream, limit):
        self.stream, self.limit, self.received = stream, limit, 0

    def __getattr__(self, name):
        return getattr(self.stream, name)

    async def read(self, max_bytes, timeout=None):
        data = await self.stream.read(min(max_bytes, self.limit - self.received + 1), timeout=timeout)
        self.received += len(data)
        if self.received > self.limit:
            raise ValueError("Vision HTTP response exceeds the byte limit")
        return data

    async def start_tls(self, *args, **kwargs):
        self.stream = await self.stream.start_tls(*args, **kwargs)
        return self


class _LimitedBackend:
    """Apply the native response bound to the one selected TCP connection."""

    def __init__(self, backend, limit):
        self.backend, self.limit = backend, limit

    async def connect_tcp(self, *args, **kwargs):
        return _LimitedStream(await self.backend.connect_tcp(*args, **kwargs), self.limit)


async def _response_bytes(response, response_limit=MAX_RESPONSE_BYTES):
    """Bound raw response bytes without allocating an untrusted decompressed body."""
    length = response.headers.get("content-length")
    if length is not None and (not length.isdecimal() or int(length) > response_limit):
        raise ValueError("Vision HTTP response Content-Length exceeds or violates the byte limit")
    if response.headers.get("content-encoding", "identity").lower() != "identity":
        raise ValueError("Vision HTTP compressed responses are unsupported")
    data = bytearray()
    async for chunk in response.aiter_raw():
        if len(data) + len(chunk) > response_limit:
            raise ValueError("Vision HTTP response exceeds the byte limit")
        data.extend(chunk)
    return bytes(data)


async def _close_resources(client, streams):
    """Give every owned close an independent shared grace, even if another fails."""
    async with asyncio.timeout(CLEANUP_TIMEOUT_SECONDS):
        outcomes = await asyncio.gather(client.aclose(), *(stream.aclose() for stream in streams),
                                        return_exceptions=True)
    if any(isinstance(outcome, BaseException) for outcome in outcomes):
        raise RuntimeError("Vision HTTP cleanup failed")


async def _joined_cleanup(client, streams, primary):
    """Repeated caller cancellation cannot detach this independently bounded task."""
    cleanup = asyncio.create_task(_close_resources(client, streams), name="vision-http-cleanup")
    cancelled = None
    while not cleanup.done():
        try:
            await asyncio.shield(cleanup)
        except asyncio.CancelledError as exc:
            if cancelled is None:
                cancelled = exc
        except Exception:
            break
    try:
        cleanup.result()
    except (Exception, asyncio.CancelledError):
        if primary is None and cancelled is None:
            raise RuntimeError("Vision HTTP cleanup failed") from None
    if primary is None and cancelled is not None:
        raise cancelled


async def _exchange(
    url: str, *, headers: dict[str, str], content: bytes, method: str, local: bool = False,
    request_limit: int | None = None, response_limit: int | None = None,
) -> tuple[int, bytes]:
    """Validate and perform one owned exchange under the overall deadline."""
    if type(local) is not bool or method not in {"GET", "POST", "DELETE"} or not isinstance(content, bytes):
        raise ValueError("Vision HTTP requires GET/POST, byte content and a boolean local flag")
    request_limit = MAX_REQUEST_BYTES if request_limit is None else request_limit
    response_limit = MAX_RESPONSE_BYTES if response_limit is None else response_limit
    if (type(request_limit) is not int or not 0 < request_limit <= MAX_REQUEST_BYTES
            or type(response_limit) is not int or not 0 < response_limit <= MAX_RESPONSE_BYTES):
        raise ValueError("Vision HTTP byte limits must be positive bounded integers")
    if len(content) > request_limit:
        raise ValueError("Vision HTTP request exceeds the byte limit")
    prepared = _request_headers(headers, "", content)
    if not isinstance(url, str) or 64 + len(url.encode("utf-8")) + len(content) + sum(
        len(key) + len(value) + 4 for key, value in prepared.items()
    ) > request_limit:
        raise ValueError("Vision HTTP request exceeds the byte limit")
    deadline = asyncio.get_running_loop().time() + EXCHANGE_TIMEOUT_SECONDS
    client, primary, streams = None, None, []
    try:
        async with asyncio.timeout_at(deadline):
            target, hostname, authority, selected, port = await _destination(url, local)
            prepared["Host"] = authority
            trace, attested = _peer_trace(selected, port, streams, response_limit < MAX_RESPONSE_BYTES)
            transport = httpx.AsyncHTTPTransport(retries=0, trust_env=False, http2=False)
            if response_limit < MAX_RESPONSE_BYTES:
                transport._pool._network_backend = _LimitedBackend(transport._pool._network_backend, response_limit)
            client = httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                      timeout=EXCHANGE_TIMEOUT_SECONDS)
            async with client.stream(method, target, headers=prepared, content=content,
                                     extensions={"sni_hostname": hostname, "trace": trace}) as response:
                if not attested():
                    raise PermissionError("Vision HTTP transport did not attest its connected peer")
                return response.status_code, await _response_bytes(response, response_limit)
    except httpx.HTTPError:
        primary = RuntimeError("Vision HTTP exchange failed")
        raise primary from None
    except BaseException as exc:
        primary = exc
        raise
    finally:
        if client is not None:
            await _joined_cleanup(client, streams, primary)


async def exchange(
    url: str, *, headers: dict[str, str], content: bytes, method: str, local: bool = False,
    request_limit: int | None = None, response_limit: int | None = None,
) -> tuple[int, bytes]:
    """Return one status/body without retries, redirects, proxies or upstream logging.

    Request and response limits default to 32 MiB and 256 KiB; smaller response
    limits also bound received headers and framing. The 120-second
    request deadline includes DNS, connection, transmission and response. Owned
    cleanup has a separate five-second grace and is joined before returning.
    Credentials are caller-selected; this boundary never selects or logs secrets.
    """
    with _quiet_transport_logs():
        return await _exchange(url, headers=headers, content=content, method=method, local=local,
                               request_limit=request_limit, response_limit=response_limit)
