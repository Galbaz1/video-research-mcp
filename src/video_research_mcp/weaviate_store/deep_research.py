"""Store functions for DeepResearchReports collection.

Persists Gemini Deep Research reports with semantic cross-references
to existing ResearchFindings and WebSearchResults collections.
"""

from __future__ import annotations

import asyncio
import json

from ..weaviate_client import WeaviateClient
from ._base import _is_enabled, _now, logger


async def store_deep_research(report_dict: dict) -> str | None:
    """Persist a completed Deep Research report to Weaviate.

    Inserts the report and creates semantic cross-references to related
    ResearchFindings and WebSearchResults objects (near-text search).

    Args:
        report_dict: Serialised DeepResearchResult dict.

    Returns:
        Weaviate object UUID, or None if disabled/failed.
    """
    if not _is_enabled():
        return None
    try:
        def _insert():
            client = WeaviateClient.get()
            collection = client.collections.get("DeepResearchReports")

            topic = report_dict.get("report_text", "")[:500]
            uuid = str(collection.data.insert(properties={
                "created_at": _now(),
                "source_tool": "research_web",
                "interaction_id": report_dict.get("interaction_id", ""),
                "topic": topic,
                "report_text": report_dict.get("report_text", ""),
                "sources_json": json.dumps(report_dict.get("sources", [])),
                "source_count": report_dict.get("source_count", 0),
                "status": report_dict.get("status", "completed"),
                "duration_seconds": report_dict.get("duration_seconds") or 0,
                "usage_json": json.dumps(report_dict.get("usage", {})),
                "follow_up_ids": [],
            }))

            _cross_reference(client, collection, uuid, topic)
            return uuid

        return await asyncio.to_thread(_insert)
    except Exception as exc:
        logger.warning("Weaviate store failed (non-fatal): %s", exc)
        return None


def _cross_reference(client, collection, uuid: str, topic: str) -> None:
    """Create semantic cross-references to related collections.

    Near-text searches find related ResearchFindings and WebSearchResults,
    then links them via Weaviate references. All failures are silenced.
    """
    try:
        findings_col = client.collections.get("ResearchFindings")
        results = findings_col.query.near_text(
            query=topic[:200], limit=5,
        )
        for obj in getattr(results, "objects", []):
            try:
                collection.data.reference_add(
                    from_uuid=uuid,
                    from_property="related_findings",
                    to=str(obj.uuid),
                )
            except Exception:
                pass
    except Exception:
        pass

    try:
        search_col = client.collections.get("WebSearchResults")
        results = search_col.query.near_text(
            query=topic[:200], limit=5,
        )
        for obj in getattr(results, "objects", []):
            try:
                collection.data.reference_add(
                    from_uuid=uuid,
                    from_property="related_web_searches",
                    to=str(obj.uuid),
                )
            except Exception:
                pass
    except Exception:
        pass


async def store_deep_research_followup(
    original_id: str, followup_id: str,
) -> bool:
    """Append a follow-up interaction ID to an existing report.

    Args:
        original_id: The original interaction_id of the report.
        followup_id: The new follow-up interaction_id.

    Returns:
        True if updated, False if not found or disabled.
    """
    if not _is_enabled():
        return False
    try:
        def _update():
            client = WeaviateClient.get()
            collection = client.collections.get("DeepResearchReports")
            results = collection.query.fetch_objects(
                filters=_interaction_id_filter(original_id),
                limit=1,
            )
            objs = getattr(results, "objects", [])
            if not objs:
                return False

            obj = objs[0]
            existing = obj.properties.get("follow_up_ids", []) or []
            existing.append(followup_id)
            collection.data.update(
                uuid=obj.uuid,
                properties={"follow_up_ids": existing, "updated_at": _now()},
            )
            return True

        return await asyncio.to_thread(_update)
    except Exception as exc:
        logger.warning("Weaviate follow-up update failed (non-fatal): %s", exc)
        return False


def _interaction_id_filter(interaction_id: str):
    """Build a Weaviate filter for interaction_id equality."""
    from weaviate.classes.query import Filter
    return Filter.by_property("interaction_id").equal(interaction_id)
