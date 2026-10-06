"""Vector config migration for Weaviate collections.

Builds vectorizer configs with explicit source_properties derived from
CollectionDef schemas, and handles auto-migration when existing collections
have mismatched vector configs (e.g. missing source_properties after
cloud-to-local migration, or vectorizer provider changes).
"""

from __future__ import annotations

import os

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
    if cfg.weaviate_vectorizer == "ollama":
        api_endpoint = os.environ.get(
            "WEAVIATE_OLLAMA_API_ENDPOINT", "http://host.docker.internal:11434"
        )
        model = os.environ.get("WEAVIATE_OLLAMA_MODEL", "nomic-embed-text")
        return Configure.Vectors.text2vec_ollama(
            source_properties=source_props,
            api_endpoint=api_endpoint,
            model=model,
        )
    return Configure.Vectors.text2vec_openai(source_properties=source_props)


def _get_vectorizer(col_config: Any) -> Any | None:
    """Navigate runtime config to the vectorizer object.

    Shared navigation for _get_current_source_properties and
    _get_current_vectorizer_module — defensive against SDK shape changes.
    """
    vc = getattr(col_config, "vector_config", None)
    if not vc or not isinstance(vc, dict):
        return None
    named = vc.get("default")
    if named is None:
        return None
    return getattr(named, "vectorizer", None)


def _get_current_source_properties(col_config: Any) -> list[str] | None:
    """Safely extract source_properties from runtime collection config."""
    vectorizer = _get_vectorizer(col_config)
    if vectorizer is None:
        return None
    return getattr(vectorizer, "source_properties", None)


def _get_current_vectorizer_module(col_config: Any) -> str | None:
    """Safely extract vectorizer module name from runtime collection config.

    Returns a lowercase string like "text2vec-openai", or None if
    the config shape doesn't match or the module is unrecognized.
    """
    vectorizer = _get_vectorizer(col_config)
    if vectorizer is None:
        return None
    module = getattr(vectorizer, "vectorizer", None)
    if module is None:
        return None
    # Handle both Vectorizers enum (.value) and plain strings
    module_str = getattr(module, "value", None)
    if not isinstance(module_str, str):
        module_str = str(module)
    result = module_str.lower()
    # Sanity check: must be a recognizable Weaviate vectorizer name
    if not result.startswith(("text2vec-", "img2vec-", "multi2vec-", "ref2vec-")):
        return None
    return result


def _desired_vectorizer_module() -> str:
    """Return the vectorizer module name matching current config."""
    cfg = get_config()
    mapping = {"weaviate": "text2vec-weaviate", "ollama": "text2vec-ollama"}
    return mapping.get(cfg.weaviate_vectorizer, "text2vec-openai")


def needs_vector_migration(col_config: Any, col_def: CollectionDef) -> bool:
    """Check if source_properties or vectorizer mismatch requires migration.

    Args:
        col_config: Runtime config from collection.config.get().
        col_def: Desired collection definition.

    Returns:
        True if migration is needed.
    """
    current_props = _get_current_source_properties(col_config)
    desired_props = col_def.vectorized_properties() or None

    props_match = current_props == desired_props
    if not props_match and current_props is not None and desired_props is not None:
        props_match = set(current_props) == set(desired_props)

    if not props_match:
        return True

    # Check vectorizer module (text2vec-openai vs text2vec-weaviate)
    current_module = _get_current_vectorizer_module(col_config)
    if current_module is not None and current_module != _desired_vectorizer_module():
        return True

    return False


def _export_objects(col: Any, col_def: CollectionDef) -> list[dict]:
    """Export all objects from a collection, including cross-reference edges.

    Args:
        col: Weaviate collection handle.
        col_def: Collection definition (used for reference names).

    Returns:
        List of dicts with uuid, properties, and references.
    """
    from weaviate.classes.query import MetadataQuery

    ref_names = [r.name for r in col_def.references]
    iterator_kwargs: dict = {"return_metadata": MetadataQuery(creation_time=True)}
    if ref_names:
        from weaviate.classes.query import QueryReference

        iterator_kwargs["return_references"] = [
            QueryReference(link_on=rn) for rn in ref_names
        ]

    objects: list[dict] = []
    for obj in col.iterator(**iterator_kwargs):
        refs: dict[str, list] = {}
        if ref_names and obj.references:
            for rn, cross_refs in obj.references.items():
                target_uuids = [
                    getattr(cr, "uuid", None)
                    for cr in getattr(cross_refs, "objects", [])
                ]
                refs[rn] = [u for u in target_uuids if u is not None]
        objects.append({
            "uuid": obj.uuid,
            "properties": dict(obj.properties),
            "references": refs,
        })
    return objects


def _restore_references(col: Any, col_def: CollectionDef, objects: list[dict]) -> None:
    """Restore reference schema and edges after collection migration.

    Args:
        col: Weaviate collection handle (post-recreation).
        col_def: Collection definition with reference definitions.
        objects: Exported objects with their reference edges.
    """
    if not col_def.references:
        return

    from weaviate.classes.config import ReferenceProperty

    for ref_def in col_def.references:
        try:
            col.config.add_reference(ReferenceProperty(
                name=ref_def.name,
                target_collection=ref_def.target_collection,
            ))
        except Exception as exc:
            logger.debug("Reference %s.%s: %s", col_def.name, ref_def.name, exc)

    ref_count = 0
    for obj in objects:
        for ref_name, target_uuids in obj["references"].items():
            for target_uuid in target_uuids:
                try:
                    col.data.reference_add(
                        from_uuid=obj["uuid"],
                        from_property=ref_name,
                        to=target_uuid,
                    )
                    ref_count += 1
                except Exception as exc:
                    logger.warning(
                        "Failed to restore ref %s on %s: %s",
                        ref_name, obj["uuid"], exc,
                    )
    if ref_count:
        logger.info("Restored %d reference edges in %s", ref_count, col_def.name)


def migrate_collection(client: weaviate.WeaviateClient, col_def: CollectionDef) -> None:
    """Recreate an empty collection; refuse populated destructive migration.

    An in-memory export cannot recover from process loss after deletion.

    Args:
        client: Connected Weaviate client.
        col_def: Collection definition with correct vectorization flags.

    Raises:
        RuntimeError: If the collection contains objects without durable recovery.
    """
    from weaviate.classes.config import Configure

    from .weaviate_client import _to_property

    name = col_def.name
    col = client.collections.get(name)
    if next(iter(col.iterator()), None) is not None:
        raise RuntimeError(
            f"Refusing automatic migration of populated collection {name!r}: "
            "no durable recovery export is available"
        )

    cfg = get_config()
    create_kwargs: dict = {
        "name": name,
        "description": col_def.description,
        "properties": [_to_property(p) for p in col_def.properties],
        "vector_config": build_vector_config(col_def),
    }
    if cfg.reranker_enabled:
        create_kwargs["reranker_config"] = Configure.Reranker.cohere()
    client.collections.delete(name)
    client.collections.create(**create_kwargs)
    logger.info("Recreated empty %s with updated vector config", name)


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
            if auto_migrate:
                raise
            logger.debug("Cannot check %s vector config: %s", col_def.name, exc)
            continue

        if not needs_vector_migration(col_config, col_def):
            continue

        if not auto_migrate:
            logger.warning(
                "Collection %s has mismatched vector config "
                "(source_properties or vectorizer). "
                "Automatic migration recreates empty collections only; "
                "populated collections require durable external recovery.",
                col_def.name,
            )
            continue

        logger.info("Migrating %s (vector config mismatch)...", col_def.name)
        migrate_collection(client, col_def)
