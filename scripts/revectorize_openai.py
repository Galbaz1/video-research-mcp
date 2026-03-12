"""Re-vectorize all Weaviate objects with OpenAI embeddings.

One-time script. Migrated objects have vectors from text2vec-weaviate (cloud).
Local Docker uses text2vec-openai. Updating each object without a vector
triggers the vectorizer to recompute embeddings via the OpenAI API.

Usage:
    OPENAI_API_KEY=... uv run python scripts/revectorize_openai.py
"""

from __future__ import annotations

import os
import sys
import time

import weaviate
from weaviate.classes.init import AdditionalConfig, Timeout
from weaviate.classes.query import MetadataQuery

BATCH_SIZE = 100


def connect() -> weaviate.WeaviateClient:
    """Connect to local Weaviate with OpenAI API key header."""
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    if not openai_key:
        print("ERROR: OPENAI_API_KEY not set")
        sys.exit(1)

    return weaviate.connect_to_local(
        headers={"X-OpenAI-Api-Key": openai_key},
        additional_config=AdditionalConfig(
            timeout=Timeout(init=30, query=60, insert=300),
        ),
    )


def revectorize_collection(client: weaviate.WeaviateClient, name: str) -> int:
    """Re-vectorize all objects in a collection by updating without a vector.

    Iterates all objects, then updates each with its own properties
    (no vector arg). This forces text2vec-openai to recompute the embedding.
    """
    col = client.collections.get(name)
    count = col.aggregate.over_all(total_count=True).total_count
    if count == 0:
        return 0

    updated = 0
    for obj in col.iterator(return_metadata=MetadataQuery(creation_time=True)):
        col.data.update(uuid=obj.uuid, properties=obj.properties)
        updated += 1
        if updated % 100 == 0:
            print(f"    {updated}/{count}...")

    return updated


def main() -> None:
    """Re-vectorize all collections."""
    print("Connecting to local Weaviate...")
    client = connect()
    print(f"  Ready: {client.is_ready()}")

    collections = sorted(client.collections.list_all().keys())
    print(f"\nRe-vectorizing {len(collections)} collections...\n")

    start = time.time()
    total = 0

    for name in collections:
        col = client.collections.get(name)
        count = col.aggregate.over_all(total_count=True).total_count
        if count == 0:
            print(f"  {name}: empty, skipping")
            continue

        print(f"  {name}: {count} objects...")
        t0 = time.time()
        done = revectorize_collection(client, name)
        elapsed = time.time() - t0
        total += done
        print(f"  {name}: {done} re-vectorized in {elapsed:.1f}s")

    elapsed = time.time() - start
    print(f"\nDone: {total} objects re-vectorized in {elapsed:.1f}s")

    # Quick verification: spot-check that vectors changed
    print("\nVerification (vector dimensions):")
    for name in collections:
        col = client.collections.get(name)
        count = col.aggregate.over_all(total_count=True).total_count
        if count == 0:
            continue
        sample = list(col.iterator(include_vector=True, return_metadata=MetadataQuery(creation_time=True)))
        if sample:
            vec = sample[0].vector.get("default", [])
            dim = len(vec) if vec else 0
            print(f"  {name}: {count} objects, vector dim={dim}")

    client.close()


if __name__ == "__main__":
    main()
