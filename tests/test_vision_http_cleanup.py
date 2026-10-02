"""Owned transport cleanup survives deadline expiry and repeated cancellation."""

import asyncio

import httpx
import pytest

from tests.test_vision_http import network as network
from video_research_mcp import vision_http


async def test_expired_tls_deadline_still_joins_slow_raw_stream_close(network, monkeypatch):
    """GIVEN unfinished TLS WHEN its deadline expires THEN raw close has its own grace."""
    stream = network["stream"]

    async def unfinished_tls(**kwargs):
        await asyncio.Event().wait()

    async def slow_close():
        await asyncio.sleep(0.03)
        stream.closed = True

    monkeypatch.setattr(stream, "start_tls", unfinished_tls)
    monkeypatch.setattr(stream, "aclose", slow_close)
    monkeypatch.setattr(vision_http, "EXCHANGE_TIMEOUT_SECONDS", 0.02)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(vision_http.exchange("https://vision.example", headers={},
                                                   content=b"owned", method="POST"), 1)
    assert stream.closed
    assert not stream.writes


async def test_failed_client_close_still_closes_captured_raw_stream(network, monkeypatch):
    """GIVEN a primary TLS timeout WHEN client close fails THEN raw cleanup still runs."""
    stream = network["stream"]
    client_closes = []

    async def timeout_tls(**kwargs):
        raise TimeoutError("primary TLS timeout")

    async def failed_client_close(self):
        client_closes.append(self)
        raise RuntimeError("private cleanup diagnostics")

    monkeypatch.setattr(stream, "start_tls", timeout_tls)
    monkeypatch.setattr(httpx.AsyncClient, "aclose", failed_client_close)
    with pytest.raises(TimeoutError, match="^primary TLS timeout$"):
        await vision_http.exchange("https://vision.example", headers={}, content=b"", method="GET")
    assert len(client_closes) == 1 and stream.closed
    assert not stream.writes


@pytest.mark.parametrize("primary", ["cancel", "timeout"])
async def test_repeated_caller_cancellation_joins_cleanup_and_preserves_primary(network, monkeypatch, primary):
    """GIVEN pending cleanup WHEN callers cancel repeatedly THEN cleanup remains joined."""
    stream = network["stream"]
    tls_started, close_started, release_close = asyncio.Event(), asyncio.Event(), asyncio.Event()
    baseline = asyncio.all_tasks()

    async def unfinished_tls(**kwargs):
        tls_started.set()
        await asyncio.Event().wait()

    async def held_close():
        close_started.set()
        await release_close.wait()
        stream.closed = True

    monkeypatch.setattr(stream, "start_tls", unfinished_tls)
    monkeypatch.setattr(stream, "aclose", held_close)
    monkeypatch.setattr(vision_http, "EXCHANGE_TIMEOUT_SECONDS", 0.02 if primary == "timeout" else 1)
    task = asyncio.create_task(vision_http.exchange("https://vision.example", headers={}, content=b"", method="GET"))
    await asyncio.wait_for(tls_started.wait(), 1)
    if primary == "cancel":
        task.cancel("primary cancellation")
    await asyncio.wait_for(close_started.wait(), 1)
    for _ in range(3):
        task.cancel("later cancellation")
        await asyncio.sleep(0)
    release_close.set()
    try:
        async with asyncio.timeout(1):
            with pytest.raises(asyncio.CancelledError if primary == "cancel" else TimeoutError) as caught:
                await task
        if primary == "cancel":
            assert caught.value.args == ("primary cancellation",)
        assert stream.closed
        assert not [pending for pending in asyncio.all_tasks() - baseline if not pending.done()]
    finally:
        release_close.set()
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_cleanup_deadline_cancels_and_joins_stalled_close_without_masking_primary(network, monkeypatch):
    """GIVEN unresponsive cooperative close THEN grace expires without a detached task."""
    stream = network["stream"]
    close_finished = asyncio.Event()
    baseline = asyncio.all_tasks()

    async def timeout_tls(**kwargs):
        raise TimeoutError("primary TLS timeout")

    async def stalled_close():
        try:
            await asyncio.Event().wait()
        finally:
            close_finished.set()

    monkeypatch.setattr(stream, "start_tls", timeout_tls)
    monkeypatch.setattr(stream, "aclose", stalled_close)
    monkeypatch.setattr(vision_http, "CLEANUP_TIMEOUT_SECONDS", 0.03, raising=False)
    with pytest.raises(TimeoutError, match="^primary TLS timeout$"):
        await asyncio.wait_for(vision_http.exchange("https://vision.example", headers={}, content=b"", method="GET"), 0.3)
    assert close_finished.is_set()
    assert not [pending for pending in asyncio.all_tasks() - baseline if not pending.done()]


async def test_cleanup_failure_cannot_return_a_successful_exchange(network, monkeypatch):
    """GIVEN a valid response WHEN client cleanup fails THEN success is withheld."""
    async def failed_client_close(self):
        raise RuntimeError("private cleanup diagnostics")

    monkeypatch.setattr(httpx.AsyncClient, "aclose", failed_client_close)
    with pytest.raises(RuntimeError, match="^Vision HTTP cleanup failed$"):
        await vision_http.exchange("https://vision.example", headers={}, content=b"", method="GET")
    assert network["stream"].closed
