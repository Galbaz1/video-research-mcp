"""knowledge_schema tool — expose collection property schemas without Weaviate."""

from __future__ import annotations

from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ...types import KnowledgeCollection
from ...tracing import trace
from . import knowledge_server
from .helpers import SCHEMA_COLLECTIONS


@knowledge_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
)
@trace(name="knowledge_schema", span_type="TOOL")
async def knowledge_schema(
    collection: Annotated[
        KnowledgeCollection | None,
        Field(description="Collection to inspect (omit for all)"),
    ] = None,
) -> dict:
    """Return property schemas for knowledge collections.

    Reads from local CollectionDef objects — no Weaviate connection needed.
    Use this before knowledge_ingest to discover expected property names and types.

    Args:
        collection: Single collection name, or None for all collections.

    Returns:
        Dict mapping collection names to lists of {name, type, description}.
    """
    result: dict[str, list[dict[str, str]]] = {}
    for col_def in SCHEMA_COLLECTIONS:
        if collection and col_def.name != collection:
            continue
        result[col_def.name] = [
            {
                "name": p.name,
                "type": p.data_type[0],
                "description": p.description,
            }
            for p in col_def.properties
        ]
    return {"schemas": result, "total_collections": len(result)}
