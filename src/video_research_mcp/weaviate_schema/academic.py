"""Weaviate collection definition for academic papers from Semantic Scholar.

Stores paper metadata, abstracts, and citation info for semantic search
across ingested academic literature.
"""

from __future__ import annotations

from .base import CollectionDef, PropertyDef, _common_properties

ACADEMIC_PAPERS = CollectionDef(
    name="AcademicPapers",
    description="Academic papers from Semantic Scholar",
    properties=_common_properties() + [
        PropertyDef(
            "paper_id", ["text"], "Semantic Scholar paper ID",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef("title", ["text"], "Paper title"),
        PropertyDef("abstract", ["text"], "Paper abstract"),
        PropertyDef(
            "authors_json", ["text"], "JSON array of author objects",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef(
            "year", ["int"], "Publication year",
            skip_vectorization=True, index_range_filters=True,
        ),
        PropertyDef("venue", ["text"], "Publication venue"),
        PropertyDef(
            "citation_count", ["int"], "Number of citations",
            skip_vectorization=True, index_range_filters=True,
        ),
        PropertyDef("fields_of_study", ["text[]"], "Academic fields"),
        PropertyDef(
            "doi", ["text"], "DOI identifier",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef(
            "arxiv_id", ["text"], "ArXiv ID",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef("tldr", ["text"], "TL;DR summary"),
        PropertyDef(
            "is_open_access", ["boolean"], "Open access availability",
            skip_vectorization=True,
        ),
        PropertyDef(
            "open_access_pdf_url", ["text"], "Open access PDF URL",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef(
            "url", ["text"], "Semantic Scholar URL",
            skip_vectorization=True, index_searchable=False,
        ),
    ],
)
