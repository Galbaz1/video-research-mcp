"""knowledge_ingest tool — manual data insertion into Weaviate collections."""

from __future__ import annotations

import asyncio
from typing import Annotated

from mcp.types import ToolAnnotations
from pydantic import Field

from ...config import get_config
from ...errors import make_tool_error
from ...models.knowledge import KnowledgeIngestResult
from ...types import KnowledgeCollection, coerce_json_param
from ...weaviate_client import WeaviateClient
from . import knowledge_server
from .helpers import ALLOWED_PROPERTIES, SCHEMA_COLLECTIONS, weaviate_not_configured
from ...tracing import trace


@knowledge_server.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        destructiveHint=False,
        idempotentHint=False,
        openWorldHint=False,
    )
)
@trace(name="knowledge_ingest", span_type="TOOL")
async def knowledge_ingest(
    collection: KnowledgeCollection,
    properties: Annotated[dict, Field(description="Object properties to insert")],
) -> dict:
    """Manually insert data into a knowledge collection.

    Properties are validated against the collection schema — unknown keys
    are rejected with allowed name:type pairs.

    Tip: call knowledge_schema(collection=...) first to see expected properties.

    Args:
        collection: Target collection name.
        properties: Dict of property values matching the collection schema.

    Returns:
        Dict matching KnowledgeIngestResult schema.
    """
    if not get_config().weaviate_enabled:
        return weaviate_not_configured()

    properties = coerce_json_param(properties, dict)

    # Validate properties against schema
    allowed = ALLOWED_PROPERTIES.get(collection, set())
    unknown = set(properties) - allowed
    if unknown:
        allowed_with_types = {
            p.name: p.data_type[0] for c in SCHEMA_COLLECTIONS
            if c.name == collection for p in c.properties
        }
        return make_tool_error(
            ValueError(
                f"Unknown properties for {collection}: {sorted(unknown)}. "
                f"Allowed: {', '.join(f'{k}:{v}' for k, v in sorted(allowed_with_types.items()))}. "
                f"Use knowledge_schema(collection='{collection}') for full details."
            )
        )

    try:
        def _insert():
            client = WeaviateClient.get()
            col = client.collections.get(collection)
            uuid = col.data.insert(properties=properties)
            return str(uuid)

        object_id = await asyncio.to_thread(_insert)
        return KnowledgeIngestResult(
            collection=collection,
            object_id=object_id,
            status="success",
        ).model_dump(mode="json")

    except Exception as exc:
        return make_tool_error(exc)
