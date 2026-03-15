"""Tests for research_document_file helpers -- URL normalization and download."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from video_research_mcp.tools.research_document_file import (
    _prepare_all_documents_with_issues,
    _normalize_document_url,
    _download_document,
)


class TestNormalizeDocumentUrl:
    """Tests for _normalize_document_url."""

    def test_arxiv_abs_to_pdf(self):
        """GIVEN arxiv.org/abs URL WHEN normalized THEN converts to /pdf/.pdf."""
        result = _normalize_document_url("https://arxiv.org/abs/2401.12345")
        assert result == "https://arxiv.org/pdf/2401.12345.pdf"

    def test_arxiv_abs_with_version(self):
        """GIVEN arxiv.org/abs URL with version WHEN normalized THEN preserves version."""
        result = _normalize_document_url("https://arxiv.org/abs/2401.12345v2")
        assert result == "https://arxiv.org/pdf/2401.12345v2.pdf"

    def test_arxiv_pdf_without_extension(self):
        """GIVEN arxiv.org/pdf URL without .pdf WHEN normalized THEN adds .pdf."""
        result = _normalize_document_url("https://arxiv.org/pdf/2401.12345")
        assert result == "https://arxiv.org/pdf/2401.12345.pdf"

    def test_arxiv_pdf_with_version_no_extension(self):
        """GIVEN arxiv.org/pdf/XXXX.XXXXXv1 WHEN normalized THEN adds .pdf."""
        result = _normalize_document_url("https://arxiv.org/pdf/2401.12345v1")
        assert result == "https://arxiv.org/pdf/2401.12345v1.pdf"

    def test_non_arxiv_url_unchanged(self):
        """GIVEN non-arXiv URL WHEN normalized THEN returned unchanged."""
        url = "https://example.com/paper.pdf"
        assert _normalize_document_url(url) == url

    def test_http_arxiv_also_normalized(self):
        """GIVEN http:// arXiv URL WHEN normalized THEN still converts."""
        result = _normalize_document_url("http://arxiv.org/abs/2401.12345")
        assert result == "https://arxiv.org/pdf/2401.12345.pdf"

    def test_arxiv_abs_trailing_slash(self):
        """GIVEN arXiv URL with trailing slash WHEN normalized THEN still converts."""
        result = _normalize_document_url("https://arxiv.org/abs/2401.12345/")
        assert result == "https://arxiv.org/pdf/2401.12345.pdf"

    def test_arxiv_abs_with_query_params(self):
        """GIVEN arXiv URL with query params WHEN normalized THEN still converts."""
        result = _normalize_document_url("https://arxiv.org/abs/2401.12345?context=stat")
        assert result == "https://arxiv.org/pdf/2401.12345.pdf"

    def test_arxiv_abs_trailing_slash_and_query(self):
        """GIVEN arXiv URL with trailing slash AND query WHEN normalized THEN converts."""
        result = _normalize_document_url("https://arxiv.org/abs/2401.12345v2/?utm=1")
        assert result == "https://arxiv.org/pdf/2401.12345v2.pdf"

    def test_arxiv_pdf_trailing_slash(self):
        """GIVEN arXiv /pdf/ URL with trailing slash WHEN normalized THEN adds .pdf."""
        result = _normalize_document_url("https://arxiv.org/pdf/2401.12345/")
        assert result == "https://arxiv.org/pdf/2401.12345.pdf"


class TestDownloadDocument:
    """Tests for _download_document delegation to download_checked."""

    async def test_normalizes_arxiv_url_before_download(self, tmp_path, clean_config):
        """GIVEN arXiv /abs/ URL WHEN _download_document THEN passes normalized URL to download_checked."""
        with patch("video_research_mcp.tools.research_document_file.download_checked", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = tmp_path / "2401.12345.pdf"
            await _download_document("https://arxiv.org/abs/2401.12345", tmp_path)

            called_url = mock_dl.call_args[0][0]
            assert called_url == "https://arxiv.org/pdf/2401.12345.pdf"

    async def test_passes_non_arxiv_url_unchanged(self, tmp_path, clean_config):
        """GIVEN regular URL WHEN _download_document THEN passes URL unchanged."""
        with patch("video_research_mcp.tools.research_document_file.download_checked", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = tmp_path / "report.pdf"
            await _download_document("https://example.com/report.pdf", tmp_path)

            called_url = mock_dl.call_args[0][0]
            assert called_url == "https://example.com/report.pdf"

    async def test_passes_max_bytes_from_config(self, tmp_path, clean_config):
        """download_checked receives max_bytes from config (default 50MB)."""
        with patch("video_research_mcp.tools.research_document_file.download_checked", new_callable=AsyncMock) as mock_dl:
            mock_dl.return_value = tmp_path / "doc.pdf"
            await _download_document("https://example.com/doc.pdf", tmp_path)

            assert mock_dl.call_args[1]["max_bytes"] == 50 * 1024 * 1024


class TestPrepareAllDocumentsWithIssues:
    """Tests for issue-aware document preparation helper."""

    async def test_collects_download_failures_and_keeps_successes(self, tmp_path):
        """GIVEN one download failure WHEN preparing THEN output includes issue metadata."""
        ok_path = tmp_path / "ok.pdf"

        with (
            patch(
                "video_research_mcp.tools.research_document_file._download_document",
                new_callable=AsyncMock,
            ) as mock_download,
            patch(
                "video_research_mcp.tools.research_document_file._prepare_document",
                new_callable=AsyncMock,
            ) as mock_prepare,
        ):
            mock_download.side_effect = [ok_path, RuntimeError("fetch failed")]
            mock_prepare.return_value = ("gs://ok", "hash-ok")

            prepared, issues = await _prepare_all_documents_with_issues(
                file_paths=None,
                urls=["https://example.com/ok.pdf", "https://example.com/bad.pdf"],
            )

            assert prepared == [("gs://ok", "hash-ok", "https://example.com/ok.pdf")]
            assert issues == [
                {
                    "source": "https://example.com/bad.pdf",
                    "phase": "download",
                    "error_type": "RuntimeError",
                    "error": "fetch failed",
                }
            ]
