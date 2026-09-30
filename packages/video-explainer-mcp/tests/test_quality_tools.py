"""Tests for quality improvement tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastmcp.exceptions import ValidationError

from video_explainer_mcp.tools.quality import (
    explainer_factcheck,
    explainer_feedback,
    explainer_refine,
    quality_server,
)

pytestmark = pytest.mark.unit


def _mock_result(stdout: str = "OK"):
    mock = AsyncMock()
    mock.stdout = stdout
    mock.stderr = ""
    mock.returncode = 0
    mock.duration_seconds = 1.0
    return mock


class TestExplainerRefine:
    """Tests for explainer_refine tool."""

    async def test_refine_script(self, monkeypatch, tmp_path):
        """Forward the configured projects directory to the refine subparser."""
        projects = tmp_path / "custom-projects"
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(projects))
        tool = await quality_server.get_tool("explainer_refine")
        with patch("video_explainer_mcp.tools.quality.run_cli", return_value=_mock_result()) as mock_cli:
            reply = await tool.run({"project_id": "test", "phase": "script"})
        result = reply.structured_content
        assert result["phase"] == "script"
        assert result["success"] is True
        mock_cli.assert_awaited_once_with(
            "refine", "test", "--phase", "script", "--projects-dir", str(projects)
        )

    @pytest.mark.parametrize("phase", ["narration", "scenes"])
    async def test_unsupported_refine_phase(self, phase):
        """Reject unsupported phases at the MCP boundary before the CLI runs."""
        tool = await quality_server.get_tool("explainer_refine")
        with patch("video_explainer_mcp.tools.quality.run_cli") as mock_cli:
            with pytest.raises(ValidationError):
                await tool.run({"project_id": "test", "phase": phase})
        mock_cli.assert_not_awaited()

    async def test_refine_error(self, monkeypatch):
        """Returns tool error on CLI failure."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        from video_explainer_mcp.errors import SubprocessError
        with patch(
            "video_explainer_mcp.tools.quality.run_cli",
            side_effect=SubprocessError(["cli"], 1, stderr="fail"),
        ):
            result = await explainer_refine(project_id="test", phase="script")
        assert "error" in result


class TestExplainerFeedback:
    """Tests for explainer_feedback tool."""

    async def test_add_feedback(self, monkeypatch):
        """Adds feedback text."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.quality.run_cli", return_value=_mock_result()) as mock_cli:
            result = await explainer_feedback(
                project_id="test", feedback="Make the intro shorter"
            )
        assert result["success"] is True
        assert "Make the intro shorter" in mock_cli.call_args.args


class TestExplainerFactcheck:
    """Tests for explainer_factcheck tool."""

    async def test_factcheck(self, monkeypatch):
        """Runs fact-check."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        with patch("video_explainer_mcp.tools.quality.run_cli", return_value=_mock_result("2 claims verified")):
            result = await explainer_factcheck(project_id="test")
        assert result["success"] is True

    async def test_factcheck_error(self, monkeypatch):
        """Handles factcheck failure."""
        monkeypatch.setenv("EXPLAINER_PATH", "/fake")
        from video_explainer_mcp.errors import SubprocessError
        with patch(
            "video_explainer_mcp.tools.quality.run_cli",
            side_effect=SubprocessError(["cli"], 1, stderr="no script found"),
        ):
            result = await explainer_factcheck(project_id="test")
        assert "error" in result
