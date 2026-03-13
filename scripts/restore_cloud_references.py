"""Restore cross-reference edges from cloud Weaviate to local Docker.

One-time script. The cloud→local migration (migrate_cloud_to_local.py) and
re-vectorization (revectorize_openai.py) both dropped cross-reference edges.
This script reads edges from cloud and applies them to local.

Also copies any objects that exist in cloud but not in local.

Usage:
    uv run python scripts/restore_cloud_references.py
"""

from __future__ import annotations

import os
import sys
import time

import weaviate
from weaviate.classes.init import AdditionalConfig, Auth, Timeout
from weaviate.classes.query import MetadataQuery, QueryReference

CLOUD_URL = "https://xbn6jeforsib1nlqjsselw.c0.europe-west3.gcp.weaviate.cloud"
CLOUD_KEY = (
    "UzdFUTA5Rm9VVDQ0b3FZdF9pczVrL2pBaDhrdHV5a3hGeHJSb04r"
    "UUdaSTdEZ1JaS3U5ck5scXFoa0R3PV92MjAw"
)

# Collections with cross-references and their reference property names
REF_COLLECTIONS: dict[str, list[str]] = {
    "VideoAnalyses": ["has_metadata"],
    "DeepResearchReports": ["related_findings", "related_web_searches"],
    "ResearchFindings": ["belongs_to_report"],
    "CommunityReactions": ["for_video"],
}


def connect_cloud() -> weaviate.WeaviateClient:
    """Connect to Weaviate Cloud cluster."""
    return weaviate.connect_to_weaviate_cloud(
        cluster_url=CLOUD_URL,
        auth_credentials=Auth.api_key(CLOUD_KEY),
        additional_config=AdditionalConfig(timeout=Timeout(init=30, query=60)),
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


def export_reference_edges(
    client: weaviate.WeaviateClient,
    col_name: str,
    ref_names: list[str],
) -> list[dict]:
    """Export all cross-reference edges from a cloud collection.

    Returns:
        List of {from_uuid, ref_name, to_uuid} dicts.
    """
    col = client.collections.get(col_name)
    config = col.config.get()
    schema_refs = {p.name for p in config.references}

    valid_refs = [rn for rn in ref_names if rn in schema_refs]
    if not valid_refs:
        return []

    refs = [QueryReference(link_on=rn) for rn in valid_refs]
    edges: list[dict] = []
    for obj in col.iterator(return_references=refs):
        if not obj.references:
            continue
        for ref_name, cross_refs in obj.references.items():
            if not cross_refs or not hasattr(cross_refs, "objects"):
                continue
            for cr in cross_refs.objects:
                uuid = getattr(cr, "uuid", None)
                if uuid is not None:
                    edges.append({
                        "from_uuid": str(obj.uuid),
                        "ref_name": ref_name,
                        "to_uuid": str(uuid),
                    })

    return edges


def apply_reference_edges(
    client: weaviate.WeaviateClient,
    col_name: str,
    edges: list[dict],
) -> tuple[int, int]:
    """Apply reference edges to local collection.

    Returns:
        (success_count, failure_count) tuple.
    """
    if not edges:
        return 0, 0

    col = client.collections.get(col_name)
    success = 0
    failed = 0
    for edge in edges:
        try:
            col.data.reference_add(
                from_uuid=edge["from_uuid"],
                from_property=edge["ref_name"],
                to=edge["to_uuid"],
            )
            success += 1
        except Exception as exc:
            failed += 1
            if failed <= 3:
                print(f"    FAIL: {edge['ref_name']} {edge['from_uuid'][:8]}→{edge['to_uuid'][:8]}: {exc}")
    return success, failed


def copy_missing_objects(
    cloud: weaviate.WeaviateClient,
    local: weaviate.WeaviateClient,
) -> int:
    """Copy objects that exist in cloud but not in local.

    Compares counts per collection and copies missing UUIDs.
    """
    collections = sorted(cloud.collections.list_all().keys())
    total_copied = 0

    for name in collections:
        cloud_col = cloud.collections.get(name)
        local_col = local.collections.get(name)

        cloud_count = cloud_col.aggregate.over_all(total_count=True).total_count
        local_count = local_col.aggregate.over_all(total_count=True).total_count

        if cloud_count <= local_count:
            continue

        # Collect local UUIDs
        local_uuids = set()
        for obj in local_col.iterator():
            local_uuids.add(str(obj.uuid))

        # Find and copy missing objects
        copied = 0
        with local_col.batch.fixed_size(batch_size=50) as batch:
            for obj in cloud_col.iterator(
                return_metadata=MetadataQuery(creation_time=True),
            ):
                if str(obj.uuid) not in local_uuids:
                    batch.add_object(
                        properties=obj.properties,
                        uuid=obj.uuid,
                    )
                    copied += 1

        if copied:
            print(f"  {name}: copied {copied} missing objects")
            total_copied += copied

    return total_copied


def main() -> None:
    """Restore reference edges from cloud to local."""
    print("Connecting to cloud...")
    cloud = connect_cloud()
    print(f"  Cloud ready: {cloud.is_ready()}")

    print("Connecting to local...")
    local = connect_local()
    print(f"  Local ready: {local.is_ready()}")

    # Phase 1: copy missing objects
    print("\n=== Phase 1: Copy missing objects ===\n")
    copied = copy_missing_objects(cloud, local)
    if copied:
        print(f"\n  Total: {copied} objects copied")
    else:
        print("  No missing objects found")

    # Phase 2: export and apply reference edges
    print("\n=== Phase 2: Restore reference edges ===\n")
    start = time.time()
    total_edges = 0
    total_failed = 0

    for col_name, ref_names in REF_COLLECTIONS.items():
        edges = export_reference_edges(cloud, col_name, ref_names)
        if not edges:
            print(f"  {col_name}: no edges to restore")
            continue

        print(f"  {col_name}: {len(edges)} edges found in cloud")
        success, failed = apply_reference_edges(local, col_name, edges)
        print(f"  {col_name}: {success} restored, {failed} failed")
        total_edges += success
        total_failed += failed

    elapsed = time.time() - start
    print(f"\n  Total: {total_edges} edges restored, {total_failed} failed in {elapsed:.1f}s")

    # Phase 3: verify
    print("\n=== Verification ===\n")
    for col_name, ref_names in REF_COLLECTIONS.items():
        col = local.collections.get(col_name)
        count = col.aggregate.over_all(total_count=True).total_count
        if count == 0:
            continue

        edges_found = 0
        refs = [QueryReference(link_on=rn) for rn in ref_names]
        try:
            for obj in col.iterator(return_references=refs):
                if obj.references:
                    for _rn, cr in obj.references.items():
                        if cr and hasattr(cr, "objects") and cr.objects:
                            edges_found += len(cr.objects)
        except Exception as exc:
            print(f"  {col_name}: verification error: {exc}")
            continue
        print(f"  {col_name}: {edges_found} edges verified")

    cloud.close()
    local.close()
    print("\nDone.")


if __name__ == "__main__":
    main()
