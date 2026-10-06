"""Controlled loopback transport and native metadata boundary regressions."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
import ipaddress
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from video_research_mcp import vision_http, vision_ollama, vision_provider
from video_research_mcp.models.vision import VisionBackend, VisionRequest


@asynccontextmanager
async def response_server(response):
    """Join the one controlled connection, including caller refusal and EOF."""
    observed = {"connections": 0, "requests": [], "closed": 0, "tasks": []}

    async def respond(reader, writer):
        observed["tasks"].append(asyncio.current_task())
        observed["connections"] += 1
        try:
            async with asyncio.timeout(3):
                head = await reader.readuntil(b"\r\n\r\n")
                length = next(int(line.split(b":", 1)[1]) for line in head.split(b"\r\n")
                              if line.lower().startswith(b"content-length:"))
                observed["requests"].append(await reader.readexactly(length))
                writer.write(response)
                await writer.drain()
        except (ConnectionError, asyncio.IncompleteReadError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except ConnectionError:
                pass
            observed["closed"] += 1

    server = await asyncio.start_server(respond, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/api/chat", observed
    finally:
        server.close()
        await server.wait_closed()
        async with asyncio.timeout(4):
            await asyncio.gather(*observed["tasks"])


@pytest.mark.parametrize("case,limit", [
    ("success", 4096), ("headers", 4096), ("close_body", 131072),
    ("body_with_headers", 131072),
])
async def test_real_guarded_exchange(case, limit, monkeypatch):
    """The real httpx/httpcore connection uses the bound before HTTP parsing."""
    responses = {
        "success": b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nok",
        "headers": b"HTTP/1.1 200 OK\r\nX-Owned: " + b"h" * 5000 + b"\r\n\r\n",
        "close_body": b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n" + b"b" * 131073,
        "body_with_headers": b"HTTP/1.1 200 OK\r\nContent-Length: 131072\r\n\r\n" + b"b" * 131072,
    }
    streams = []
    original = vision_http._LimitedStream.read

    async def measured(stream, *args, **kwargs):
        if stream not in streams:
            streams.append(stream)
        return await original(stream, *args, **kwargs)

    monkeypatch.setattr(vision_http._LimitedStream, "read", measured)
    async with response_server(responses[case]) as (url, observed):
        async with asyncio.timeout(5):
            if case == "success":
                assert await vision_http.exchange(url, headers={}, content=b"[]", method="POST",
                                                  local=True, response_limit=limit) == (200, b"ok")
            else:
                with pytest.raises(ValueError, match="byte limit"):
                    await vision_http.exchange(url, headers={}, content=b"[]", method="POST",
                                               local=True, response_limit=limit)
    assert observed["connections"] == observed["closed"] == len(streams) == 1
    assert observed["requests"] == [b"[]"]
    assert streams[0].received <= limit + 1


async def test_receive_guard_required_before_transmission():
    """A private transport API change cannot silently remove the receive guard."""
    stream = SimpleNamespace(get_extra_info=lambda key: ("127.0.0.1", 9000))
    streams = []
    trace, attested = vision_http._peer_trace(ipaddress.ip_address("127.0.0.1"), 9000,
                                            streams, require_limited=True)
    with pytest.raises(PermissionError, match="receive limit"):
        await trace("connection.connect_tcp.complete", {"return_value": stream})
    assert streams == [stream] and not attested()
    with pytest.raises(PermissionError, match="attestation"):
        await trace("http11.send_request_headers.started", {})


@pytest.mark.parametrize("field,value", [
    ("done", {"untrusted": "secret"}), ("done_reason", {"untrusted": "secret"}),
    ("done_reason", float("nan")), ("thinking", "secret" * 1000),
])
def test_native_metadata_never_returns_unvalidated_values(field, value):
    """Rejected model fields cannot leak text, objects or nonfinite numbers."""
    body = {"model": "owned", "done": True, "done_reason": "stop",
            "message": {"role": "assistant", "content": "red"}}
    (body["message"] if field == "thinking" else body)[field] = value
    call = {}
    with pytest.raises(ValueError):
        vision_ollama.result_answer(body, "owned", 128, call)
    encoded = json.dumps(call, allow_nan=False)
    assert "secret" not in encoded and "untrusted" not in encoded


async def test_snapshot_growth_refused_before_payload_read(monkeypatch):
    """Recheck actual snapshot size after the original admission stat."""
    request = VisionRequest(sources=[{"file_path": "/owned/image.png", "expected_source_sha256": "0" * 64}],
                            instruction="owned")
    reader = SimpleNamespace(fileno=lambda: 1)

    @asynccontextmanager
    async def owned_snapshot(*args):
        yield SimpleNamespace(size=786433)

    from contextlib import nullcontext
    monkeypatch.setattr(vision_ollama, "checked_path", lambda path: path)
    monkeypatch.setattr(vision_ollama, "_open_regular", lambda path: nullcontext(reader))
    monkeypatch.setattr(vision_ollama.os, "fstat", lambda fd: SimpleNamespace(st_size=411))
    monkeypatch.setattr(vision_ollama, "snapshot", owned_snapshot)
    read = AsyncMock(side_effect=AssertionError("payload read before size check"))
    monkeypatch.setattr(vision_ollama, "read_payload", read)
    async with AsyncExitStack() as stack:
        with pytest.raises(ValueError, match="PNG exceeds"):
            await vision_ollama.prepare_png(request, stack)
    read.assert_not_called()


def test_compatible_binding_retains_profile_identity():
    """Default compatible receipts keep the pre-protocol profile representation."""
    profile = VisionBackend(base_url="http://127.0.0.1:9000/v1", model="owned", local=True,
                            capabilities=["images", "structured_json"])
    request = VisionRequest(sources=[{"file_path": "/owned/image.png", "expected_source_sha256": "0" * 64}],
                            instruction="owned")
    binding, digest = vision_provider.backend_binding(request, profile, profile.model, "", None,
                                                     {}, "owned", [], [])
    assert "protocol" not in binding["profile"]
    assert binding["profile"] == profile.model_dump(mode="json", exclude={"protocol"})
    assert digest == "69dad05ee60ee85962b8a9c011c849f47c063ba82c568495c4732f3ec22a3290"
