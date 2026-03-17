"""Shared test fixtures for video-research-mcp."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def unwrap_tool(tool: Any) -> Any:
    """Extract the raw coroutine from a FastMCP FunctionTool, if wrapped.

    FastMCP 2.x wraps @server.tool functions in FunctionTool (not callable).
    FastMCP 3.x preserves the original function. This helper works with both.
    """
    return getattr(tool, "fn", tool)


@pytest.fixture(autouse=True, scope="session")
def _unwrap_fastmcp_tools():
    """Patch tool modules so FunctionTool objects become directly callable.

    FastMCP 2.x wraps @server.tool in FunctionTool (not callable); 3.x
    preserves the function. This fixture unwraps at the module level so
    tests can ``await tool_func(...)`` regardless of FastMCP version.
    """
    import importlib
    import pkgutil

    import video_research_mcp.tools as tools_pkg

    modules = []
    for info in pkgutil.walk_packages(tools_pkg.__path__, tools_pkg.__name__ + "."):
        try:
            modules.append(importlib.import_module(info.name))
        except Exception:
            pass

    for mod in modules:
        for name in list(vars(mod)):
            obj = getattr(mod, name, None)
            if obj is not None and hasattr(obj, "fn") and not callable(obj):
                setattr(mod, name, obj.fn)


@pytest.fixture(autouse=True)
def _set_dummy_api_key(monkeypatch):
    """Ensure tests never hit real Gemini API."""
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")


@pytest.fixture(autouse=True)
def _disable_tracing(monkeypatch):
    """Disable MLflow tracing in all tests to avoid real tracking-server calls.

    The ``test_tracing.py`` module patches the tracing module directly
    and does not rely on this fixture.
    """
    monkeypatch.setenv("GEMINI_TRACING_ENABLED", "false")


@pytest.fixture(autouse=True)
def _isolate_dotenv(tmp_path, monkeypatch):
    """Prevent tests from loading the user's real ~/.config/video-research-mcp/.env."""
    monkeypatch.setattr(
        "video_research_mcp.dotenv.DEFAULT_ENV_PATH",
        tmp_path / "nonexistent.env",
    )


@pytest.fixture(autouse=True)
def _disable_graph_extraction():
    """Prevent graph extraction from interfering with tool-level assertions.

    The extra GeminiClient.generate() call from extract_and_store_graph()
    breaks call-count and call-args assertions in tool tests.
    Patches both the source module and the re-export in __init__.
    """
    mock = AsyncMock()
    with (
        patch("video_research_mcp.weaviate_store.graph.extract_and_store_graph", mock),
        patch("video_research_mcp.weaviate_store.extract_and_store_graph", mock),
    ):
        yield


@pytest.fixture(autouse=True)
def _isolate_upload_cache(tmp_path, monkeypatch):
    """Point upload cache to a temp directory so tests never share filesystem state."""
    cache_dir = tmp_path / "upload_cache"
    cache_dir.mkdir()
    monkeypatch.setattr(
        "video_research_mcp.tools.video_file._upload_cache_dir",
        lambda: cache_dir,
    )


@pytest.fixture()
def mock_gemini_client():
    """Patch GeminiClient.get(), .generate(), and .generate_structured() for unit tests."""
    with (
        patch("video_research_mcp.client.GeminiClient.get") as mock_get,
        patch(
            "video_research_mcp.client.GeminiClient.generate", new_callable=AsyncMock
        ) as mock_gen,
        patch(
            "video_research_mcp.client.GeminiClient.generate_structured",
            new_callable=AsyncMock,
        ) as mock_structured,
        patch(
            "video_research_mcp.client.GeminiClient.generate_json_validated",
            new_callable=AsyncMock,
        ) as mock_json_validated,
    ):
        client = MagicMock()
        mock_get.return_value = client
        yield {
            "get": mock_get,
            "generate": mock_gen,
            "generate_structured": mock_structured,
            "generate_json_validated": mock_json_validated,
            "client": client,
        }


@pytest.fixture()
def clean_config():
    """Reset the config singleton between tests."""
    import video_research_mcp.config as cfg_mod

    cfg_mod._config = None
    yield
    cfg_mod._config = None


@pytest.fixture()
def mock_weaviate_client():
    """Patch WeaviateClient for unit tests — provides mock client + collection."""
    mock_client = MagicMock()
    mock_collection = MagicMock()
    mock_client.collections.get.return_value = mock_collection
    mock_client.collections.list_all.return_value = {}
    mock_client.is_ready.return_value = True

    # Mock data operations
    mock_collection.data.insert.return_value = "test-uuid-1234"
    mock_collection.data.update.return_value = None
    mock_collection.query.hybrid.return_value = MagicMock(objects=[])
    mock_collection.query.near_object.return_value = MagicMock(objects=[])
    mock_collection.query.fetch_objects.return_value = MagicMock(objects=[])
    mock_collection.aggregate.over_all.return_value = MagicMock(total_count=0)

    with (
        patch("video_research_mcp.weaviate_client._client", mock_client),
        patch("video_research_mcp.weaviate_client._schema_ensured", True),
        patch("video_research_mcp.weaviate_client.WeaviateClient.get", return_value=mock_client),
        patch("video_research_mcp.weaviate_client.WeaviateClient.is_available", return_value=True),
    ):
        yield {
            "client": mock_client,
            "collection": mock_collection,
        }


@pytest.fixture()
def mock_weaviate_disabled(monkeypatch, clean_config):
    """Ensure Weaviate is disabled — empty WEAVIATE_URL."""
    monkeypatch.delenv("WEAVIATE_URL", raising=False)
    monkeypatch.delenv("WEAVIATE_API_KEY", raising=False)
