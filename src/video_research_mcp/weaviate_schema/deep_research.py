"""Weaviate collection definition for Deep Research reports.

DeepResearchReports stores web-grounded research reports from the
Gemini Deep Research Agent (Interactions API). Cross-references
ResearchFindings and WebSearchResults for knowledge graph integration.
"""

from __future__ import annotations

from .base import CollectionDef, PropertyDef, ReferenceDef, _common_properties

DEEP_RESEARCH_REPORTS = CollectionDef(
    name="DeepResearchReports",
    description="Web-grounded reports from Gemini Deep Research Agent",
    properties=_common_properties() + [
        PropertyDef(
            "interaction_id", ["text"], "Gemini interaction ID",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef("topic", ["text"], "Research topic/question"),
        PropertyDef("report_text", ["text"], "Full markdown report"),
        PropertyDef(
            "sources_json", ["text"], "Cited sources as JSON",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef(
            "source_count", ["int"], "Number of sources",
            skip_vectorization=True, index_range_filters=True,
        ),
        PropertyDef(
            "status", ["text"], "completed/failed",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef(
            "duration_seconds", ["int"], "Research wall-clock time",
            skip_vectorization=True, index_range_filters=True,
        ),
        PropertyDef(
            "usage_json", ["text"], "Token usage as JSON",
            skip_vectorization=True, index_searchable=False,
        ),
        PropertyDef("follow_up_ids", ["text[]"], "Follow-up interaction IDs",
                     skip_vectorization=True),
        PropertyDef(
            "follow_ups_json", ["text"], "Follow-up Q&A pairs as JSON array",
            skip_vectorization=True, index_searchable=False,
        ),
    ],
    references=[
        ReferenceDef(
            "related_findings", "ResearchFindings",
            "Cross-ref to offline research",
        ),
        ReferenceDef(
            "related_web_searches", "WebSearchResults",
            "Cross-ref to prior web searches",
        ),
    ],
)
