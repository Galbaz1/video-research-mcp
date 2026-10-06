"""Tests for research_document_file helpers -- URL normalization and download."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

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

    async def test_collects_download_failures_and_keeps_successes(self, tmp_path, monkeypatch, clean_config):
        """GIVEN one download failure WHEN preparing THEN output includes issue metadata."""
        ok_path = tmp_path / "ok.pdf"
        monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))

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

    async def test_cleans_tmp_dir_after_url_preparation(self, tmp_path):
        """Temporary URL download directory is removed after preparation."""
        ok_path = tmp_path / "ok.pdf"
        tmp_dir = tmp_path / "research_doc_tmp"
        tmp_dir.mkdir()

        with (
            patch(
                "video_research_mcp.tools.research_document_file.view_directory",
                return_value=tmp_dir,
            ),
            patch(
                "video_research_mcp.tools.research_document_file._download_document",
                new_callable=AsyncMock,
                return_value=ok_path,
            ),
            patch(
                "video_research_mcp.tools.research_document_file._prepare_document",
                new_callable=AsyncMock,
                return_value=("gs://ok", "hash-ok"),
            ),
            patch(
                "video_research_mcp.tools.research_document_file.shutil.rmtree"
            ) as mock_rmtree,
        ):
            await _prepare_all_documents_with_issues(
                file_paths=None,
                urls=["https://example.com/ok.pdf"],
            )

            mock_rmtree.assert_called_once_with(tmp_dir, True)


@pytest.mark.parametrize("phase", ["download", "upload"])
async def test_diagnostic_redaction_preparation_issues(phase, tmp_path, monkeypatch, caplog):
    """GIVEN credential source/error WHEN preparation fails THEN only diagnostics redact."""
    import video_research_mcp.tools.research_document_file as mod
    from video_research_mcp.models.research_document import DocumentPreparationIssue

    uri = "https://url-user-canary:url-password-canary@documents.example/paper.pdf?token=url-query-canary#url-fragment-canary"
    error = RuntimeError("backend rejected https://error-user-canary:error-password-canary@documents.example/?token=error-query-canary#error-fragment-canary password=error-field-canary")
    directory = tmp_path / "download"
    directory.mkdir()
    path = directory / "paper.pdf"
    download = AsyncMock(side_effect=error if phase == "download" else None, return_value=path)
    prepare = AsyncMock(side_effect=error if phase == "upload" else None)
    monkeypatch.setattr(mod, "view_directory", lambda: directory)
    monkeypatch.setattr(mod, "download_checked", download)
    monkeypatch.setattr(mod, "_prepare_document", prepare)
    prepared, issues = await mod._prepare_all_documents_with_issues(None, [uri])
    assert prepared == []
    download.assert_awaited_once()
    assert download.await_args.args[0] == uri
    if phase == "upload":
        prepare.assert_awaited_once_with(path)
    assert len(issues) == 1
    issue = DocumentPreparationIssue(**issues[0]).model_dump(mode="json")
    assert set(issue) == {"source", "phase", "error_type", "error"}
    assert issue["phase"] == phase
    assert issue["error_type"] == "RuntimeError"
    assert "documents.example/paper.pdf" in issue["source"]
    assert "backend rejected" in issue["error"]
    assert "documents.example" in caplog.text
    for canary in ("url-user-canary", "url-password-canary", "url-query-canary", "url-fragment-canary", "error-user-canary", "error-password-canary", "error-query-canary", "error-fragment-canary", "error-field-canary"):
        assert canary not in repr(issue)
        assert canary not in caplog.text
    assert not directory.exists()


async def test_diagnostic_redaction_preserves_prepared_source(tmp_path, monkeypatch):
    """GIVEN successful preparation THEN original URL and content identity remain exact."""
    import video_research_mcp.tools.research_document_file as mod

    uri = "https://documents.example/paper.pdf?token=source-identity-canary#source-fragment-canary"
    directory = tmp_path / "download"
    directory.mkdir()
    path = directory / "paper.pdf"
    download = AsyncMock(return_value=path)
    prepare = AsyncMock(return_value=("fixture://file", "fixture-content-hash"))
    monkeypatch.setattr(mod, "view_directory", lambda: directory)
    monkeypatch.setattr(mod, "download_checked", download)
    monkeypatch.setattr(mod, "_prepare_document", prepare)
    prepared, issues = await mod._prepare_all_documents_with_issues(None, [uri])
    assert prepared == [("fixture://file", "fixture-content-hash", uri)]
    assert issues == []
    assert download.await_args.args[0] == uri
    prepare.assert_awaited_once_with(path)
