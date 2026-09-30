"""Credential-bearing exchanges exercised through the installed HTTP transport."""

import asyncio
import logging
import socket
import ssl

import httpcore
import pytest


class NetworkStream(httpcore.AsyncNetworkStream):
    """An owned HTTP/1.1 socket substitute; no live sockets or TLS are opened."""

    def __init__(self, response=b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\n{}", peer=("8.8.8.8", 443)):
        self.response = response
        self.peer = peer
        self.writes = []
        self.tls = []
        self.closed = False
        self.block_read = False
        self.read_started = asyncio.Event()

    async def read(self, max_bytes, timeout=None):
        self.read_started.set()
        if self.block_read:
            await asyncio.Event().wait()
        result, self.response = self.response[:max_bytes], self.response[max_bytes:]
        return result

    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    async def aclose(self):
        self.closed = True

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls.append((server_hostname, ssl_context.check_hostname, ssl_context.verify_mode))
        return self

    def get_extra_info(self, info):
        return self.peer if info == "server_addr" else None


@pytest.fixture
async def network(monkeypatch):
    """Patch the socket/DNS boundaries while retaining httpx/httpcore/h11 execution."""
    from httpcore._backends.auto import AutoBackend

    state = {"answers": ["8.8.8.8"], "connections": [], "dns": [], "stream": NetworkStream()}

    async def resolve(host, port, **kwargs):
        state["dns"].append((host, port))
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in state["answers"]]

    async def connect(self, host, port, **kwargs):
        state["connections"].append((host, port))
        return state["stream"]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr(AutoBackend, "connect_tcp", connect)
    return state


async def test_public_destination_is_pinned_with_original_host_and_tls_name(network, monkeypatch):
    """GIVEN public DNS WHEN posting credentials THEN connect only to the attested literal."""
    from video_research_mcp.vision_http import exchange

    network["stream"].peer = ("8.8.8.8", 8443)
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:9")
    result = await exchange("https://vision.example:8443/v1/chat?mode=json", headers={
        "Authorization": "Bearer test-secret", "Content-Type": "application/json", "Host": "wrong.example",
    }, content=b'{"messages":[]}', method="POST")
    assert result == (200, b"{}")
    assert network["dns"] == [("vision.example", 8443)]
    assert network["connections"] == [("8.8.8.8", 8443)]
    wire = b"".join(network["stream"].writes)
    assert wire.startswith(b"POST /v1/chat?mode=json HTTP/1.1\r\n")
    assert b"Host: vision.example:8443\r\n" in wire
    assert b"Authorization: Bearer test-secret\r\n" in wire
    assert b"wrong.example" not in wire
    assert network["stream"].tls == [("vision.example", True, ssl.CERT_REQUIRED)]
    assert network["stream"].closed


@pytest.mark.parametrize("answers", [[], ["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"],
                                    ["8.8.8.8", "::1"], ["8.8.8.8", "224.0.0.1"]])
async def test_all_dns_answers_must_be_public_before_credentials_are_sent(network, answers):
    from video_research_mcp.vision_http import exchange

    network["answers"] = answers
    with pytest.raises(ValueError, match="only public"):
        await exchange("https://vision.example/api", headers={"Authorization": "Bearer private"},
                       content=b"sensitive-image", method="POST")
    assert not network["connections"]
    assert not network["stream"].writes


@pytest.mark.parametrize("peer", [None, ("127.0.0.1", 443), ("8.8.4.4", 443),
                                 ("8.8.8.8", 8443), ("8.8.8.8", "443"), ("invalid", 443)])
async def test_connected_peer_must_match_pinned_ip_and_port_before_tls_or_write(network, peer):
    from video_research_mcp.vision_http import exchange

    network["stream"].peer = peer
    with pytest.raises(PermissionError, match="peer could not be verified"):
        await exchange("https://vision.example/api", headers={"Authorization": "Bearer private"},
                       content=b"sensitive-image", method="POST")
    assert not network["stream"].writes
    assert not network["stream"].tls
    assert network["stream"].closed


@pytest.mark.parametrize("url,local", [
    ("http://vision.example", False), ("https://user:pass@vision.example", False),
    ("https://vision.example/#fragment", False), ("https://vision.example/#", False),
    ("https://vision.example/\r\nx", False), ("https://vision.example/\x7f", False),
    ("file:///tmp/image", False), ("https://127.0.0.1", False),
    ("http://localhost:9000", True), ("http://127.0.0.2:9000", True),
    ("http://192.168.0.1:9000", True), ("https://vision.example", True),
])
async def test_unsafe_origins_are_rejected_without_dns_or_connection(network, url, local):
    from video_research_mcp.vision_http import exchange

    with pytest.raises(ValueError):
        await exchange(url, headers={"Authorization": "Bearer private"}, content=b"x", method="POST", local=local)
    assert not network["dns"]
    assert not network["connections"]


