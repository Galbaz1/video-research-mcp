"""Regression checks for retained security safeguards and fenced document staging."""

from __future__ import annotations

import asyncio
import os
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import Client

from video_research_mcp.batch_discovery import discover_files
from video_research_mcp.content_file_data import read_content_bytes
from video_research_mcp.tools.content import content_analyze, content_server
from video_research_mcp.tools.content_batch import content_batch_analyze
from video_research_mcp.tools.video import video_batch_analyze


@pytest.fixture
def fenced_tree(tmp_path, monkeypatch, clean_config):
    """Separate allowed content from files outside the configured boundary."""
    allowed = tmp_path / "allowed"
    docs = allowed / "docs"
    docs.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    for suffix in ("txt", "mp4"):
        (docs / f"inside.{suffix}").write_bytes(b"inside")
        (outside / f"secret.{suffix}").write_bytes(b"outside secret")
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(allowed))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(allowed / "cache"))
    return allowed, docs, outside


@pytest.mark.parametrize("mode", ["compare", "individual", "video"])
@pytest.mark.parametrize("escape", ["parent", "symlink"])
async def test_discovery_rejects_escape_before_provider(fenced_tree, mode, escape, mock_gemini_client):
    """GIVEN a glob/root escape WHEN batching THEN reject before a provider or job call."""
    _allowed, docs, outside = fenced_tree
    suffix = "mp4" if mode == "video" else "txt"
    pattern = f"../../outside/*.{suffix}"
    if escape == "symlink":
        (docs / f"link.{suffix}").symlink_to(outside / f"secret.{suffix}")
        pattern = f"*.{suffix}"
    with patch("video_research_mcp.tools.video_batch.execute_batch", new_callable=AsyncMock) as submit:
        if mode == "video":
            result = await video_batch_analyze(directory=str(docs), glob_pattern=pattern)
        else:
            result = await content_batch_analyze(directory=str(docs), glob_pattern=pattern, mode=mode)
        assert result["category"] == "PERMISSION_DENIED"
        assert "items" not in result
        submit.assert_not_awaited()
    mock_gemini_client["generate"].assert_not_awaited()
    mock_gemini_client["generate_structured"].assert_not_awaited()


@pytest.mark.parametrize("batch", [False, True])
async def test_content_byte_ceiling_prevents_inference(tmp_path, monkeypatch, clean_config, mock_gemini_client, batch):
    """GIVEN an oversized local file WHEN analyzing THEN reject without model calls."""
    monkeypatch.setenv("DOC_MAX_DOWNLOAD_BYTES", "8")
    source = tmp_path / "large.txt"
    source.write_bytes(b"x" * 9)
    if batch:
        result = await content_batch_analyze(file_paths=[str(source)])
    else:
        result = await content_analyze(file_path=str(source))
    assert "exceeds" in result["error"]
    assert result["retryable"] is False
    mock_gemini_client["generate"].assert_not_awaited()
    mock_gemini_client["generate_structured"].assert_not_awaited()


def test_special_files_rejected_without_blocking(tmp_path):
    """GIVEN a FIFO WHEN reading content THEN fail before opening the stream."""
    source = tmp_path / "pipe.txt"
    os.mkfifo(source)
    with pytest.raises(PermissionError, match="regular files"):
        read_content_bytes(source, 100)


def test_checked_reader_preserves_exact_limit_bytes(tmp_path, monkeypatch, clean_config):
    """GIVEN a file at the configured limit WHEN reading THEN retain every byte."""
    monkeypatch.setenv("DOC_MAX_DOWNLOAD_BYTES", "8")
    source = tmp_path / "exact.txt"
    source.write_bytes(b"12345678")
    assert read_content_bytes(source, 8) == b"12345678"


async def test_aggregate_compare_budget_before_reading(tmp_path, monkeypatch, clean_config, mock_gemini_client):
    """GIVEN small files over the aggregate budget WHEN comparing THEN read none."""
    monkeypatch.setenv("DOC_MAX_DOWNLOAD_BYTES", "8")
    paths = [tmp_path / "one.txt", tmp_path / "two.txt"]
    for path in paths:
        path.write_bytes(b"12345")
    with patch("video_research_mcp.tools.content_batch.read_content_bytes") as reader:
        result = await content_batch_analyze(file_paths=[str(p) for p in paths])
        reader.assert_not_called()
    assert "exceeds" in result["error"]
    assert result["retryable"] is False
    mock_gemini_client["generate_structured"].assert_not_awaited()


