"""Academic paper models — Pydantic schemas for Semantic Scholar data.

Maps the S2 Graph API response format to clean domain models used by
the academic tools and Weaviate store.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AcademicAuthor(BaseModel):
    """A paper author from Semantic Scholar."""

    author_id: str = ""
    name: str = ""


class AcademicPaper(BaseModel):
    """A single academic paper with metadata."""

    paper_id: str = ""
    title: str = ""
    abstract: str = ""
    authors: list[AcademicAuthor] = Field(default_factory=list)
    year: int | None = None
    venue: str = ""
    citation_count: int = 0
    reference_count: int = 0
    fields_of_study: list[str] = Field(default_factory=list)
    doi: str = ""
    arxiv_id: str = ""
    tldr: str = ""
    is_open_access: bool = False
    open_access_pdf_url: str = ""
    url: str = ""


class PaperSearchResult(BaseModel):
    """Result of a paper search query."""

    total: int = 0
    papers: list[AcademicPaper] = Field(default_factory=list)


class CitationResult(BaseModel):
    """Citations or references for a paper."""

    paper_id: str = ""
    direction: str = ""  # "citations" or "references"
    papers: list[AcademicPaper] = Field(default_factory=list)


class RecommendationResult(BaseModel):
    """Recommended papers based on seed papers."""

    seed_paper_ids: list[str] = Field(default_factory=list)
    papers: list[AcademicPaper] = Field(default_factory=list)


class AuthorSearchResult(BaseModel):
    """Result of an author search query."""

    authors: list[dict] = Field(default_factory=list)


def paper_from_api(data: dict) -> AcademicPaper:
    """Map a Semantic Scholar API paper response to AcademicPaper.

    Handles nested fields: externalIds (doi, arxiv), tldr dict,
    openAccessPdf dict, and author list.
    """
    if not data:
        return AcademicPaper()

    external_ids = data.get("externalIds") or {}
    tldr_data = data.get("tldr") or {}
    oa_pdf = data.get("openAccessPdf") or {}
    authors_raw = data.get("authors") or []

    paper_id = data.get("paperId") or ""

    return AcademicPaper(
        paper_id=paper_id,
        title=data.get("title") or "",
        abstract=data.get("abstract") or "",
        authors=[
            AcademicAuthor(
                author_id=a.get("authorId") or "",
                name=a.get("name") or "",
            )
            for a in authors_raw
        ],
        year=data.get("year"),
        venue=data.get("venue") or "",
        citation_count=data.get("citationCount") or 0,
        reference_count=data.get("referenceCount") or 0,
        fields_of_study=data.get("fieldsOfStudy") or [],
        doi=external_ids.get("DOI") or "",
        arxiv_id=external_ids.get("ArXiv") or "",
        tldr=tldr_data.get("text") or "",
        is_open_access=bool(data.get("isOpenAccess")),
        open_access_pdf_url=oa_pdf.get("url") or "",
        url=f"https://www.semanticscholar.org/paper/{paper_id}" if paper_id else "",
    )
