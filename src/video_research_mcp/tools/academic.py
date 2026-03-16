"""Academic research tools — 5 tools on research_server (Semantic Scholar).

Provides paper search, paper details, citations/references, recommendations,
and author search via the Semantic Scholar Graph API. Papers are automatically
stored to Weaviate for knowledge graph integration.
"""

from __future__ import annotations

import logging
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ..academic_client import SemanticScholarClient
from ..errors import make_tool_error
from ..models.academic import (
    AcademicPaper,
    AuthorSearchResult,
    CitationResult,
    PaperSearchResult,
    RecommendationResult,
    paper_from_api,
)
from ..tracing import trace
from ..types import coerce_json_param
from .research import research_server

logger = logging.getLogger(__name__)


async def _store_papers(papers: list[dict]) -> None:
    """Fire-and-forget batch store of paper dicts to Weaviate."""
    try:
        from ..weaviate_store import store_academic_papers_batch
        await store_academic_papers_batch(papers)
    except Exception as exc:
        logger.warning("Weaviate store failed (non-fatal): %s", exc)


def _dump_papers(papers: list[AcademicPaper]) -> list[dict]:
    """Serialize a list of AcademicPaper models to JSON-safe dicts."""
    return [p.model_dump(mode="json") for p in papers]


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_paper_search", span_type="TOOL")
async def research_paper_search(
    query: Annotated[str, Field(min_length=2, max_length=500, description="Search query for academic papers")],
    fields_of_study: Annotated[
        list[str] | None,
        Field(description="Filter by fields (e.g. Computer Science, Medicine)"),
    ] = None,
    year_range: Annotated[
        str | None,
        Field(description="Year filter: '2020' for single year, '2020-2024' for range, '2020-' for since"),
    ] = None,
    open_access_only: Annotated[bool, Field(description="Only return open access papers")] = False,
    limit: Annotated[int, Field(ge=1, le=100, description="Max papers to return")] = 10,
) -> dict:
    """Search academic papers on Semantic Scholar.

    Returns papers with metadata, abstracts, citation counts, and TL;DR
    summaries. Supports filtering by field of study, year range, and
    open access availability.

    Args:
        query: Search terms (title, abstract, keywords).
        fields_of_study: Filter by academic fields.
        year_range: Year or year range filter.
        open_access_only: Only open access papers.
        limit: Maximum number of papers.

    Returns:
        Dict with total count and list of papers.
    """
    if fields_of_study is not None:
        fields_of_study = coerce_json_param(fields_of_study, list)

    try:
        data = await SemanticScholarClient.search_papers(
            query=query,
            limit=limit,
            fields_of_study=fields_of_study,
            year=year_range,
            open_access_only=open_access_only,
        )

        papers = [paper_from_api(p) for p in data.get("data", [])]
        paper_dicts = _dump_papers(papers)
        result = PaperSearchResult(
            total=data.get("total", len(papers)),
            papers=papers,
        ).model_dump(mode="json")

        await _store_papers(paper_dicts)
        return result

    except Exception as exc:
        return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_paper_details", span_type="TOOL")
async def research_paper_details(
    paper_id: Annotated[str, Field(
        min_length=1,
        description="Paper ID: S2 ID, DOI (prefix 'DOI:10.xxx'), or ArXiv (prefix 'ArXiv:2301.xxx')",
    )],
) -> dict:
    """Get detailed metadata for a specific paper.

    Accepts Semantic Scholar IDs, DOIs (prefix with DOI:), or ArXiv IDs
    (prefix with ArXiv:).

    Args:
        paper_id: Paper identifier in any supported format.

    Returns:
        Dict with full paper metadata.
    """
    try:
        data = await SemanticScholarClient.get_paper(paper_id)
        result = paper_from_api(data).model_dump(mode="json")

        try:
            from ..weaviate_store import store_academic_paper
            await store_academic_paper(result)
        except Exception as exc:
            logger.warning("Weaviate store failed (non-fatal): %s", exc)

        return result

    except Exception as exc:
        return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_paper_citations", span_type="TOOL")
async def research_paper_citations(
    paper_id: Annotated[str, Field(
        min_length=1,
        description="Paper ID (S2, DOI:, or ArXiv:)",
    )],
    direction: Annotated[str, Field(
        description="'citations' (papers citing this) or 'references' (papers this cites)",
    )] = "citations",
    limit: Annotated[int, Field(ge=1, le=1000, description="Max papers to return")] = 20,
) -> dict:
    """Get citations or references for a paper.

    Args:
        paper_id: Paper identifier.
        direction: 'citations' for papers citing this one, 'references' for this paper's bibliography.
        limit: Maximum number of papers.

    Returns:
        Dict with paper_id, direction, and list of related papers.
    """
    try:
        if direction == "references":
            data = await SemanticScholarClient.get_references(paper_id, limit=limit)
        else:
            data = await SemanticScholarClient.get_citations(paper_id, limit=limit)

        # S2 API wraps each paper in a nested "citingPaper" or "citedPaper" key
        nested_key = "citingPaper" if direction == "citations" else "citedPaper"
        raw_papers = [
            item[nested_key] for item in data.get("data", [])
            if item.get(nested_key)
        ]

        papers = [paper_from_api(p) for p in raw_papers]
        paper_dicts = _dump_papers(papers)
        result = CitationResult(
            paper_id=paper_id,
            direction=direction,
            papers=papers,
        ).model_dump(mode="json")

        await _store_papers(paper_dicts)
        return result

    except Exception as exc:
        return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_paper_recommendations", span_type="TOOL")
async def research_paper_recommendations(
    seed_paper_ids: Annotated[list[str], Field(
        min_length=1,
        description="List of S2 paper IDs to base recommendations on",
    )],
    limit: Annotated[int, Field(ge=1, le=500, description="Max papers to return")] = 10,
) -> dict:
    """Get paper recommendations based on seed papers.

    Uses Semantic Scholar's recommendation engine to find related papers.

    Args:
        seed_paper_ids: One or more paper IDs as seeds.
        limit: Maximum recommendations.

    Returns:
        Dict with seed IDs and recommended papers.
    """
    seed_paper_ids = coerce_json_param(seed_paper_ids, list)

    try:
        data = await SemanticScholarClient.get_recommendations(
            seed_paper_ids=seed_paper_ids,
            limit=limit,
        )

        papers = [paper_from_api(p) for p in data.get("recommendedPapers", [])]
        paper_dicts = _dump_papers(papers)
        result = RecommendationResult(
            seed_paper_ids=seed_paper_ids,
            papers=papers,
        ).model_dump(mode="json")

        await _store_papers(paper_dicts)
        return result

    except Exception as exc:
        return make_tool_error(exc)


@research_server.tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
@trace(name="research_author_search", span_type="TOOL")
async def research_author_search(
    query: Annotated[str, Field(min_length=2, max_length=200, description="Author name to search")],
    limit: Annotated[int, Field(ge=1, le=100, description="Max authors to return")] = 5,
) -> dict:
    """Search for academic authors on Semantic Scholar.

    Returns author profiles with affiliation, paper count, citation count,
    and h-index.

    Args:
        query: Author name or partial name.
        limit: Maximum authors to return.

    Returns:
        Dict with list of author profiles.
    """
    try:
        data = await SemanticScholarClient.search_authors(query=query, limit=limit)
        return AuthorSearchResult(
            authors=data.get("data", []),
        ).model_dump(mode="json")

    except Exception as exc:
        return make_tool_error(exc)
