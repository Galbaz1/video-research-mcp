"""Migrate all Weaviate data from cloud to local Docker instance.

One-time migration script. Exports all objects (with vectors) from the
cloud cluster and imports them into the local instance.

Usage:
    uv run python scripts/migrate_cloud_to_local.py
"""

from __future__ import annotations

import os
import sys
import time

import weaviate
from weaviate.classes.init import AdditionalConfig, Auth, Timeout
from weaviate.classes.query import MetadataQuery

CLOUD_URL = "https://xbn6jeforsib1nlqjsselw.c0.europe-west3.gcp.weaviate.cloud"
CLOUD_KEY = "UzdFUTA5Rm9VVDQ0b3FZdF9pczVrL2pBaDhrdHV5a3hGeHJSb04rUUdaSTdEZ1JaS3U5ck5scXFoa0R3PV92MjAw"
LOCAL_URL = "http://localhost:8080"

BATCH_SIZE = 100


def connect_cloud() -> weaviate.WeaviateClient:
    """Connect to Weaviate Cloud cluster."""
    return weaviate.connect_to_weaviate_cloud(
        cluster_url=CLOUD_URL,
        auth_credentials=Auth.api_key(CLOUD_KEY),
        additional_config=AdditionalConfig(timeout=Timeout(init=60, query=120)),
        skip_init_checks=True,
    )


def connect_local() -> weaviate.WeaviateClient:
    """Connect to local Weaviate Docker instance."""
    openai_key = os.environ.get("OPENAI_API_KEY", "")
    headers = {"X-OpenAI-Api-Key": openai_key} if openai_key else None
    return weaviate.connect_to_local(
        headers=headers,
        additional_config=AdditionalConfig(
            timeout=Timeout(init=30, query=60, insert=120),
        ),
    )


def migrate_collection(
    cloud: weaviate.WeaviateClient,
    local: weaviate.WeaviateClient,
    name: str,
) -> int:
    """Migrate all objects from one collection, preserving UUIDs and vectors."""
    source = cloud.collections.get(name)
    target = local.collections.get(name)

    count = source.aggregate.over_all(total_count=True).total_count
    if count == 0:
        return 0

    migrated = 0
    with target.batch.fixed_size(batch_size=BATCH_SIZE) as batch:
        for obj in source.iterator(
            include_vector=True,
            return_metadata=MetadataQuery(creation_time=True),
        ):
            batch.add_object(
                properties=obj.properties,
                uuid=obj.uuid,
                vector=obj.vector.get("default") if obj.vector else None,
            )
            migrated += 1

    return migrated


def main() -> None:
    """Run the migration."""
    print("Connecting to cloud...")
    cloud = connect_cloud()
    print(f"  Cloud ready: {cloud.is_ready()}")

    print("Connecting to local...")
    local = connect_local()
    print(f"  Local ready: {local.is_ready()}")

    collections = sorted(cloud.collections.list_all().keys())
    print(f"\nMigrating {len(collections)} collections...")

    start = time.time()
    total = 0

    for name in collections:
        cloud_count = cloud.collections.get(name).aggregate.over_all(
            total_count=True
        ).total_count
        if cloud_count == 0:
            print(f"  {name}: empty, skipping")
            continue

        migrated = migrate_collection(cloud, local, name)
        total += migrated
        print(f"  {name}: {migrated}/{cloud_count} objects migrated")

    elapsed = time.time() - start
    print(f"\nDone: {total} objects migrated in {elapsed:.1f}s")

    # Verify counts
    print("\nVerification:")
    for name in collections:
        cloud_count = cloud.collections.get(name).aggregate.over_all(
            total_count=True
        ).total_count
        local_count = local.collections.get(name).aggregate.over_all(
            total_count=True
        ).total_count
        status = "OK" if cloud_count == local_count else "MISMATCH"
        if cloud_count > 0:
            print(f"  {name}: cloud={cloud_count} local={local_count} [{status}]")

    cloud.close()
    local.close()


if __name__ == "__main__":
    main()
