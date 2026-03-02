"""Tests for content_batch_analyze tool."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, patch

from tests.conftest import unwrap_tool
from video_research_mcp.tools.content_batch import (
    content_batch_analyze,
    _resolve_files,
)

content_batch_analyze = unwrap_tool(content_batch_analyze)


@pytest.fixture()
def sample_files(tmp_path):
    """Create sample content files for testing."""
    (tmp_path / "doc1.pdf").write_bytes(b"%PDF-1.4 fake pdf content")
    (tmp_path / "doc2.pdf").write_bytes(b"%PDF-1.4 another pdf")
    (tmp_path / "notes.txt").write_text("Some notes here")
    (tmp_path / "image.png").write_bytes(b"not a content file")
    return tmp_path


class TestResolveFiles:
    async def test_directory_scanning(self, sample_files):
        """GIVEN a directory with mixed files WHEN resolving THEN only supported extensions returned."""
        files = _resolve_files(str(sample_files), None, "*", 20)
        extensions = {f.suffix for f in files}
        assert ".png" not in extensions
        assert len(files) == 3  # 2 PDFs + 1 txt

    async def test_explicit_file_paths(self, sample_files):
        """GIVEN explicit file paths WHEN resolving THEN all valid paths returned."""
        paths = [str(sample_files / "doc1.pdf"), str(sample_files / "notes.txt")]
        files = _resolve_files(None, paths, "*", 20)
        assert len(files) == 2

    async def test_no_source_provided(self):
        """GIVEN neither directory nor file_paths WHEN resolving THEN ValueError raised."""
        with pytest.raises(ValueError, match="Provide either"):
            _resolve_files(None, None, "*", 20)

    async def test_both_sources_provided(self, sample_files):
        """GIVEN both directory and file_paths WHEN resolving THEN ValueError raised."""
        with pytest.raises(ValueError, match="not both"):
            _resolve_files(str(sample_files), [str(sample_files / "doc1.pdf")], "*", 20)

    async def test_file_not_found(self):
        """GIVEN a non-existent file path WHEN resolving THEN FileNotFoundError raised."""
        with pytest.raises(FileNotFoundError):
            _resolve_files(None, ["/nonexistent/file.pdf"], "*", 20)

    async def test_max_files_limit(self, tmp_path):
        """GIVEN more files than max_files WHEN resolving THEN capped at limit."""
        for i in range(10):
            (tmp_path / f"doc{i}.pdf").write_bytes(b"%PDF fake")
        files = _resolve_files(str(tmp_path), None, "*", 3)
        assert len(files) == 3

    async def test_no_files_found(self, tmp_path):
        """GIVEN an empty directory WHEN resolving THEN empty list returned."""
        files = _resolve_files(str(tmp_path), None, "*", 20)
        assert files == []

    async def test_unsupported_extensions_filtered(self, sample_files):
        """GIVEN files with unsupported extensions WHEN resolving THEN they are excluded."""
        files = _resolve_files(None, [str(sample_files / "image.png")], "*", 20)
        assert len(files) == 0

    async def test_glob_pattern_filtering(self, sample_files):
        """GIVEN a glob pattern WHEN resolving THEN only matching files returned."""
        files = _resolve_files(str(sample_files), None, "*.pdf", 20)
        assert len(files) == 2
        assert all(f.suffix == ".pdf" for f in files)

    async def test_directory_outside_local_access_root(
        self, sample_files, monkeypatch, clean_config,
    ):
        """Configured local access root blocks directory scans outside allowlist."""
        allowed_root = sample_files / "allowed"
        allowed_root.mkdir()
        monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(allowed_root))

        with pytest.raises(PermissionError, match="outside LOCAL_FILE_ACCESS_ROOT"):
            _resolve_files(str(sample_files), None, "*", 20)


class TestContentBatchAnalyze:
    @patch("video_research_mcp.tools.content_batch.store_content_analysis", new_callable=AsyncMock)
    async def test_compare_mode(self, mock_store, sample_files, mock_gemini_client):
        """GIVEN multiple files WHEN compare mode THEN single Gemini call with all files."""
        mock_gemini_client["generate"].return_value = '{"summary": "comparison result"}'
        result = await content_batch_analyze(
            instruction="Compare these documents",
            directory=str(sample_files),
            mode="compare",
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )
        assert result["mode"] == "compare"
        assert result["comparison"] == {"summary": "comparison result"}
        assert result["total_files"] == 3

    @patch("video_research_mcp.tools.content_batch.store_content_analysis", new_callable=AsyncMock)
    async def test_individual_mode(self, mock_store, sample_files, mock_gemini_client):
        """GIVEN multiple files WHEN individual mode THEN separate Gemini call per file."""
        from video_research_mcp.models.content import ContentResult
        mock_gemini_client["generate_structured"].return_value = ContentResult(
            title="Test", summary="A summary"
        )
        result = await content_batch_analyze(
            instruction="Summarize each document",
            directory=str(sample_files),
            mode="individual",
        )
        assert result["mode"] == "individual"
        assert result["total_files"] == 3
        assert result["successful"] == 3

    async def test_no_source_returns_error(self, mock_gemini_client):
        """GIVEN no directory or file_paths WHEN calling tool THEN error dict returned."""
        result = await content_batch_analyze(instruction="test")
        assert "error" in result

    async def test_empty_directory(self, tmp_path, mock_gemini_client):
        """GIVEN an empty directory WHEN calling tool THEN empty result returned."""
        result = await content_batch_analyze(
            instruction="test", directory=str(tmp_path),
        )
        assert result["total_files"] == 0

    @patch("video_research_mcp.tools.content_batch.store_content_analysis", new_callable=AsyncMock)
    async def test_custom_output_schema(self, mock_store, sample_files, mock_gemini_client):
        """GIVEN a custom output_schema WHEN compare mode THEN schema passed to Gemini."""
        schema = {"type": "object", "properties": {"findings": {"type": "array"}}}
        mock_gemini_client["generate"].return_value = '{"findings": ["a", "b"]}'
        result = await content_batch_analyze(
            instruction="Extract findings",
            directory=str(sample_files),
            mode="compare",
            output_schema=schema,
        )
        assert result["comparison"] == {"findings": ["a", "b"]}

    @patch("video_research_mcp.tools.content_batch.store_content_analysis", new_callable=AsyncMock)
    async def test_weaviate_store_called(self, mock_store, sample_files, mock_gemini_client):
        """GIVEN successful analysis WHEN tool completes THEN store_content_analysis called."""
        mock_gemini_client["generate"].return_value = '{"summary": "test"}'
        await content_batch_analyze(
            instruction="Summarize",
            directory=str(sample_files),
            mode="compare",
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )
        assert mock_store.call_count > 0

    @patch("video_research_mcp.tools.content_batch.store_content_analysis", new_callable=AsyncMock)
    async def test_file_paths_mode(self, mock_store, sample_files, mock_gemini_client):
        """GIVEN explicit file_paths WHEN compare mode THEN files analyzed."""
        mock_gemini_client["generate"].return_value = '{"summary": "result"}'
        paths = [str(sample_files / "doc1.pdf"), str(sample_files / "notes.txt")]
        result = await content_batch_analyze(
            instruction="Compare",
            file_paths=paths,
            mode="compare",
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )
        assert result["total_files"] == 2
        assert result["comparison"] == {"summary": "result"}

    async def test_nonexistent_directory(self, mock_gemini_client):
        """GIVEN a non-existent directory WHEN calling tool THEN error dict returned."""
        result = await content_batch_analyze(
            instruction="test", directory="/nonexistent/path",
        )
        assert "error" in result
