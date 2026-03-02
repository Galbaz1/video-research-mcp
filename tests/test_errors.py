"""Tests for structured error categorization and retryability flags."""

from __future__ import annotations

import httpx

from video_research_mcp.errors import make_tool_error


class TestMakeToolError:
    def test_builtin_timeout_maps_to_network_error(self):
        result = make_tool_error(TimeoutError())
        assert result["category"] == "NETWORK_ERROR"
        assert result["retryable"] is True

    def test_httpx_timeout_maps_to_network_error(self):
        result = make_tool_error(httpx.ReadTimeout("read timed out"))
        assert result["category"] == "NETWORK_ERROR"
        assert result["retryable"] is True

    def test_httpx_network_maps_to_network_error(self):
        result = make_tool_error(httpx.ConnectError("connection refused"))
        assert result["category"] == "NETWORK_ERROR"
        assert result["retryable"] is True
