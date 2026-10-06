"""Real installed HTTP transport regressions with in-memory network boundaries."""

from __future__ import annotations

import asyncio
import json
import os
from ipaddress import ip_address
from pathlib import Path
import re
import socket
import ssl

import anyio
from anyio._backends._asyncio import AsyncIOBackend
from anyio.streams.tls import TLSStream
import httpx
import pytest

from video_research_mcp.url_policy import UrlPolicyError, checked_response

PUBLIC = "93.184.216.34"
PUBLIC_V6 = "2606:4700:4700::1111"


class _Socket:
    """Return scripted HTTP bytes while recording the actual transport operations."""

    def __init__(self, network, host, port, wire):
        self.network, self.host, self.port, self.wire = network, host, port, wire
        self.closed = False

    async def send(self, item):
        if item:
            self.network.events.append({"event": "request_write", "address": self.host,
                                        "request": item.decode("ascii")})
            if self.network.block_write:
                self.network.write_started.set()
                await asyncio.Future()

    async def receive(self, max_bytes=65536):
        assert self.wire and len(self.wire) <= max_bytes
        data, self.wire = self.wire, b""
        self.network.events.append({"event": "wire_read", "bytes": len(data)})
        return data

    async def aclose(self):
        self.closed = True
        self.network.events.append({"event": "close", "address": self.host})

    def extra(self, attribute, default=None):
        if attribute == anyio.abc.SocketAttribute.remote_address:
            peer = self.network.peer if self.network.override_peer else (self.host, self.port)
            self.network.events.append({"event": "peer", "address": peer})
            return peer
        return default


class _Network:
    """Control only DNS, platform socket-connect and TLS-wrap boundaries."""

    def __init__(self):
        self.answers = [PUBLIC]
        self.rebind = False
        self.fail_addresses = set()
        self.events, self.sockets, self.requests = [], [], []
        self.responses = [(200, {}, b"OK")]
        self.override_peer, self.peer = False, None
        self.block_write = False
        self.write_started = asyncio.Event()

    async def resolve(self, host, port):
        resolutions = [e for e in self.events if e["event"] == "resolve"]
        answers = ["10.0.0.1"] if self.rebind and resolutions else self.answers
        name = host.decode("ascii") if isinstance(host, bytes) else host
        self.events.append({"event": "resolve", "hostname": name, "addresses": answers})
        return [(socket.AF_INET6 if ip_address(ip).version == 6 else socket.AF_INET,
                 socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, port or 0)) for ip in answers]

    async def connect(self, host, port):
        self.events.append({"event": "connect", "address": host, "port": port})
        if host in self.fail_addresses:
            raise OSError("scripted connect refusal")
        status, headers, body = self.responses.pop(0)
        fields = {"Content-Length": str(len(body)), "Connection": "close", **headers}
        wire = f"HTTP/1.1 {status} Test\r\n".encode()
        wire += b"".join(f"{key}: {value}\r\n".encode() for key, value in fields.items())
        stream = _Socket(self, host, port, wire + b"\r\n" + body)
        self.sockets.append(stream)
        return stream


@pytest.fixture
def network(monkeypatch, request):
    """Keep real HTTPX/httpcore/AnyIO above fake socket/TLS and refuse real I/O."""
    net = _Network()

    async def resolve(loop, host, port, **kwargs):
        return await net.resolve(host, port)

    async def connect(cls, host, port, local_address=None):
        return await net.connect(host, port)

    async def tls(cls, stream, *, hostname, ssl_context, **kwargs):
        net.events.append({"event": "tls", "hostname": hostname,
                           "check_hostname": ssl_context.check_hostname,
                           "verify_mode": int(ssl_context.verify_mode)})
        assert ssl_context.check_hostname and ssl_context.verify_mode == ssl.CERT_REQUIRED
        return stream

    def forbidden(*args, **kwargs):
        pytest.fail("A real network/DNS boundary was reached")

    original_transport = httpx.AsyncHTTPTransport.handle_async_request

    async def observe_transport(self, transport_request):
        net.requests.append(transport_request)
        return await original_transport(self, transport_request)

    monkeypatch.setattr(asyncio.BaseEventLoop, "getaddrinfo", resolve)
    monkeypatch.setattr(AsyncIOBackend, "connect_tcp", classmethod(connect))
    monkeypatch.setattr(TLSStream, "wrap", classmethod(tls))
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket.socket, "connect_ex", forbidden)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", observe_transport)
    yield net
    trace_dir = os.environ.get("R541_TRACE_DIR")
    if trace_dir:
        name = re.sub(r"[^a-zA-Z0-9_.-]", "_", request.node.nodeid)
        Path(trace_dir, name + ".json").write_text(json.dumps(net.events, indent=2) + "\n")


