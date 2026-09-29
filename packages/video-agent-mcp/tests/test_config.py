"""Tests for config.py path resolution and environment validation."""

from __future__ import annotations

import pytest

from video_agent_mcp.config import ServerConfig


class TestServerConfigPaths:
    """Tests for ServerConfig.get_project_dir path safety checks."""

    def test_get_project_dir_resolves_existing_project(self, tmp_path):
        """GIVEN a valid project_id WHEN resolving THEN returns project directory."""
        explainer_root = tmp_path / "projects"
        project_dir = explainer_root / "demo-project"
        project_dir.mkdir(parents=True)

        config = ServerConfig(projects_path=str(explainer_root))

        resolved = config.get_project_dir("demo-project")

        assert resolved == project_dir.resolve()

    def test_get_project_dir_rejects_parent_traversal(self, tmp_path):
        """GIVEN ../ traversal WHEN resolving THEN raises FileNotFoundError."""
        explainer_root = tmp_path / "projects"
        explainer_root.mkdir()
        outside_dir = tmp_path / "outside-project"
        outside_dir.mkdir()

        config = ServerConfig(projects_path=str(explainer_root))

        with pytest.raises(FileNotFoundError, match="must be under"):
            config.get_project_dir("../outside-project")

    def test_get_project_dir_rejects_absolute_paths(self, tmp_path):
        """GIVEN an absolute path WHEN resolving THEN raises FileNotFoundError."""
        explainer_root = tmp_path / "projects"
        explainer_root.mkdir()
        outside_dir = tmp_path / "outside-project"
        outside_dir.mkdir()

        config = ServerConfig(projects_path=str(explainer_root))

        with pytest.raises(FileNotFoundError, match="must be under"):
            config.get_project_dir(str(outside_dir.resolve()))

    def test_get_project_dir_rejects_empty_id(self, tmp_path):
        """GIVEN an empty project_id WHEN resolving THEN raises FileNotFoundError."""
        explainer_root = tmp_path / "projects"
        explainer_root.mkdir()
        config = ServerConfig(projects_path=str(explainer_root))

        with pytest.raises(FileNotFoundError, match="project_id cannot be empty"):
            config.get_project_dir("  ")


    def test_checkout_defaults_to_projects_directory(self, tmp_path):
        """Shared EXPLAINER_PATH means the upstream checkout for both servers."""
        project_dir = tmp_path / "projects" / "demo"
        project_dir.mkdir(parents=True)
        assert ServerConfig(explainer_path=str(tmp_path)).get_project_dir("demo") == project_dir

    def test_current_default_model(self, monkeypatch):
        """The configured default uses the current official Sonnet model ID."""
        monkeypatch.delenv("AGENT_MODEL")
        assert ServerConfig.from_env().agent_model == "claude-sonnet-5-5"

    def test_max_turns_must_be_positive(self):
        """Reject invalid turn budgets at the config boundary."""
        with pytest.raises(ValueError, match="greater than or equal to 1"):
            ServerConfig(agent_max_turns=0)
