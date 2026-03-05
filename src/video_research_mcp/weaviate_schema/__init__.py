"""Weaviate collection definitions — 12 collections for knowledge storage.

Each CollectionDef maps to a Weaviate class. Collections are created
idempotently by WeaviateClient.ensure_collections() on first connection.
ALL_COLLECTIONS is the canonical list consumed by the client and tests.

Re-exports all types and collection constants so existing imports like
``from .weaviate_schema import ALL_COLLECTIONS`` keep working.
"""

from __future__ import annotations

from .base import CollectionDef, PropertyDef, ReferenceDef, _common_properties
from .calls import CALL_NOTES
from .deep_research import DEEP_RESEARCH_REPORTS
from .collections import (
    CONTENT_ANALYSES,
    RESEARCH_FINDINGS,
    RESEARCH_PLANS,
    SESSION_TRANSCRIPTS,
    VIDEO_ANALYSES,
    VIDEO_METADATA,
    WEB_SEARCH_RESULTS,
)
from .community import COMMUNITY_REACTIONS
from .concepts import CONCEPT_KNOWLEDGE, RELATIONSHIP_EDGES

ALL_COLLECTIONS: list[CollectionDef] = [
    RESEARCH_FINDINGS,
    VIDEO_ANALYSES,
    CONTENT_ANALYSES,
    VIDEO_METADATA,
    SESSION_TRANSCRIPTS,
    WEB_SEARCH_RESULTS,
    RESEARCH_PLANS,
    COMMUNITY_REACTIONS,
    CONCEPT_KNOWLEDGE,
    RELATIONSHIP_EDGES,
    CALL_NOTES,
    DEEP_RESEARCH_REPORTS,
]

__all__ = [
    "ALL_COLLECTIONS",
    "CALL_NOTES",
    "COMMUNITY_REACTIONS",
    "CONCEPT_KNOWLEDGE",
    "CollectionDef",
    "CONTENT_ANALYSES",
    "DEEP_RESEARCH_REPORTS",
    "PropertyDef",
    "ReferenceDef",
    "RELATIONSHIP_EDGES",
    "RESEARCH_FINDINGS",
    "RESEARCH_PLANS",
    "SESSION_TRANSCRIPTS",
    "VIDEO_ANALYSES",
    "VIDEO_METADATA",
    "WEB_SEARCH_RESULTS",
    "_common_properties",
]