async def test_rebinding_uses_admitted_address_before_connect(network):
    """A second private DNS outcome must never reach the connect boundary."""
    network.rebind = True
    refusal = None
    try:
        async with checked_response("https://flip.example/document") as response:
            assert str(response.url) == "https://flip.example/document"
            assert await response.aread() == b"OK"
    except UrlPolicyError as exc:
        refusal = str(exc)
    connects = [e["address"] for e in network.events if e["event"] == "connect"]
    assert connects == [PUBLIC], f"Unadmitted contact {connects}; later refusal={refusal}"
    assert len([e for e in network.events if e["event"] == "resolve"]) == 1
    assert next(e for e in network.events if e["event"] == "tls")["hostname"] == "flip.example"
    assert "Host: flip.example\r\n" in next(e for e in network.events if e["event"] == "request_write")["request"]


async def test_unicode_origin_uses_httpx_ascii_host_for_admission(network, monkeypatch):
    """Distinct IDNA spellings must use one DNS, connect, Host and TLS identity."""
    logical_host = "xn--fa-hia.example"
    addresses = {"fass.example": PUBLIC, logical_host: "93.184.216.35"}
    original_resolve = network.resolve

    async def resolve(host, port):
        name = host.decode("ascii") if isinstance(host, bytes) else host
        network.answers = [addresses[name.encode("idna").decode("ascii")]]
        return await original_resolve(host, port)

    monkeypatch.setattr(network, "resolve", resolve)
    async with checked_response(
        "https://faß.example/document", allowed_hosts={"faß.example"},
    ) as response:
        assert str(response.url) == f"https://{logical_host}/document"
        assert await response.aread() == b"OK"
    assert [e["address"] for e in network.events if e["event"] == "connect"] == [addresses[logical_host]]
    assert [e["hostname"] for e in network.events if e["event"] == "resolve"] == [logical_host]
    assert next(e for e in network.events if e["event"] == "tls")["hostname"] == logical_host
    assert f"Host: {logical_host}\r\n" in next(e for e in network.events if e["event"] == "request_write")["request"]
    assert all(stream.closed for stream in network.sockets)


async def test_mixed_dns_refuses_before_connect(network):
    """One forbidden answer rejects the complete snapshot before contact."""
    network.answers = [PUBLIC, "10.0.0.1"]
    with pytest.raises(UrlPolicyError, match="blocked IP"):
        async with checked_response("https://mixed.example/file"):
            pytest.fail("Mixed DNS accepted")
    assert not network.sockets
    assert not any(e["event"] == "connect" for e in network.events)


async def test_public_ipv6_fallback_uses_only_admitted_addresses(network):
    """A refused public IPv6 address falls back to the admitted public IPv4."""
    network.answers = [PUBLIC_V6, PUBLIC, PUBLIC]
    network.fail_addresses = {PUBLIC_V6}
    async with checked_response("https://multi.example:8443/file") as response:
        assert str(response.url) == "https://multi.example:8443/file"
    assert [e["address"] for e in network.events if e["event"] == "connect"] == [PUBLIC_V6, PUBLIC]
    assert len([e for e in network.events if e["event"] == "resolve"]) == 1
    written = next(e for e in network.events if e["event"] == "request_write")
    assert "Host: multi.example:8443\r\n" in written["request"]


@pytest.mark.parametrize("url,host", [("https://v6.example/file", "v6.example"),
                                      (f"https://[{PUBLIC_V6}]:8443/file", f"[{PUBLIC_V6}]:8443")])
async def test_ipv6_connection_preserves_original_authority(network, url, host):
    """IPv6 selection retains the logical URL and original Host authority."""
    network.answers = [PUBLIC_V6]
    async with checked_response(url) as response:
        assert str(response.url) == url
    assert [e["address"] for e in network.events if e["event"] == "connect"] == [PUBLIC_V6]
    assert f"Host: {host}\r\n" in next(e for e in network.events if e["event"] == "request_write")["request"]


async def test_redirects_keep_logical_origin_cookies_and_isolate_shared_ip(network):
    """Relative/cross-host redirects keep their origin even when sharing one IP."""
    network.responses = [(302, {"Location": "/next", "Set-Cookie": "session=test; Path=/"}, b""),
                         (302, {"Location": "https://second.example/final"}, b""),
                         (200, {}, b"OK")]
    async with checked_response("https://first.example/start") as response:
        assert str(response.url) == "https://second.example/final"
        assert await response.aread() == b"OK"
    assert [e["hostname"] for e in network.events if e["event"] == "resolve"] == ["first.example", "first.example", "second.example"]
    assert [e["hostname"] for e in network.events if e["event"] == "tls"] == ["first.example", "first.example", "second.example"]
    writes = [e["request"] for e in network.events if e["event"] == "request_write"]
    assert "GET /next HTTP/1.1" in writes[1] and "Cookie: session=test\r\n" in writes[1]
    assert "Host: second.example\r\n" in writes[2] and "Cookie:" not in writes[2]
    assert len(network.sockets) == 3 and all(stream.closed for stream in network.sockets)


