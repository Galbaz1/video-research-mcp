"""Legacy generation cannot inherit upstream mock or retained-output completion."""

from unittest.mock import AsyncMock, patch

from video_explainer_mcp.tools.pipeline import explainer_generate

from .test_pipeline_tools import _mock_cli_result, _setup_project


async def test_full_generation_denies_before_preparation_when_renderer_unavailable(
    tmp_path, monkeypatch
):
    """No billable generation is dispatched after a failed local readiness check."""
    projects = tmp_path / "projects"
    _setup_project(projects / "owned")
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(projects))
    with (
        patch(
            "video_explainer_mcp.tools.pipeline.require_render_ready",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Remotion missing"),
        ) as ready,
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli,
        patch("video_explainer_mcp.tools.pipeline._run_render", new_callable=AsyncMock) as render,
    ):
        result = await explainer_generate("owned")
    assert "Remotion missing" in result["error"]
    ready.assert_awaited_once_with(None)
    cli.assert_not_awaited()
    render.assert_not_awaited()


async def test_from_render_bypasses_full_pipeline_and_uses_fresh_render_gate(tmp_path, monkeypatch):
    """Render-only requests never reach the foreign whole-pipeline skip branch."""
    projects = tmp_path / "projects"
    _setup_project(projects / "owned")
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(projects))
    with (
        patch("video_explainer_mcp.tools.pipeline.require_render_ready", new_callable=AsyncMock),
        patch("video_explainer_mcp.tools.pipeline.run_cli", new_callable=AsyncMock) as cli,
        patch(
            "video_explainer_mcp.tools.pipeline._run_render",
            return_value=(_mock_cli_result(), "/owned/final-720p.mp4"),
        ) as render,
    ):
        result = await explainer_generate("owned", from_step="render")
    cli.assert_not_awaited()
    render.assert_awaited_once_with("owned", "720p", True)
    assert result["output_file"] == "/owned/final-720p.mp4"
    assert result["playability_verified"] is True
    assert result["real_renderer_verified"] is False


async def test_preparation_exit_zero_cannot_hide_render_failure(tmp_path, monkeypatch):
    """A failed qualifier keeps the public generation outcome an error."""
    projects = tmp_path / "projects"
    _setup_project(projects / "owned")
    monkeypatch.setenv("EXPLAINER_PROJECTS_PATH", str(projects))
    with (
        patch("video_explainer_mcp.tools.pipeline.require_render_ready", new_callable=AsyncMock),
        patch("video_explainer_mcp.tools.pipeline.run_cli", return_value=_mock_cli_result()) as cli,
        patch(
            "video_explainer_mcp.tools.pipeline._run_render",
            new_callable=AsyncMock,
            side_effect=ValueError("MP4 decode failed"),
        ),
    ):
        result = await explainer_generate("owned", to_step="render", force=True)
    cli.assert_awaited_once_with("generate", "owned", "--to", "storyboard", "--force", "--mock")
    assert "MP4 decode failed" in result["error"]
    assert "success" not in result
