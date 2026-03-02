"""Policy-inheritance regression tests for URL/path-taking tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import video_research_mcp.tools.content as content_mod
from tests.conftest import unwrap_tool
from video_research_mcp.tools.content_batch import _resolve_files
from video_research_mcp.tools.research_document_file import (
    _download_document,
    _prepare_all_documents_with_issues,
)
from video_research_mcp.tools.video_file import _validate_video_path

content_analyze = unwrap_tool(content_mod.content_analyze)


class TestPolicyInheritance:
    async def test_content_analyze_url_calls_validate_url(self):
        """URL analysis must invoke shared URL policy validation helper."""
        with (
            patch(
                "video_research_mcp.tools.content.validate_url",
                new_callable=AsyncMock,
            ) as mock_validate,
            patch(
                "video_research_mcp.tools.content._analyze_url",
                new_callable=AsyncMock,
                return_value={"title": "ok"},
            ),
            patch(
                "video_research_mcp.weaviate_store.store_content_analysis",
                new_callable=AsyncMock,
            ),
        ):
            result = await content_analyze(url="https://example.com")

        assert result["title"] == "ok"
        mock_validate.assert_awaited_once_with("https://example.com")

    async def test_content_analyze_file_path_calls_local_path_policy(self, tmp_path):
        """File-path analysis must invoke shared local path policy helper."""
        f = tmp_path / "doc.txt"
        f.write_text("hello")

        with (
            patch(
                "video_research_mcp.tools.content.enforce_local_access_root",
                side_effect=lambda p: p,
            ) as mock_enforce,
            patch(
                "video_research_mcp.tools.content._analyze_parts",
                new_callable=AsyncMock,
                return_value={"title": "ok"},
            ),
            patch(
                "video_research_mcp.weaviate_store.store_content_analysis",
                new_callable=AsyncMock,
            ),
        ):
            result = await content_analyze(file_path=str(f))

        assert result["title"] == "ok"
        assert mock_enforce.call_count == 1

    def test_content_batch_resolve_files_calls_local_path_policy(self, tmp_path):
        """Batch content directory scan must pass through local path policy helper."""
        (tmp_path / "doc.pdf").write_bytes(b"%PDF fake")

        with patch(
            "video_research_mcp.tools.content_batch.enforce_local_access_root",
            side_effect=lambda p: p,
        ) as mock_enforce:
            files = _resolve_files(str(tmp_path), None, "*", 20)

        assert len(files) == 1
        assert mock_enforce.call_count == 1

    def test_content_batch_file_paths_calls_local_path_policy(self, tmp_path):
        """Explicit file-path mode must enforce local path policy per file."""
        f1 = tmp_path / "doc1.pdf"
        f2 = tmp_path / "doc2.txt"
        f1.write_bytes(b"%PDF fake")
        f2.write_text("notes")

        with patch(
            "video_research_mcp.tools.content_batch.enforce_local_access_root",
            side_effect=lambda p: p,
        ) as mock_enforce:
            files = _resolve_files(None, [str(f1), str(f2)], "*", 20)

        assert len(files) == 2
        assert mock_enforce.call_count == 2

    def test_video_file_validate_path_calls_local_path_policy(self, tmp_path):
        """Video file ingress must pass through shared local path policy helper."""
        video = tmp_path / "clip.mp4"
        video.write_bytes(b"\x00" * 10)

        with patch(
            "video_research_mcp.tools.video_file.enforce_local_access_root",
            side_effect=lambda p: p,
        ) as mock_enforce:
            path, mime = _validate_video_path(str(video))

        assert path == video
        assert mime == "video/mp4"
        assert mock_enforce.call_count == 1

    async def test_research_document_local_paths_call_local_path_policy(self, tmp_path):
        """Document preparation for local files must enforce shared path boundary helper."""
        d1 = tmp_path / "one.pdf"
        d2 = tmp_path / "two.pdf"
        d1.write_bytes(b"%PDF-1.4 one")
        d2.write_bytes(b"%PDF-1.4 two")

        with (
            patch(
                "video_research_mcp.tools.research_document_file.enforce_local_access_root",
                side_effect=lambda p: p,
            ) as mock_enforce,
            patch(
                "video_research_mcp.tools.research_document_file._prepare_document",
                new_callable=AsyncMock,
                side_effect=[("gs://one", "h1"), ("gs://two", "h2")],
            ),
        ):
            prepared, issues = await _prepare_all_documents_with_issues(
                file_paths=[str(d1), str(d2)],
                urls=None,
            )

        assert issues == []
        assert len(prepared) == 2
        assert mock_enforce.call_count == 2

    async def test_research_document_url_download_calls_download_checked(
        self, tmp_path, clean_config,
    ):
        """Document URL ingress must route through shared checked downloader."""
        with patch(
            "video_research_mcp.tools.research_document_file.download_checked",
            new_callable=AsyncMock,
            return_value=tmp_path / "paper.pdf",
        ) as mock_download_checked:
            await _download_document("https://example.com/paper.pdf", tmp_path)

        mock_download_checked.assert_awaited_once()
        assert mock_download_checked.call_args.args[0] == "https://example.com/paper.pdf"