async def test_redirect_allowlist_refuses_before_next_dns(network):
    """The next hostname is checked before resolution or transport contact."""
    network.responses = [(302, {"Location": "https://blocked.example/file"}, b"")]
    with pytest.raises(UrlPolicyError, match="allowlist"):
        async with checked_response("https://allowed.example/file", allowed_hosts={"allowed.example"}):
            pytest.fail("Redirect allowlist bypassed")
    assert len([e for e in network.events if e["event"] == "resolve"]) == 1
    assert len(network.sockets) == 1 and network.sockets[0].closed


async def test_cancelled_write_restores_logical_url_and_closes_socket(network):
    """Cancellation keeps original identity and joins the transport's cleanup."""
    network.block_write = True

    async def consume():
        async with checked_response("https://cancel.example/file"):
            pytest.fail("Cancelled response yielded")

    task = asyncio.create_task(consume())
    await asyncio.wait_for(network.write_started.wait(), timeout=2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, timeout=2)
    assert str(network.requests[0].url) == "https://cancel.example/file"
    assert network.sockets[0].closed


@pytest.mark.parametrize("peer", [None, ("10.0.0.1", 443)])
async def test_postresponse_peer_guard_still_fails_closed(network, peer):
    """Pinned addressing does not bypass absent or forbidden actual-peer metadata."""
    network.override_peer, network.peer = True, peer
    with pytest.raises(UrlPolicyError):
        async with checked_response("https://peer.example/file"):
            pytest.fail("Unverified peer yielded")
    assert network.sockets[0].closed


@pytest.mark.parametrize("origin_host", ["faß.example", "xn--fa-hia.example"])
@pytest.mark.parametrize("allowed_host", ["faß.example", "xn--fa-hia.example"])
async def test_unicode_allowlist_preserves_same_origin_redirect(network, origin_host, allowed_host):
    """GIVEN equivalent host spellings WHEN redirecting relatively THEN retain one admitted origin."""
    logical_host = "xn--fa-hia.example"
    network.responses = [
        (302, {"Location": "/next", "Set-Cookie": "session=unicode; Path=/"}, b""),
        (200, {}, b"OK"),
    ]
    async with checked_response(
        f"https://{origin_host}/document", allowed_hosts={allowed_host},
    ) as response:
        assert str(response.url) == f"https://{logical_host}/next"
        assert await response.aread() == b"OK"
    assert [e["hostname"] for e in network.events if e["event"] == "resolve"] == [logical_host] * 2
    assert [e["address"] for e in network.events if e["event"] == "connect"] == [PUBLIC] * 2
    assert [e["hostname"] for e in network.events if e["event"] == "tls"] == [logical_host] * 2
    writes = [e["request"] for e in network.events if e["event"] == "request_write"]
    assert all(f"Host: {logical_host}\r\n" in value for value in writes)
    assert "GET /next HTTP/1.1" in writes[1] and "Cookie: session=unicode\r\n" in writes[1]
    assert [str(request.url) for request in network.requests] == [
        f"https://{logical_host}/document", f"https://{logical_host}/next",
    ]
    assert len(network.sockets) == 2 and all(stream.closed for stream in network.sockets)


@pytest.mark.parametrize("hop", ["initial", "redirect"])
async def test_unicode_allowlist_refuses_distinct_host_before_dns(network, hop):
    """GIVEN a distinct IDNA2003 spelling WHEN admitting either hop THEN refuse before its DNS."""
    if hop == "initial":
        url = "https://fass.example/document"
        expected_hosts = []
    else:
        url = "https://faß.example/document"
        network.responses = [(302, {"Location": "https://fass.example/next"}, b"")]
        expected_hosts = ["xn--fa-hia.example"]
    with pytest.raises(UrlPolicyError, match="allowlist"):
        async with checked_response(url, allowed_hosts={"faß.example"}):
            pytest.fail("Distinct host admitted")
    assert [e["hostname"] for e in network.events if e["event"] == "resolve"] == expected_hosts
    assert len([e for e in network.events if e["event"] == "connect"]) == len(expected_hosts)
    assert len([e for e in network.events if e["event"] == "request_write"]) == len(expected_hosts)
    assert len(network.sockets) == len(expected_hosts) and all(stream.closed for stream in network.sockets)
