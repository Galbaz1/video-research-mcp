"""knowledge_search tool — hybrid, semantic, and keyword search across collections."""

from __future__ import annotations

import asyncio
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field
from ...config import get_config
from ...errors import make_tool_error
from ...models.knowledge import KnowledgeHit, KnowledgeSearchResult
from ...types import KnowledgeCollection, coerce_json_param
from ...weaviate_client import WeaviateClient
from ..knowledge_filters import build_collection_filter
from . import knowledge_server
from .helpers import ALL_COLLECTION_NAMES, ALLOWED_PROPERTIES, RERANK_PROPERTY, SearchType, logger, serialize
from ...tracing import trace


@knowledge_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
@trace(name="knowledge_search", span_type="TOOL")
async def knowledge_search(
    query: Annotated[str, Field(min_length=1, description="Search query")],
    collections: Annotated[
        list[KnowledgeCollection] | None,
        Field(description="Collections to search (all if omitted)"),
    ] = None,
    search_type: Annotated[
        SearchType,
        Field(description="Search mode: hybrid (BM25+vector), semantic (vector only), keyword (BM25 only)"),
    ] = "hybrid",
    limit: Annotated[int, Field(ge=1, le=100, description="Maximum total results to return")] = 10,
    alpha: Annotated[float, Field(ge=0.0, le=1.0, description="Hybrid balance: 0=BM25, 1=vector")] = 0.5,
    evidence_tier: Annotated[str | None, Field(description="Filter by evidence tier (e.g. CONFIRMED)")] = None,
    source_tool: Annotated[str | None, Field(description="Filter by originating tool name")] = None,
    date_from: Annotated[str | None, Field(description="Filter created_at >= ISO date")] = None,
    date_to: Annotated[str | None, Field(description="Filter created_at <= ISO date")] = None,
    category: Annotated[str | None, Field(description="Filter VideoMetadata by category")] = None,
    video_id: Annotated[str | None, Field(description="Filter by video_id")] = None,
) -> dict:
    """Search across knowledge collections using hybrid, semantic, or keyword mode.

    Searches specified or all collections. Results are merged and sorted by score.
    Filters are collection-aware: conditions are skipped for collections
    that lack the relevant property.

    Args:
        query: Text to search for.
        collections: Which collections to search (default: all).
        search_type: Search algorithm — hybrid, semantic (near_text), or keyword (BM25).
        limit: Maximum total results to return.
        alpha: Hybrid balance (only used when search_type="hybrid").
        evidence_tier: Filter ResearchFindings by evidence tier.
        source_tool: Filter any collection by originating tool.
        date_from: Filter objects created on or after this ISO date.
        date_to: Filter objects created on or before this ISO date.
        category: Filter VideoMetadata by category label.
        video_id: Filter by video_id field.

    Returns:
        Dict matching KnowledgeSearchResult schema.
    """
    if not get_config().weaviate_enabled:
        return KnowledgeSearchResult(query=query).model_dump(mode="json")

    collections = coerce_json_param(collections, list)

    try:
        cfg = get_config()
        target = list(collections) if collections else ALL_COLLECTION_NAMES
        filter_kwargs = dict(
            evidence_tier=evidence_tier, source_tool=source_tool,
            date_from=date_from, date_to=date_to,
            category=category, video_id=video_id,
        )
        filters_applied = {k: v for k, v in filter_kwargs.items() if v is not None} or None
        reranked = False

        def _search():
            client = WeaviateClient.get()
            hits: list[KnowledgeHit] = []
            any_reranked = False
            for col_name in target:
                try:
                    collection = client.collections.get(col_name)
                    col_filter = build_collection_filter(
                        col_name, ALLOWED_PROPERTIES.get(col_name, set()), **filter_kwargs,
                    )
                    rerank_prop = RERANK_PROPERTY.get(col_name) if cfg.reranker_enabled else None
                    rerank_cfg = _build_rerank(rerank_prop, query) if rerank_prop else None
                    fetch_limit = limit * _OVERFETCH_FACTOR if rerank_cfg else limit

                    response = _dispatch_search(
                        collection, query, search_type, fetch_limit, alpha, col_filter, rerank_cfg,
                    )
                    if rerank_cfg:
                        any_reranked = True
                    for obj in response.objects:
                        props = {k: serialize(v) for k, v in obj.properties.items()}
                        base_score, rerank_score = _extract_score(obj, search_type)
                        hits.append(KnowledgeHit(
                            collection=col_name,
                            object_id=str(obj.uuid),
                            score=base_score,
                            rerank_score=rerank_score,
                            properties=props,
                        ))
                except Exception as exc:
                    logger.warning("Search failed for %s: %s", col_name, exc)

            # Sort by rerank_score when available, fall back to base score
            hits.sort(
                key=lambda h: (h.rerank_score if h.rerank_score is not None else -1, h.score),
                reverse=True,
            )
            return hits, any_reranked

        hits, reranked = await asyncio.to_thread(_search)
        hits = hits[:limit]

        # Flash post-processing (async, best-effort)
        flash_processed = False
        if cfg.flash_summarize and hits:
            from .summarize import summarize_hits
            hits = await summarize_hits(hits, query)
            flash_processed = any(h.summary is not None for h in hits)

        return KnowledgeSearchResult(
            query=query,
            total_results=len(hits),
            results=hits,
            filters_applied=filters_applied,
            reranked=reranked,
            flash_processed=flash_processed,
        ).model_dump(mode="json")

    except Exception as exc:
        return make_tool_error(exc)


_OVERFETCH_FACTOR = 3


def _build_rerank(prop: str, query: str):
    """Build a Rerank config for Weaviate query methods."""
    from weaviate.classes.query import Rerank
    return Rerank(prop=prop, query=query)


def _dispatch_search(collection, query, search_type, limit, alpha, col_filter, rerank_cfg=None):
    """Dispatch to the correct Weaviate query method based on search_type."""
    from weaviate.classes.query import MetadataQuery
    if search_type == "semantic":
        return collection.query.near_text(
            query=query,
            limit=limit,
            filters=col_filter,
            rerank=rerank_cfg,
            return_metadata=MetadataQuery(distance=True),
        )
    if search_type == "keyword":
        return collection.query.bm25(
            query=query,
            limit=limit,
            filters=col_filter,
            rerank=rerank_cfg,
            return_metadata=MetadataQuery(score=True),
        )
    # Default: hybrid
    return collection.query.hybrid(
        query=query,
        limit=limit,
        alpha=alpha,
        filters=col_filter,
        rerank=rerank_cfg,
        return_metadata=MetadataQuery(score=True),
    )


def _extract_score(obj, search_type: str) -> tuple[float, float | None]:
    """Extract base score and optional rerank score from a Weaviate result."""
    rerank_score = getattr(obj.metadata, "rerank_score", None)
    if search_type == "semantic":
        distance = getattr(obj.metadata, "distance", None)
        base = 1.0 - distance if distance is not None else 0.0
    else:
        base = getattr(obj.metadata, "score", 0.0) or 0.0
    return base, rerank_score
