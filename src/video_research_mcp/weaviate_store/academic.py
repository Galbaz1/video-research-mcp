"""Store functions for AcademicPapers collection.

Persists Semantic Scholar paper data to Weaviate with deterministic
UUIDs based on paper_id for idempotent upserts.
"""

from __future__ import annotations

import asyncio
import json

import weaviate.util

from ..weaviate_client import WeaviateClient
from ._base import _is_enabled, _now, logger


def _paper_properties(paper: dict) -> dict:
    """Build the Weaviate properties dict for an AcademicPapers insert/replace."""
    authors = paper.get("authors", [])
    return {
        "created_at": _now(),
        "source_tool": "research_paper_search",
        "paper_id": paper.get("paper_id", ""),
        "title": paper.get("title", ""),
        "abstract": paper.get("abstract", ""),
        "authors_json": json.dumps(authors) if isinstance(authors, list) else str(authors),
        "year": paper.get("year") or 0,
        "venue": paper.get("venue", ""),
        "citation_count": paper.get("citation_count", 0),
        "fields_of_study": paper.get("fields_of_study", []),
        "doi": paper.get("doi", ""),
        "arxiv_id": paper.get("arxiv_id", ""),
        "tldr": paper.get("tldr", ""),
        "is_open_access": paper.get("is_open_access", False),
        "open_access_pdf_url": paper.get("open_access_pdf_url", ""),
        "url": paper.get("url", ""),
    }


async def store_academic_paper(paper: dict) -> str | None:
    """Persist a paper to AcademicPapers. Deterministic UUID from paper_id.

    Args:
        paper: Dict with AcademicPaper fields (paper_id, title, etc.).

    Returns:
        Weaviate object UUID, or None if disabled/failed.
    """
    if not _is_enabled():
        return None
    try:
        def _upsert() -> str:
            client = WeaviateClient.get()
            col = client.collections.get("AcademicPapers")
            paper_id = paper.get("paper_id", "")
            props = _paper_properties(paper)

            if paper_id:
                det_uuid = weaviate.util.generate_uuid5(f"s2:{paper_id}")
                try:
                    col.data.replace(uuid=det_uuid, properties=props)
                    return str(det_uuid)
                except Exception:
                    return str(col.data.insert(properties=props, uuid=det_uuid))
            return str(col.data.insert(properties=props))

        return await asyncio.to_thread(_upsert)
    except Exception as exc:
        logger.warning("Weaviate store failed (non-fatal): %s", exc)
        return None


async def store_academic_papers_batch(papers: list[dict]) -> list[str]:
    """Batch store papers. Returns list of UUIDs.

    Args:
        papers: List of AcademicPaper dicts.

    Returns:
        List of successfully stored UUIDs.
    """
    results: list[str] = []
    for p in papers:
        uid = await store_academic_paper(p)
        if uid:
            results.append(uid)
    return results