@pytest.mark.parametrize("host,port,scheme", [("127.0.0.1", 9000, "http"), ("::1", 9443, "https")])
async def test_explicit_literal_loopback_is_supported_without_dns(network, host, port, scheme):
    from video_research_mcp.vision_http import exchange

    network["stream"].peer = (host, port)
    authority = f"[{host}]" if ":" in host else host
    assert await exchange(f"{scheme}://{authority}:{port}/api", headers={}, content=b"", method="GET", local=True) == (200, b"{}")
    assert not network["dns"]
    assert network["connections"] == [(host, port)]
    wire = b"".join(network["stream"].writes)
    assert f"Host: {authority}:{port}\r\n".encode() in wire
    assert bool(network["stream"].tls) == (scheme == "https")


async def test_ipv6_public_literal_is_pinned_without_dns(network):
    from video_research_mcp.vision_http import exchange

    ip = "2606:4700:4700::1111"
    network["stream"].peer = (ip, 443, 0, 0)
    assert await exchange(f"https://[{ip}]/", headers={}, content=b"", method="GET") == (200, b"{}")
    assert network["connections"] == [(ip, 443)]
    assert not network["dns"]


async def test_redirect_is_returned_once_without_forwarding_credentials(network):
    from video_research_mcp.vision_http import exchange

    network["stream"].response = b"HTTP/1.1 307 Temporary Redirect\r\nLocation: http://127.0.0.1/private\r\nContent-Length: 0\r\n\r\n"
    assert await exchange("https://vision.example/api", headers={"Authorization": "Bearer private"},
                          content=b"sensitive-image", method="POST") == (307, b"")
    assert network["connections"] == [("8.8.8.8", 443)]
    assert b"".join(network["stream"].writes).count(b"Authorization:") == 1
    assert network["stream"].closed


async def test_oss_multipart_bytes_and_policy_get_are_not_reinterpreted(network):
    from video_research_mcp.vision_http import exchange

    body = b"--owned\r\nContent-Disposition: form-data; name=\"file\"\r\n\r\n\x00\xff\r\n--owned--\r\n"
    assert await exchange("https://oss.example/temporary", headers={"Content-Type": "multipart/form-data; boundary=owned"},
                          content=body, method="POST") == (200, b"{}")
    assert body in b"".join(network["stream"].writes)
    network["stream"] = NetworkStream()
    assert await exchange("https://policy.example/policy?model=vision", headers={"Authorization": "Bearer private"},
                          content=b"", method="GET") == (200, b"{}")
    assert b"".join(network["stream"].writes).startswith(b"GET /policy?model=vision HTTP/1.1")


async def test_request_body_and_headers_limit_is_checked_before_dns(network, monkeypatch):
    from video_research_mcp import vision_http

    monkeypatch.setattr(vision_http, "MAX_REQUEST_BYTES", 512)
    for body, headers in [(b"x" * 513, {}), (b"", {"Authorization": "x" * 513})]:
        with pytest.raises(ValueError, match="request exceeds"):
            await vision_http.exchange("https://vision.example", headers=headers, content=body, method="POST")
    assert not network["dns"]
    assert not network["connections"]


@pytest.mark.parametrize("headers", [{"Authorization": "private\r\nInjected: yes"},
                                      {"Injected\n": "yes"}, {"Content-Length": "999"},
                                      {"Transfer-Encoding": "chunked"}])
async def test_header_injection_and_framing_override_are_rejected_before_dns(network, headers):
    from video_research_mcp.vision_http import exchange

    with pytest.raises(ValueError):
        await exchange("https://vision.example", headers=headers, content=b"image", method="POST")
    assert not network["connections"]
    assert not network["dns"]


@pytest.mark.parametrize("response", [
    b"HTTP/1.1 200 OK\r\nContent-Length: 262145\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n40001\r\n" + b"x" * 262145 + b"\r\n0\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\nContent-Length: 2\r\n\r\n{}",
])
async def test_response_caps_and_compression_fail_closed_and_close(network, response):
    from video_research_mcp.vision_http import exchange

    network["stream"].response = response
    with pytest.raises(ValueError):
        await exchange("https://vision.example", headers={}, content=b"", method="GET")
    assert network["stream"].closed


async def test_exact_raw_response_ceiling_succeeds(network):
    from video_research_mcp.vision_http import MAX_RESPONSE_BYTES, exchange

    body = b"x" * MAX_RESPONSE_BYTES
    network["stream"].response = f"HTTP/1.1 200 OK\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
    assert await exchange("https://vision.example", headers={}, content=b"", method="GET") == (200, body)
    assert network["stream"].closed


async def test_overall_deadline_closes_blocked_response_without_retry(network, monkeypatch):
    from video_research_mcp import vision_http

    monkeypatch.setattr(vision_http, "EXCHANGE_TIMEOUT_SECONDS", 0.02)
    network["stream"].block_read = True
    with pytest.raises(TimeoutError):
        await vision_http.exchange("https://vision.example", headers={}, content=b"", method="GET")
    assert network["stream"].closed
    assert len(network["connections"]) == 1


