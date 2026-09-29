"""Mocked SDK tests for terminal evidence, isolation, and bounded execution."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest
from claude_agent_sdk import ResultMessage

from video_agent_mcp.sdk_runner import run_agent_query, run_parallel_queries
from video_agent_mcp.types import AgentResult

from .conftest import MockAsyncIterator, make_mock_message

SAMPLE_TSX = 'import React from "react";\nexport const HookScene = () => null;'


def result_message(**overrides) -> ResultMessage:
    """Build the SDK terminal message required to prove completion."""
    fields = dict(
        subtype="success", duration_ms=1, duration_api_ms=1,
        is_error=False, num_turns=1, session_id="test-session", result=SAMPLE_TSX,
    )
    fields.update(overrides)
    return ResultMessage(**fields)


async def test_query_success_and_isolation(monkeypatch):
    """Single and parallel paths isolate child tools, MCP servers, and nesting guard."""
    monkeypatch.setenv("CLAUDECODE", "parent-session")
    messages = [make_mock_message(SAMPLE_TSX), result_message()]
    with patch(
        "video_agent_mcp.sdk_runner.claude_agent_sdk.query",
        return_value=MockAsyncIterator(messages),
    ) as sdk_query:
        result = await run_agent_query("Generate a scene")
    assert result.success is True
    assert result.text == SAMPLE_TSX
    assert result.error is None
    options = sdk_query.call_args.kwargs["options"]
    assert options.tools == []
    assert options.strict_mcp_config is True
    assert options.setting_sources == []
    assert options.env == {"CLAUDECODE": ""}
    assert os.environ["CLAUDECODE"] == "parent-session"


async def test_query_timeout():
    """Timeout cancels an incomplete stream and reports failure."""
    async def slow_generator():
        yield make_mock_message("starting...")
        await asyncio.sleep(10)
    with patch(
        "video_agent_mcp.sdk_runner.claude_agent_sdk.query", return_value=slow_generator(),
    ):
        result = await run_agent_query("Generate a scene", timeout=0)
    assert result.success is False
    assert "timed out" in result.error


async def test_query_empty_response():
    """An empty terminal result cannot prove a generated scene."""
    with patch(
        "video_agent_mcp.sdk_runner.claude_agent_sdk.query",
        return_value=MockAsyncIterator([result_message(result="")]),
    ):
        result = await run_agent_query("Generate a scene")
    assert result.success is False
    assert "Empty response" in result.error


async def test_query_missing_terminal_result():
    """Partial text is not accepted after a truncated stream."""
    with patch(
        "video_agent_mcp.sdk_runner.claude_agent_sdk.query",
        return_value=MockAsyncIterator([make_mock_message(SAMPLE_TSX)]),
    ):
        result = await run_agent_query("Generate a scene")
    assert result.success is False
    assert "terminal result" in result.error
    assert result.text == ""


@pytest.mark.parametrize("terminal", [
    result_message(subtype="error_max_turns", is_error=True, errors=["turn budget exhausted"]),
    result_message(is_error=True, result="billing error"),
    result_message(terminal_reason="aborted_streaming"),
])
async def test_terminal_error_overrides_partial_text(terminal):
    """SDK errors must not become successful files because prior text was nonempty."""
    with patch(
        "video_agent_mcp.sdk_runner.claude_agent_sdk.query",
        return_value=MockAsyncIterator([make_mock_message(SAMPLE_TSX), terminal]),
    ):
        result = await run_agent_query("Generate a scene")
    assert result.success is False
    assert result.error
    assert result.text == ""


async def test_query_exception():
    """SDK exceptions become failed results instead of escaping the tool boundary."""
    with patch(
        "video_agent_mcp.sdk_runner.claude_agent_sdk.query",
        side_effect=RuntimeError("SDK connection failed"),
    ):
        result = await run_agent_query("Generate a scene")
    assert result.success is False
    assert "SDK connection failed" in result.error


async def test_parallel_concurrency_and_order():
    """Concurrency is bounded while results retain their input order."""
    active = 0
    maximum = 0
    async def counting_query(prompt):
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0.01)
        active -= 1
        return AgentResult(text=prompt, success=True, duration_seconds=0.01)
    with patch("video_agent_mcp.sdk_runner.run_agent_query", side_effect=counting_query):
        results = await run_parallel_queries(
            [{"prompt": f"Scene {i}"} for i in range(5)], concurrency=2,
        )
    assert maximum == 2
    assert [r.text for r in results] == [f"Scene {i}" for i in range(5)]


@pytest.mark.parametrize("concurrency", [0, -1, 11])
async def test_parallel_invalid_concurrency(concurrency):
    """Reject invalid limits instead of deadlocking the semaphore."""
    with pytest.raises(ValueError, match="between 1 and 10"):
        await run_parallel_queries([{"prompt": "test"}], concurrency=concurrency)


async def test_parallel_partial_failure():
    """Keep failed scenes in the output denominator."""
    async def query(prompt):
        return AgentResult(
            text=prompt if prompt != "fail" else "", success=prompt != "fail",
            error="Failed" if prompt == "fail" else None, duration_seconds=0.1,
        )
    with patch("video_agent_mcp.sdk_runner.run_agent_query", side_effect=query):
        results = await run_parallel_queries([{"prompt": "ok"}, {"prompt": "fail"}])
    assert [r.success for r in results] == [True, False]
