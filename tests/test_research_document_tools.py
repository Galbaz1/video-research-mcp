"""Tests for research_document tool."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

import video_research_mcp.tools.research_document as research_document_mod
from video_research_mcp.models.research_document import (
    CrossReferenceMap,
    DocumentFinding,
    DocumentFindingsContainer,
    DocumentMap,
    DocumentResearchReport,
)
from tests.conftest import unwrap_tool

research_document = unwrap_tool(research_document_mod.research_document)


@pytest.fixture()
def mock_prepare():
    """Mock document preparation to avoid real File API uploads."""
    with patch(
        "video_research_mcp.tools.research_document._prepare_all_documents_with_issues",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = (
            [("gs://fake-uri-1", "hash1", "/path/to/doc1.pdf")],
            [],
        )
        yield mock


@pytest.fixture()
def mock_prepare_multi():
    """Mock preparation for multi-document tests."""
    with patch(
        "video_research_mcp.tools.research_document._prepare_all_documents_with_issues",
        new_callable=AsyncMock,
    ) as mock:
        mock.return_value = (
            [
                ("gs://fake-uri-1", "hash1", "/path/to/doc1.pdf"),
                ("gs://fake-uri-2", "hash2", "/path/to/doc2.pdf"),
            ],
            [],
        )
        yield mock


@pytest.fixture()
def mock_store():
    """Mock Weaviate store."""
    with patch(
        "video_research_mcp.tools.research_document.store_research_finding",
        new_callable=AsyncMock,
    ) as mock:
        yield mock


class TestResearchDocument:
    @patch(
        "video_research_mcp.tools.research_document.store_research_finding",
        new_callable=AsyncMock,
    )
    async def test_single_document_moderate(
        self, mock_store_fn, mock_prepare, mock_gemini_client,
    ):
        """GIVEN one document WHEN moderate scope THEN phases 1-2-4 run."""
        mock_gemini_client["generate_structured"].side_effect = [
            # Phase 1: Document map
            DocumentMap(title="Test Paper", sections=["Intro", "Methods"], summary="A paper"),
            # Phase 2: Evidence
            DocumentFindingsContainer(
                document="doc1.pdf",
                findings=[DocumentFinding(claim="X is true", evidence_tier="CONFIRMED")],
            ),
            # Phase 4: Synthesis (skip phase 3 for single doc moderate)
            DocumentResearchReport(
                executive_summary="The paper shows X.",
                findings=[DocumentFinding(claim="X is true", evidence_tier="CONFIRMED")],
            ),
        ]
        result = await research_document(
            instruction="Analyze methodology",
            file_paths=["/path/to/doc1.pdf"],
            scope="moderate",
        )
        assert "error" not in result
        assert result["scope"] == "moderate"
        assert result["executive_summary"] == "The paper shows X."
        assert len(result["document_sources"]) == 1

    @patch(
        "video_research_mcp.tools.research_document.store_research_finding",
        new_callable=AsyncMock,
    )
    async def test_multi_document_deep(
        self, mock_store_fn, mock_prepare_multi, mock_gemini_client,
    ):
        """GIVEN two documents WHEN deep scope THEN all 4 phases run."""
        mock_gemini_client["generate_structured"].side_effect = [
            # Phase 1: two maps
            DocumentMap(title="Paper A", sections=["Intro"], summary="Paper A"),
            DocumentMap(title="Paper B", sections=["Methods"], summary="Paper B"),
            # Phase 2: two findings
            DocumentFindingsContainer(
                document="doc1.pdf",
                findings=[DocumentFinding(claim="A says X", evidence_tier="CONFIRMED")],
            ),
            DocumentFindingsContainer(
                document="doc2.pdf",
                findings=[DocumentFinding(claim="B says Y", evidence_tier="INFERENCE")],
            ),
            # Phase 3: cross-reference
            CrossReferenceMap(agreements=[], contradictions=[]),
            # Phase 4: synthesis
            DocumentResearchReport(
                executive_summary="Papers A and B complement each other.",
            ),
        ]
        result = await research_document(
            instruction="Compare findings",
            file_paths=["/path/to/doc1.pdf", "/path/to/doc2.pdf"],
            scope="deep",
        )
        assert "error" not in result
        assert len(result["document_sources"]) == 2
        assert result["scope"] == "deep"

    @patch(
        "video_research_mcp.tools.research_document.store_research_finding",
        new_callable=AsyncMock,
    )
    async def test_quick_scope(
        self, mock_store_fn, mock_prepare, mock_gemini_client,
    ):
        """GIVEN quick scope WHEN running THEN only phases 1 and quick synthesis."""
        mock_gemini_client["generate_structured"].side_effect = [
            # Phase 1
            DocumentMap(title="Quick Doc", summary="Brief doc"),
            # Quick synthesis (skip phases 2-4)
            DocumentResearchReport(executive_summary="Quick analysis."),
        ]
        result = await research_document(
            instruction="Quick summary",
            file_paths=["/path/to/doc.pdf"],
            scope="quick",
        )
        assert result["scope"] == "quick"
        assert result["executive_summary"] == "Quick analysis."

    async def test_no_sources_returns_error(self, mock_gemini_client):
        """GIVEN no file_paths or urls WHEN calling THEN error returned."""
        result = await research_document(instruction="test")
        assert "error" in result

    async def test_rejects_too_many_sources(self, clean_config, monkeypatch, mock_gemini_client):
        """GIVEN more sources than policy limit WHEN calling THEN return bounded-workload error."""
        monkeypatch.setenv("RESEARCH_DOCUMENT_MAX_SOURCES", "1")
        result = await research_document(
            instruction="test",
            file_paths=["/path/to/doc1.pdf", "/path/to/doc2.pdf"],
        )
        assert "error" in result
        assert "Too many document sources requested" in result["error"]

    async def test_preparation_failure(self, mock_gemini_client):
        """GIVEN file prep fails WHEN calling THEN error returned."""
        with patch(
            "video_research_mcp.tools.research_document._prepare_all_documents_with_issues",
            new_callable=AsyncMock,
            return_value=([], []),
        ):
            result = await research_document(
                instruction="test",
                file_paths=["/nonexistent.pdf"],
            )
            assert "error" in result

    @patch(
        "video_research_mcp.tools.research_document.store_research_finding",
        new_callable=AsyncMock,
    )
    async def test_gemini_failure_in_phase(
        self, mock_store_fn, mock_prepare, mock_gemini_client,
    ):
        """GIVEN Gemini fails during a phase WHEN running THEN error returned."""
        mock_gemini_client["generate_structured"].side_effect = RuntimeError("Gemini error")
        result = await research_document(
            instruction="test",
            file_paths=["/path/to/doc.pdf"],
        )
        assert "error" in result

    @patch(
        "video_research_mcp.tools.research_document.store_research_finding",
        new_callable=AsyncMock,
    )
    async def test_weaviate_store_called(
        self, mock_store_fn, mock_prepare, mock_gemini_client,
    ):
        """GIVEN successful research WHEN complete THEN store_research_finding called."""
        mock_gemini_client["generate_structured"].side_effect = [
            DocumentMap(title="Test", summary="Test"),
            DocumentFindingsContainer(document="doc.pdf", findings=[]),
            DocumentResearchReport(executive_summary="Done"),
        ]
        await research_document(
            instruction="test",
            file_paths=["/path/to/doc.pdf"],
            scope="moderate",
        )
        mock_store_fn.assert_called_once()

    @patch(
        "video_research_mcp.tools.research_document.store_research_finding",
        new_callable=AsyncMock,
    )
    async def test_url_source_type(
        self, mock_store_fn, mock_gemini_client,
    ):
        """GIVEN a URL source WHEN processing THEN source_type is 'url'."""
        with patch(
            "video_research_mcp.tools.research_document._prepare_all_documents_with_issues",
            new_callable=AsyncMock,
            return_value=([("gs://fake", "hash1", "https://example.com/paper.pdf")], []),
        ):
            mock_gemini_client["generate_structured"].side_effect = [
                DocumentMap(title="URL Doc", summary="From URL"),
                DocumentFindingsContainer(document="paper.pdf", findings=[]),
                DocumentResearchReport(executive_summary="URL result"),
            ]
            result = await research_document(
                instruction="test",
                urls=["https://example.com/paper.pdf"],
                scope="moderate",
            )
            assert result["document_sources"][0]["source_type"] == "url"

    @patch(
        "video_research_mcp.tools.research_document.store_research_finding",
        new_callable=AsyncMock,
    )
    async def test_surfaces_preparation_issues(
        self, mock_store_fn, mock_gemini_client,
    ):
        """GIVEN partial prep failures WHEN synthesis completes THEN response includes issues."""
        with patch(
            "video_research_mcp.tools.research_document._prepare_all_documents_with_issues",
            new_callable=AsyncMock,
            return_value=(
                [("gs://fake", "hash1", "/path/to/doc.pdf")],
                [
                    {
                        "source": "https://example.com/bad.pdf",
                        "phase": "download",
                        "error_type": "UrlPolicyError",
                        "error": "Blocked hostname",
                    }
                ],
            ),
        ):
            mock_gemini_client["generate_structured"].side_effect = [
                DocumentMap(title="Doc", summary="OK"),
                DocumentFindingsContainer(document="doc.pdf", findings=[]),
                DocumentResearchReport(executive_summary="Done"),
            ]
            result = await research_document(
                instruction="test",
                file_paths=["/path/to/doc.pdf"],
                urls=["https://example.com/bad.pdf"],
                scope="moderate",
            )
            assert result["preparation_issues"] == [
                {
                    "source": "https://example.com/bad.pdf",
                    "phase": "download",
                    "error_type": "UrlPolicyError",
                    "error": "Blocked hostname",
                }
            ]
