"""Collection-aware filter builder for knowledge_search.

Builds Weaviate Filter objects from optional query parameters,
skipping conditions for properties that don't exist in the target
collection (checked against _ALLOWED_PROPERTIES from the schema).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from weaviate.classes.query import Filter

def build_collection_filter(
    col_name: str,
    allowed_properties: set[str],
    *,
    evidence_tier: str | None = None,
    source_tool: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    category: str | None = None,
    video_id: str | None = None,
) -> Filter | None:
    """Build a Weaviate filter for a specific collection.

    Only includes conditions for properties that exist in the target
    collection. Returns None if no conditions apply.

    Args:
        col_name: Collection name (used for logging context only).
        allowed_properties: Set of property names in the target collection.
        evidence_tier: Filter ResearchFindings by evidence tier.
        source_tool: Filter by originating tool name.
        date_from: Filter objects created on or after this ISO date.
        date_to: Filter objects created on or before this ISO date.
        category: Filter VideoMetadata by category label.
        video_id: Filter by video_id field.

    Returns:
        Combined Filter or None if no conditions apply.
    """
    from weaviate.classes.query import Filter

    conditions: list[Filter] = []

    if evidence_tier and "evidence_tier" in allowed_properties:
        conditions.append(Filter.by_property("evidence_tier").equal(evidence_tier))

    if source_tool and "source_tool" in allowed_properties:
        conditions.append(Filter.by_property("source_tool").equal(source_tool))

    if date_from and "created_at" in allowed_properties:
        dt = _parse_date(date_from)
        if dt:
            conditions.append(Filter.by_property("created_at").greater_or_equal(dt))

    if date_to and "created_at" in allowed_properties:
        dt = _parse_date(date_to)
        if dt:
            conditions.append(Filter.by_property("created_at").less_or_equal(dt))

    if category and "category" in allowed_properties:
        conditions.append(Filter.by_property("category").equal(category))

    if video_id and "video_id" in allowed_properties:
        conditions.append(Filter.by_property("video_id").equal(video_id))

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return Filter.all_of(conditions)


def _parse_date(date_str: str) -> datetime | None:
    """Parse an ISO date string to a UTC datetime."""
    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
