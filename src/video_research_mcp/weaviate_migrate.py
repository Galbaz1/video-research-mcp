"""Vector config migration for Weaviate collections.

Builds vectorizer configs with explicit source_properties derived from
CollectionDef schemas, and handles auto-migration when existing collections
have mismatched vector configs (e.g. missing source_properties after
cloud-to-local migration).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .config import get_config

if TYPE_CHECKING:
    import weaviate

    from .weaviate_schema import CollectionDef

logger = logging.getLogger(__name__)


def build_vector_config(col_def: CollectionDef) -> Any:
    """Build vector config with source_properties from schema + configured vectorizer.

    Args:
        col_def: Collection definition with property-level skip_vectorization flags.

    Returns:
        A _VectorConfigCreate for use in client.collections.create().
    """
    from weaviate.classes.config import Configure

    cfg = get_config()
    source_props = col_def.vectorized_properties() or None
    if cfg.weaviate_vectorizer == "weaviate":
        return Configure.Vectors.text2vec_weaviate(source_properties=source_props)
    return Configure.Vectors.text2vec_openai(source_properties=source_props)


def _get_current_source_properties(col_config: Any) -> list[str] | None:
    """Safely extract source_properties from runtime collection config.

    Returns None if config shape doesn't match (defensive against SDK changes).
    """
    vc = getattr(col_config, "vector_config", None)
    if not vc or not isinstance(vc, dict):
        return None
    named = vc.get("default")
    if named is None:
        return None
    vectorizer = getattr(named, "vectorizer", None)
    if vectorizer is None:
        return None
    return getattr(vectorizer, "source_properties", None)


def needs_vector_migration(col_config: Any, col_def: CollectionDef) -> bool:
    """Check if source_properties mismatch requires migration.

    Args:
        col_config: Runtime config from collection.config.get().
        col_def: Desired collection definition.

    Returns:
        True if migration is needed.
    """
    current = _get_current_source_properties(col_config)
    desired = col_def.vectorized_properties() or None

    if current == desired:
        return False
    if current is not None and desired is not None:
        if set(current) == set(desired):
            return False
    return True


def migrate_collection(client: weaviate.WeaviateClient, col_def: CollectionDef) -> None:
    """Export, delete, recreate, re-insert with correct source_properties.

    Cross-references are NOT preserved (consistent with revectorize_openai.py).
    Reference schema is restored by _ensure_references() after migration.

    Args:
        client: Connected Weaviate client.
        col_def: Collection definition with correct vectorization flags.
    """
    from weaviate.classes.query import MetadataQuery

    from .weaviate_client import _to_property

    name = col_def.name
    col = client.collections.get(name)

    # Phase 1: export
    objects: list[dict] = []
    for obj in col.iterator(return_metadata=MetadataQuery(creation_time=True)):
        objects.append({"uuid": obj.uuid, "properties": dict(obj.properties)})
    logger.info("Exported %d objects from %s", len(objects), name)

    # Phase 2: delete and recreate
    client.collections.delete(name)

    cfg = get_config()
    from weaviate.classes.config import Configure

    create_kwargs: dict = {
        "name": name,
        "description": col_def.description,
        "properties": [_to_property(p) for p in col_def.properties],
        "vector_config": build_vector_config(col_def),
    }
    if cfg.reranker_enabled:
        create_kwargs["reranker_config"] = Configure.Reranker.cohere()
    client.collections.create(**create_kwargs)
    logger.info("Recreated %s with source_properties", name)

    # Phase 3: re-insert
    if not objects:
        return

    col = client.collections.get(name)
    with col.batch.fixed_size(batch_size=100) as batch:
        for obj in objects:
            batch.add_object(properties=obj["properties"], uuid=obj["uuid"])

    if col.batch.failed_objects:
        failed = len(col.batch.failed_objects)
        logger.warning(
            "%d batch failures in %s migration", failed, name,
        )
        for err in col.batch.failed_objects[:3]:
            logger.warning("  %s", getattr(err, "message", str(err)))
    else:
        logger.info("Re-inserted %d objects into %s", len(objects), name)


def migrate_all_if_needed(
    client: weaviate.WeaviateClient,
    collections: list[CollectionDef],
    auto_migrate: bool,
) -> None:
    """Check all collections and migrate if needed and allowed.

    When auto_migrate=False, logs warnings for mismatched collections
    without performing destructive operations.

    Args:
        client: Connected Weaviate client.
        collections: All collection definitions to check.
        auto_migrate: Whether to perform destructive migration.
    """
    for col_def in collections:
        try:
            col = client.collections.get(col_def.name)
            col_config = col.config.get()
        except Exception as exc:
            logger.debug("Cannot check %s vector config: %s", col_def.name, exc)
            continue

        if not needs_vector_migration(col_config, col_def):
            continue

        if not auto_migrate:
            logger.warning(
                "Collection %s has mismatched source_properties. "
                "Set WEAVIATE_AUTO_MIGRATE=true to auto-fix, or run "
                "scripts/revectorize_openai.py manually.",
                col_def.name,
            )
            continue

        logger.info("Migrating %s (source_properties mismatch)...", col_def.name)
        try:
            migrate_collection(client, col_def)
        except Exception as exc:
            logger.error("Migration failed for %s: %s", col_def.name, exc)
