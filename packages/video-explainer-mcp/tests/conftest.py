"""Shared test fixtures for video-explainer-mcp."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

import video_explainer_mcp.config as cfg_mod


@pytest.fixture(autouse=True)
def _clean_config():
    """Reset the config singleton between tests."""
    cfg_mod._config = None
    yield
    cfg_mod._config = None


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch):
    """Prevent tests from loading the user's real .env file."""
    monkeypatch.setattr(
        "video_explainer_mcp.dotenv.DEFAULT_ENV_PATH",
        tmp_path / "nonexistent.env",
    )


@pytest.fixture()
def clean_config():
    """Explicit config reset for tests that need to reference it."""
    cfg_mod._config = None
    yield
    cfg_mod._config = None


@pytest.fixture()
def mock_subprocess():
    """Create a configurable mock async subprocess.

    Returns a factory that produces (process_mock, create_mock) tuples.
    """

    def _factory(returncode: int = 0, stdout: bytes = b"", stderr: bytes = b""):
        proc = AsyncMock()
        proc.returncode = returncode
        proc.pid = 12345
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
        proc.terminate = MagicMock()
        proc.kill = MagicMock()
        return proc

    return _factory


@pytest.fixture()
def mock_project_dir(tmp_path):
    """Create a temporary project directory with standard structure.

    Returns a factory that creates project dirs with optional completed steps.
    """

    def _factory(
        project_id: str = "test-project",
        completed_steps: list[str] | None = None,
    ):
        projects = tmp_path / "projects"
        projects.mkdir(exist_ok=True)
        project = projects / project_id
        project.mkdir()

        if completed_steps:
            for step in completed_steps:
                step_dir = project / step
                step_dir.mkdir()
                if step == "script":
                    (step_dir / "script.json").write_text("{}")
                elif step == "narration":
                    (step_dir / "narrations.json").write_text("{}")
                elif step == "scenes":
                    (step_dir / "scenes.json").write_text("{}")
                elif step == "voiceover":
                    (step_dir / "audio.mp3").write_text("")
                elif step == "storyboard":
                    (step_dir / "storyboard.json").write_text("{}")
                elif step == "input":
                    (step_dir / "content.md").write_text("# Test")

        return project

    return _factory


@pytest.fixture()
def mock_explainer_venv(tmp_path):
    """Create a fake .venv/bin/video-explainer for runner tests."""
    venv_bin = tmp_path / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    script = venv_bin / "video-explainer"
    script.write_text("#!/bin/sh\n")
    script.chmod(0o755)
    return tmp_path


@pytest.fixture(autouse=True)
async def _isolate_jobs(tmp_path, monkeypatch):
    """Keep every test's durable rows away from the user's database."""
    monkeypatch.setenv("VRM_JOB_DB", str(tmp_path / "jobs.sqlite3"))
    import video_explainer_mcp.render_worker as worker

    worker._draining_enabled = True
    yield
    await worker.cancel_background_renders()
