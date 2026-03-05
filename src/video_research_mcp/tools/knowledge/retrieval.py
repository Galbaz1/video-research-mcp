"""knowledge_related, knowledge_fetch, and knowledge_stats tools."""

from __future__ import annotations

import asyncio
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field
from ...config import get_config
from ...errors import make_tool_error
from ...models.knowledge import (
    CollectionStats,
    KnowledgeFetchResult,
    KnowledgeHit,
    KnowledgeRelatedResult,
    KnowledgeStatsResult,
)
from ...types import KnowledgeCollection
from ...weaviate_client import WeaviateClient
from . import knowledge_server
from .helpers import ALL_COLLECTION_NAMES, ALLOWED_PROPERTIES, logger, serialize, weaviate_not_configured
from ...tracing import trace


@knowledge_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
@trace(name="knowledge_related", span_type="TOOL")
async def knowledge_related(
    object_id: Annotated[str, Field(min_length=1, description="UUID of the source object")],
    collection: KnowledgeCollection,
    limit: Annotated[int, Field(ge=1, le=50, description="Max related results")] = 5,
) -> dict:
    """Find semantically related objects using near-object vector search.

    Args:
        object_id: UUID of the source object.
        collection: Collection the source object belongs to.
        limit: Maximum number of related results.

    Returns:
        Dict matching KnowledgeRelatedResult schema.
    """
    if not get_config().weaviate_enabled:
        return KnowledgeRelatedResult(
            source_id=object_id, source_collection=collection,
        ).model_dump(mode="json")

    try:
        def _search():
            from weaviate.classes.query import MetadataQuery

            client = WeaviateClient.get()
            col = client.collections.get(collection)
            response = col.query.near_object(
                near_object=object_id,
                limit=limit + 1,
                return_metadata=MetadataQuery(distance=True),
            )
            hits = []
            for obj in response.objects:
                if str(obj.uuid) == object_id:
                    continue
                props = {k: serialize(v) for k, v in obj.properties.items()}
                distance = getattr(obj.metadata, "distance", None)
                score = 1.0 - distance if distance is not None else 0.0
                hits.append(KnowledgeHit(
                    collection=collection,
                    object_id=str(obj.uuid),
                    score=score,
                    properties=props,
                ))
            return hits[:limit]

        hits = await asyncio.to_thread(_search)
        return KnowledgeRelatedResult(
            source_id=object_id,
            source_collection=collection,
            related=hits,
        ).model_dump(mode="json")

    except Exception as exc:
        return make_tool_error(exc)


@knowledge_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
@trace(name="knowledge_stats", span_type="TOOL")
async def knowledge_stats(
    collection: Annotated[
        KnowledgeCollection | None,
        Field(description="Collection to count (all if omitted)"),
    ] = None,
    group_by: Annotated[
        str | None,
        Field(description="Group counts by a text property (e.g. evidence_tier, source_tool)"),
    ] = None,
) -> dict:
    """Get object counts per collection, optionally grouped by a property.

    Args:
        collection: Single collection name, or None for all collections.
        group_by: Text property name to group counts by.

    Returns:
        Dict matching KnowledgeStatsResult schema.
    """
    if not get_config().weaviate_enabled:
        return KnowledgeStatsResult().model_dump(mode="json")

    try:
        target = [collection] if collection else ALL_COLLECTION_NAMES

        def _count():
            client = WeaviateClient.get()
            stats = []
            for col_name in target:
                try:
                    col = client.collections.get(col_name)
                    agg = col.aggregate.over_all(total_count=True)
                    groups = None
                    if group_by and group_by in ALLOWED_PROPERTIES.get(col_name, set()):
                        groups = _aggregate_groups(col, group_by)
                    stats.append(CollectionStats(
                        name=col_name,
                        count=agg.total_count or 0,
                        groups=groups,
                    ))
                except Exception as exc:
                    logger.warning("Stats failed for %s: %s", col_name, exc)
                    stats.append(CollectionStats(name=col_name, count=0))
            return stats

        stats = await asyncio.to_thread(_count)
        total = sum(s.count for s in stats)
        return KnowledgeStatsResult(
            collections=stats,
            total_objects=total,
        ).model_dump(mode="json")

    except Exception as exc:
        return make_tool_error(exc)


@knowledge_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
@trace(name="knowledge_fetch", span_type="TOOL")
async def knowledge_fetch(
    object_id: Annotated[str, Field(min_length=1, description="Weaviate object UUID")],
    collection: KnowledgeCollection,
) -> dict:
    """Fetch a single object by UUID from a knowledge collection.

    Args:
        object_id: UUID of the object to retrieve.
        collection: Collection the object belongs to.

    Returns:
        Dict matching KnowledgeFetchResult schema.
    """
    if not get_config().weaviate_enabled:
        return weaviate_not_configured()

    try:
        def _fetch():
            client = WeaviateClient.get()
            col = client.collections.get(collection)
            obj = col.query.fetch_object_by_id(object_id)
            if obj is None:
                return KnowledgeFetchResult(
                    collection=collection, object_id=object_id, found=False,
                )
            props = {k: serialize(v) for k, v in obj.properties.items()}
            return KnowledgeFetchResult(
                collection=collection,
                object_id=str(obj.uuid),
                found=True,
                properties=props,
            )

        result = await asyncio.to_thread(_fetch)
        return result.model_dump(mode="json")

    except Exception as exc:
        return make_tool_error(exc)


def _aggregate_groups(col, group_by: str) -> dict[str, int]:
    """Aggregate counts grouped by a text property value."""
    try:
        from weaviate.classes.aggregate import GroupByAggregate
        response = col.aggregate.over_all(
            group_by=GroupByAggregate(prop=group_by),
            total_count=True,
        )
        groups: dict[str, int] = {}
        for group in response.groups:
            key = str(group.grouped_by.value) if group.grouped_by else "(empty)"
            groups[key] = group.total_count or 0
        return groups
    except Exception:
        return {}