async def test_cancellation_closes_owned_stream_and_keeps_cancelled_outcome(network):
    from video_research_mcp.vision_http import exchange

    network["stream"].block_read = True
    task = asyncio.create_task(exchange("https://vision.example", headers={}, content=b"", method="GET"))
    await asyncio.wait_for(network["stream"].read_started.wait(), 1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert network["stream"].closed
    assert len(network["connections"]) == 1


async def test_transmission_failure_is_generic_and_does_not_retry(network, monkeypatch):
    from video_research_mcp.vision_http import exchange

    async def fail(buffer, timeout=None):
        raise httpcore.WriteError("private-upstream-body Bearer test-secret")

    monkeypatch.setattr(network["stream"], "write", fail)
    with pytest.raises(RuntimeError, match="^Vision HTTP exchange failed$") as caught:
        await exchange("https://vision.example", headers={"Authorization": "Bearer test-secret"}, content=b"image", method="POST")
    assert "private" not in str(caught.value)
    assert len(network["connections"]) == 1
    assert network["stream"].closed


async def test_overall_deadline_also_bounds_dns_without_transmission(network, monkeypatch):
    from video_research_mcp import vision_http

    async def blocked_dns(*args, **kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", blocked_dns)
    monkeypatch.setattr(vision_http, "EXCHANGE_TIMEOUT_SECONDS", 0.02)
    with pytest.raises(TimeoutError):
        await vision_http.exchange("https://vision.example", headers={"Authorization": "Bearer private"}, content=b"image", method="POST")
    assert not network["connections"]
    assert not network["stream"].writes


async def test_tls_failure_closes_raw_owned_stream_without_sending_credentials(network, monkeypatch):
    from video_research_mcp.vision_http import exchange

    async def fail(**kwargs):
        raise httpcore.ConnectError("private certificate response")

    monkeypatch.setattr(network["stream"], "start_tls", fail)
    with pytest.raises(RuntimeError, match="^Vision HTTP exchange failed$"):
        await exchange("https://vision.example", headers={"Authorization": "Bearer private"}, content=b"image", method="POST")
    assert network["stream"].closed
    assert not network["stream"].writes
    assert len(network["connections"]) == 1


async def test_503_is_returned_without_retry_or_error_body_logging(network, caplog):
    from video_research_mcp.vision_http import exchange

    body = b"private upstream body"
    network["stream"].response = f"HTTP/1.1 503 Unavailable\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body
    assert await exchange("https://vision.example", headers={"Authorization": "Bearer private-key"}, content=b"private-image", method="POST") == (503, body)
    assert len(network["connections"]) == 1
    assert all(secret not in caplog.text for secret in ("private-key", "private-image", body.decode()))


async def test_request_headers_and_body_each_have_one_transmission(network):
    from video_research_mcp.vision_http import exchange

    await exchange("https://vision.example", headers={}, content=b"owned-unique-body", method="POST")
    wire = b"".join(network["stream"].writes)
    assert wire.count(b"POST /") == 1
    assert wire.count(b"owned-unique-body") == 1
    assert wire.count(b"Content-Length: 17\r\n") == 1


async def test_debug_logging_cannot_expose_exchange_credentials_or_upstream_values(network, caplog):
    from video_research_mcp.vision_http import exchange

    caplog.set_level(logging.DEBUG)
    network["stream"].response = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nSet-Cookie: owned-response-secret\r\n\r\n{}"
    assert await exchange("https://vision.example/?token=owned-query-secret", headers={"Authorization": "Bearer owned-key-secret"},
                          content=b"owned-source-secret", method="POST") == (200, b"{}")
    for secret in ("owned-response-secret", "owned-query-secret", "owned-key-secret", "owned-source-secret"):
        assert secret not in caplog.text


async def test_private_logging_guard_preserves_other_tasks_and_restores_filters(network, caplog):
    from video_research_mcp.vision_http import exchange

    caplog.set_level(logging.DEBUG)
    names = ("httpx", "httpcore.connection", "httpcore.http11", "httpcore.http2")
    before = {name: list(logging.getLogger(name).filters) for name in names}
    first = network["stream"]
    first.block_read = True
    task = asyncio.create_task(exchange("https://vision.example/?token=first-private", headers={}, content=b"", method="GET"))
    await asyncio.wait_for(first.read_started.wait(), 1)
    network["stream"] = NetworkStream()
    assert await exchange("https://vision.example/?token=second-private", headers={}, content=b"", method="GET") == (200, b"{}")
    logging.getLogger("httpx").debug("other task logging remains available")
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert "other task logging remains available" in caplog.text
    assert "first-private" not in caplog.text and "second-private" not in caplog.text
    assert all(logging.getLogger(name).filters == before[name] for name in names)
    assert first.closed and network["stream"].closed