@pytest.mark.parametrize("pattern", ["*.txt", "**/*.txt"])
def test_scan_budget_counts_nonmatches(tmp_path, monkeypatch, pattern):
    """GIVEN many excluded entries WHEN scanning THEN bound actual entry visits."""
    monkeypatch.setattr("video_research_mcp.batch_discovery.MAX_SCAN_ENTRIES", 8)
    for i in range(9):
        (tmp_path / f"ignored-{i}.bin").touch()
    with pytest.raises(ValueError, match="scan exceeds"):
        discover_files(tmp_path, pattern, {".txt": "text/plain"}, 20)


@pytest.mark.parametrize("pattern", ["*", "*.txt", "**/*.txt", "nested/*.txt", "n?sted/[ab].txt", "**", "*/"])
def test_supported_globs_match_pathlib(tmp_path, pattern):
    """GIVEN ordinary and recursive globs WHEN scanning THEN preserve file selection."""
    (tmp_path / "nested").mkdir()
    for name in ("top.txt", "top.csv", "nested/a.txt", "nested/b.txt", "nested/no.bin"):
        (tmp_path / name).touch()
    matches = tmp_path.rglob("*.txt") if pattern == "**" else tmp_path.glob(pattern)
    expected = sorted(p for p in matches if p.is_file() and p.suffix == ".txt")
    assert discover_files(tmp_path, pattern, {".txt": "text/plain"}, 20) == expected


async def test_explicit_batch_retains_max_files_subset(tmp_path, mock_gemini_client):
    """GIVEN more explicit files than max_files WHEN batching THEN retain the published subset behavior."""
    paths = [tmp_path / "one.txt", tmp_path / "two.txt"]
    for path in paths:
        path.touch()
    with patch("video_research_mcp.tools.content_batch._analyze_parts", new_callable=AsyncMock, return_value={}) as analyze:
        result = await content_batch_analyze(file_paths=[str(p) for p in paths], max_files=1)
        assert result["total_files"] == 1
        analyze.assert_awaited_once()


@pytest.mark.parametrize("tool,args", [
    ("content_analyze", {"text": "x" * 200_001, "output_schema": {"type": "object"}}),
    ("content_extract", {"content": "x" * 200_001, "schema": {"type": "object"}}),
])
async def test_published_text_contract_remains_unchanged(tool, args, mock_gemini_client):
    """GIVEN text accepted by the frozen schema WHEN calling through MCP THEN retain compatibility."""
    mock_gemini_client["generate"].return_value = "{}"
    async with Client(content_server) as client:
        result = await client.call_tool(tool, args, raise_on_error=False)
        assert not result.is_error
    mock_gemini_client["generate"].assert_awaited_once()
    mock_gemini_client["generate_structured"].assert_not_awaited()


async def test_url_document_stages_inside_fence(fenced_tree):
    """GIVEN a local fence WHEN preparing a downloaded source THEN hash and upload inside it."""
    from video_research_mcp.tools.research_document_file import _prepare_all_documents_with_issues
    from video_research_mcp.tools.video_file import _file_content_hash
    allowed, _docs, _outside = fenced_tree
    directories = []

    async def download(_url, directory):
        directories.append(directory)
        source = directory / "paper.pdf"
        source.write_bytes(b"%PDF prepared")
        return source

    async def upload(path, _mime, content_hash):
        assert path.is_relative_to(allowed)
        assert content_hash == _file_content_hash(path)
        return "https://provider.invalid/files/test"

    with (
        patch("video_research_mcp.tools.research_document_file._download_document", side_effect=download),
        patch("video_research_mcp.tools.research_document_file._upload_large_file", side_effect=upload),
    ):
        prepared, issues = await _prepare_all_documents_with_issues(None, ["https://example.com/paper.pdf"])
    assert len(prepared) == 1 and issues == []
    assert all(not p.exists() for p in directories)


@pytest.mark.parametrize("module", ["research_document", "research_document_file"])
async def test_document_fanout_bound(module):
    """GIVEN more awaitables than the bound WHEN executing THEN retain order without exceeding it."""
    from importlib import import_module
    gather = import_module(f"video_research_mcp.tools.{module}")._gather_bounded
    active = peak = 0

    async def work(index):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return index

    assert await gather([work(i) for i in range(8)], 2) == list(range(8))
    assert peak == 2
