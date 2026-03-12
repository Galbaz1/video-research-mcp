"""Re-vectorize all Weaviate objects with OpenAI embeddings.

One-time script. Migrated objects have 1024d vectors from text2vec-weaviate
(cloud). Local Docker uses text2vec-openai (text-embedding-3-small, 1536d).

Since the HNSW index is locked to 1024d, we must:
1. Export all objects (properties only, no vectors)
2. Delete and recreate each collection
3. Re-insert objects — text2vec-openai generates fresh 1536d vectors

Usage:
    uv run python scripts/revectorize_openai.py
"""

from __future__ import annotations

import os
import sys
import time

import weaviate
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.init import AdditionalConfig, Timeout
from weaviate.classes.query import MetadataQuery

# Match RERANK_PROPERTY keys from knowledge/helpers.py
RERANK_PROPERTIES: dict[str, str] = {
    "ResearchFindings": "topic",
    "VideoAnalyses": "content",
    "ContentAnalyses": "content",
    "VideoMetadata": "title",
    "SessionTranscripts": "content",
    "WebSearchResults": "content",
    "ResearchPlans": "objective",
    "CommunityReactions": "content",
    "ConceptKnowledge": "description",
    "RelationshipEdges": "description",
    "CallNotes": "summary",
    "DeepResearchReports": "executive_summary",
}


def connect() -> weaviate.WeaviateClient:
    """Connect to local Weaviate with OpenAI API key header."""
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    return weaviate.connect_to_local(
        headers={"X-OpenAI-Api-Key": openai_key},
        additional_config=AdditionalConfig(
            timeout=Timeout(init=30, query=120, insert=300),
        ),
    )


def export_collection(client: weaviate.WeaviateClient, name: str) -> list[dict]:
    """Export all objects from a collection (properties only, no vectors)."""
    col = client.collections.get(name)
    objects = []
    for obj in col.iterator(return_metadata=MetadataQuery(creation_time=True)):
        objects.append({"uuid": obj.uuid, "properties": dict(obj.properties)})
    return objects


def recreate_collection(client: weaviate.WeaviateClient, name: str) -> None:
    """Delete and recreate a collection with text2vec-openai vectorizer.

    Reads the existing schema (properties, description) before deletion,
    then creates a fresh collection with text2vec-openai vector config.
    """
    col = client.collections.get(name)
    config = col.config.get()

    # Capture schema before deletion
    description = config.description or ""
    properties = []
    for prop in config.properties:
        properties.append(Property(
            name=prop.name,
            data_type=prop.data_type,
            description=prop.description or None,
            skip_vectorization=prop.vectorizer_config.skip if prop.vectorizer_config else False,
            index_filterable=prop.index_filterable,
            index_range_filters=prop.index_range_filters,
            index_searchable=prop.index_searchable,
        ))

    # Delete collection
    client.collections.delete(name)

    # Recreate with text2vec-openai
    client.collections.create(
        name=name,
        description=description,
        properties=properties,
        vector_config=Configure.Vectors.text2vec_openai(),
    )


def insert_objects(
    client: weaviate.WeaviateClient,
    name: str,
    objects: list[dict],
) -> int:
    """Batch-insert objects without vectors (triggers text2vec-openai)."""
    col = client.collections.get(name)
    failed = 0

    with col.batch.fixed_size(batch_size=100) as batch:
        for obj in objects:
            batch.add_object(
                properties=obj["properties"],
                uuid=obj["uuid"],
            )

    if col.batch.failed_objects:
        failed = len(col.batch.failed_objects)
        for err in col.batch.failed_objects[:3]:
            print(f"    FAIL: {err.message}")

    return len(objects) - failed


def verify_search(client: weaviate.WeaviateClient) -> bool:
    """Verify semantic search works after re-vectorization."""
    col = client.collections.get("ResearchFindings")
    try:
        result = col.query.near_text(
            query="video analysis",
            limit=3,
            return_metadata=MetadataQuery(distance=True),
        )
        if result.objects:
            print(f"  Semantic search: {len(result.objects)} results")
            for obj in result.objects:
                topic = obj.properties.get("topic", "")[:80]
                print(f"    dist={obj.metadata.distance:.3f} | {topic}")
            return True
        print("  Semantic search: 0 results (FAIL)")
    except Exception as exc:
        print(f"  Semantic search error: {exc}")
    return False


def main() -> None:
    """Re-vectorize all collections via export → recreate → import."""
    print("Connecting to local Weaviate...")
    client = connect()
    print(f"  Ready: {client.is_ready()}")

    collections = sorted(client.collections.list_all().keys())
    print(f"\n=== Phase 1: Export {len(collections)} collections ===\n")

    exported: dict[str, list[dict]] = {}
    total_objects = 0
    for name in collections:
        objects = export_collection(client, name)
        exported[name] = objects
        total_objects += len(objects)
        print(f"  {name}: {len(objects)} objects exported")

    print(f"\n  Total: {total_objects} objects in memory")

    print(f"\n=== Phase 2: Recreate collections with text2vec-openai ===\n")

    for name in collections:
        recreate_collection(client, name)
        print(f"  {name}: recreated")

    print(f"\n=== Phase 3: Re-insert with OpenAI embeddings ===\n")

    start = time.time()
    total_inserted = 0
    for name in collections:
        objects = exported[name]
        if not objects:
            print(f"  {name}: empty, skipping")
            continue

        print(f"  {name}: inserting {len(objects)} objects...")
        t0 = time.time()
        inserted = insert_objects(client, name, objects)
        elapsed = time.time() - t0
        total_inserted += inserted
        print(f"  {name}: {inserted}/{len(objects)} inserted in {elapsed:.1f}s")

    elapsed = time.time() - start
    print(f"\n  Total: {total_inserted}/{total_objects} inserted in {elapsed:.1f}s")

    # Verify vector dimensions
    print("\n=== Verification ===\n")
    print("Vector dimensions:")
    for name in collections:
        col = client.collections.get(name)
        count = col.aggregate.over_all(total_count=True).total_count
        if count == 0:
            continue
        for obj in col.iterator(include_vector=True):
            vec = obj.vector.get("default", [])
            dim = len(vec) if vec else 0
            print(f"  {name}: {count} objects, vector dim={dim}")
            break

    print("\nSemantic search:")
    verify_search(client)

    client.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
