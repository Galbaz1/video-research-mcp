"""Shared fixtures for video-agent-mcp tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from claude_agent_sdk import AssistantMessage, TextBlock

from video_agent_mcp.config import reset_config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Ensure clean environment for every test."""
    monkeypatch.setenv("EXPLAINER_PATH", "/tmp/test-explainer")
    monkeypatch.delenv("EXPLAINER_PROJECTS_PATH", raising=False)
    monkeypatch.setattr("video_agent_mcp.dotenv.DEFAULT_ENV_PATH", Path("/nonexistent/test.env"))
    monkeypatch.setenv("AGENT_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("AGENT_CONCURRENCY", "3")
    monkeypatch.setenv("AGENT_TIMEOUT", "60")
    monkeypatch.setenv("AGENT_MAX_TURNS", "1")
    # Ensure CLAUDECODE is not set to avoid nested agent issues
    monkeypatch.delenv("CLAUDECODE", raising=False)
    reset_config()
    yield
    reset_config()


@pytest.fixture
def sample_script() -> dict:
    """Minimal script.json with 3 scenes."""
    return {
        "title": "Test Video",
        "scenes": [
            {
                "scene_id": "scene1_hook",
                "title": "The Hook",
                "scene_type": "hook",
                "duration_seconds": 15,
                "voiceover": "Welcome to our video.",
                "visual_description": "Opening animation",
                "key_elements": ["title card"],
            },
            {
                "scene_id": "scene2_problem",
                "title": "The Big Problem",
                "scene_type": "problem",
                "duration_seconds": 30,
                "voiceover": "Here is the problem we face.",
                "visual_description": "Problem visualization",
                "key_elements": ["error state", "comparison"],
            },
            {
                "scene_id": "scene3_solution",
                "title": "A New Solution",
                "scene_type": "solution",
                "duration_seconds": 25,
                "voiceover": "The solution involves a new approach.",
                "visual_description": "Solution diagram",
                "key_elements": ["architecture", "data flow"],
            },
        ],
    }


@pytest.fixture
def sample_manifest() -> dict:
    """Minimal voiceover manifest with word timestamps."""
    return {
        "scenes": [
            {
                "scene_id": "scene1_hook",
                "duration_seconds": 15,
                "word_timestamps": [
                    {"word": "Welcome", "start_seconds": 0.0, "end_seconds": 0.5},
                    {"word": "to", "start_seconds": 0.5, "end_seconds": 0.6},
                    {"word": "our", "start_seconds": 0.6, "end_seconds": 0.8},
                    {"word": "video", "start_seconds": 0.8, "end_seconds": 1.2},
                ],
            },
        ],
    }


@pytest.fixture
def project_dir(tmp_path, sample_script, sample_manifest) -> Path:
    """Create a temporary project directory with script and manifest."""
    project = tmp_path / "test-project"
    project.mkdir()

    script_dir = project / "script"
    script_dir.mkdir()
    (script_dir / "script.json").write_text(json.dumps(sample_script))

    voiceover_dir = project / "voiceover"
    voiceover_dir.mkdir()
    (voiceover_dir / "manifest.json").write_text(json.dumps(sample_manifest))

    return project


def make_mock_message(text: str) -> AssistantMessage:
    """Create an SDK assistant message with a text block."""
    return AssistantMessage(content=[TextBlock(text)], model="test-model")


class MockAsyncIterator:
    """Async iterator that yields pre-defined messages."""

    def __init__(self, messages: list):
        self._messages = messages
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._messages):
            raise StopAsyncIteration
        msg = self._messages[self._index]
        self._index += 1
        return msg
