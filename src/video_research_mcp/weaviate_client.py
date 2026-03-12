"""Weaviate client singleton — mirrors GeminiClient pattern from client.py.

Provides a process-wide WeaviateClient that lazily connects on first use
and idempotently creates collections from weaviate_schema.ALL_COLLECTIONS.
Used by weaviate_store.py (write-through) and tools/knowledge.py (queries).
"""

from __future__ import annotations

import asyncio
import logging
import os
import threading
from typing import TYPE_CHECKING
from urllib.parse import urlparse

if TYPE_CHECKING:
    import weaviate
    from weaviate.classes.config import DataType, Property

from .config import get_config
from .weaviate_migrate import build_vector_config, migrate_all_if_needed
from .weaviate_schema import CollectionDef, PropertyDef

logger = logging.getLogger(__name__)

_client: weaviate.WeaviateClient | None = None
_async_client: weaviate.WeaviateAsyncClient | None = None
_schema_ensured = False
_lock = threading.Lock()
_async_lock = asyncio.Lock()


def __getattr__(name: str):
    """Lazy-load the weaviate SDK on first access — saves ~290ms at startup.

    Makes ``@patch("...weaviate_client.weaviate")`` work in tests because
    ``patch()`` resolves the attribute via module ``__getattr__``.
    """
    if name == "weaviate":
        import weaviate  # noqa: F811
        globals()["weaviate"] = weaviate
        return weaviate
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _weaviate():
    """Convenience accessor for the lazy-loaded weaviate SDK."""
    return __getattr__("weaviate")


def _resolve_data_type(type_str: str) -> DataType:
    """Map a schema string type name to a Weaviate DataType enum value."""
    from weaviate.classes.config import DataType

    _map: dict[str, DataType] = {
        "text": DataType.TEXT,
        "text[]": DataType.TEXT_ARRAY,
        "int": DataType.INT,
        "number": DataType.NUMBER,
        "boolean": DataType.BOOL,
        "date": DataType.DATE,
    }
    dt = _map.get(type_str)
    if dt is None:
        raise ValueError(f"Unknown data type: {type_str!r}")
    return dt


def _to_property(prop_def: PropertyDef) -> Property:
    """Convert a PropertyDef to a v4 Property object with full index config."""
    from weaviate.classes.config import Property

    kwargs: dict = {
        "name": prop_def.name,
        "data_type": _resolve_data_type(prop_def.data_type[0]),
        "description": prop_def.description or None,
        "skip_vectorization": prop_def.skip_vectorization,
        "index_filterable": prop_def.index_filterable,
        "index_range_filters": prop_def.index_range_filters,
    }
    if prop_def.index_searchable is not None:
        kwargs["index_searchable"] = prop_def.index_searchable
    return Property(**kwargs)


def _timeout_config():
    """Build Weaviate timeout/additional config on first use."""
    from weaviate.classes.init import AdditionalConfig, Timeout

    return AdditionalConfig(timeout=Timeout(init=30, query=60, insert=120))

# Provider API key env vars → Weaviate header names (for third-party vectorizers)
_PROVIDER_HEADER_MAP: dict[str, str] = {
    "OPENAI_API_KEY": "X-OpenAI-Api-Key",
    "COHERE_API_KEY": "X-Cohere-Api-Key",
    "HUGGINGFACE_API_KEY": "X-HuggingFace-Api-Key",
    "JINAAI_API_KEY": "X-JinaAI-Api-Key",
    "VOYAGEAI_API_KEY": "X-VoyageAI-Api-Key",
}


def _collect_provider_headers() -> dict[str, str]:
    """Scan env for third-party vectorizer API keys and return as Weaviate headers."""
    return {
        header: os.environ[env_var]
        for env_var, header in _PROVIDER_HEADER_MAP.items()
        if os.environ.get(env_var)
    }


def _connect(url: str, api_key: str) -> weaviate.WeaviateClient:
    """Connect to Weaviate using the appropriate method for the URL scheme.

    Supports:
        - WCS cloud clusters (https://*.weaviate.network, etc.)
        - Local instances (http://localhost:*, http://127.0.0.1:*)
        - Custom deployments (any other URL)
    """
    wv = _weaviate()
    from weaviate.classes.init import Auth

    additional_config = _timeout_config()
    parsed = urlparse(url)
    host = parsed.hostname or ""
    is_local = host in ("localhost", "127.0.0.1", "::1") or host.startswith("192.168.")

    if is_local:
        port = parsed.port or 8080
        headers = _collect_provider_headers()
        return wv.connect_to_local(
            host=host,
            port=port,
            headers=headers or None,
            additional_config=additional_config,
        )

    headers = _collect_provider_headers()

    if parsed.scheme == "https":
        return wv.connect_to_weaviate_cloud(
            cluster_url=url,
            auth_credentials=Auth.api_key(api_key) if api_key else None,
            headers=headers or None,
            additional_config=additional_config,
        )

    # Custom deployment (non-local, non-WCS)
    return wv.connect_to_custom(
        http_host=host,
        http_port=parsed.port or 8080,
        http_secure=parsed.scheme == "https",
        grpc_host=host,
        grpc_port=(parsed.port or 8080) + 1,
        grpc_secure=parsed.scheme == "https",
        auth_credentials=Auth.api_key(api_key) if api_key else None,
        headers=headers or None,
        additional_config=additional_config,
    )


async def _aconnect(url: str, api_key: str) -> weaviate.WeaviateAsyncClient:
    """Create and connect an async Weaviate client.

    Supports local instances (use_async_with_local) and cloud clusters
    (use_async_with_weaviate_cloud).
    """
    wv = _weaviate()
    from weaviate.classes.init import Auth

    additional_config = _timeout_config()
    headers = _collect_provider_headers()
    parsed = urlparse(url)
    host = parsed.hostname or ""
    is_local = host in ("localhost", "127.0.0.1", "::1") or host.startswith("192.168.")

    if is_local:
        port = parsed.port or 8080
        client = wv.use_async_with_local(
            host=host,
            port=port,
            headers=headers or None,
            additional_config=additional_config,
        )
    else:
        client = wv.use_async_with_weaviate_cloud(
            cluster_url=url,
            auth_credentials=Auth.api_key(api_key) if api_key else None,
            headers=headers or None,
            additional_config=additional_config,
        )
    await client.connect()
    return client


class WeaviateClient:
    """Process-wide Weaviate client singleton (single cluster, not a pool).

    All methods are classmethods operating on module-level _client state.
    Thread-safe via _lock for concurrent asyncio.to_thread usage.
    Async client available via aget() for AsyncQueryAgent.
    """

    @classmethod
    def get(cls) -> weaviate.WeaviateClient:
        """Return (or create) the shared Weaviate client.

        Thread-safe via threading.Lock — safe for concurrent asyncio.to_thread calls.

        Raises:
            ValueError: If WEAVIATE_URL is not configured.
            ConnectionError: If the cluster is unreachable.
        """
        global _client, _schema_ensured
        cfg = get_config()
        if not cfg.weaviate_url:
            raise ValueError("WEAVIATE_URL not configured")

        with _lock:
            if _client is None:
                _client = _connect(cfg.weaviate_url, cfg.weaviate_api_key)
                logger.info("Connected to Weaviate at %s", cfg.weaviate_url)

            if not _schema_ensured:
                cls.ensure_collections()
                _schema_ensured = True

        return _client

    @classmethod
    async def aget(cls) -> weaviate.WeaviateAsyncClient:
        """Return (or create) the shared async Weaviate client.

        For use with AsyncQueryAgent. Supports both local and cloud
        instances. Schema is ensured via the sync client — call get()
        first if collections may not exist yet.

        Raises:
            ValueError: If WEAVIATE_URL is not configured.
        """
        global _async_client
        cfg = get_config()
        if not cfg.weaviate_url:
            raise ValueError("WEAVIATE_URL not configured")

        async with _async_lock:
            if _async_client is None:
                _async_client = await _aconnect(cfg.weaviate_url, cfg.weaviate_api_key)
                logger.info("Async-connected to Weaviate at %s", cfg.weaviate_url)

        return _async_client

    @classmethod
    def ensure_collections(cls) -> None:
        """Idempotent schema creation + evolution for existing deployments.

        Pass 1: create missing collections, evolve existing ones.
        Pass 2: add cross-references (targets must exist first).
        """
        from weaviate.classes.config import Configure

        from .weaviate_schema import ALL_COLLECTIONS

        if _client is None:
            return

        cfg = get_config()
        reranker_cfg = Configure.Reranker.cohere() if cfg.reranker_enabled else None

        existing = set(_client.collections.list_all().keys())
        for col_def in ALL_COLLECTIONS:
            if col_def.name not in existing:
                create_kwargs: dict = {
                    "name": col_def.name,
                    "description": col_def.description,
                    "properties": [_to_property(p) for p in col_def.properties],
                    "vector_config": build_vector_config(col_def),
                }
                if reranker_cfg is not None:
                    create_kwargs["reranker_config"] = reranker_cfg
                _client.collections.create(**create_kwargs)
                logger.info("Created Weaviate collection: %s", col_def.name)
            else:
                cls._evolve_collection(col_def)

        # Pass 2: migrate collections with mismatched vector config.
        # Must run BEFORE _ensure_references so migrated (recreated)
        # collections get their reference schemas back.
        migrate_all_if_needed(_client, ALL_COLLECTIONS, cfg.weaviate_auto_migrate)

        # Pass 3: add cross-references (targets must exist first,
        # and migrated collections need their references restored).
        cls._ensure_references(ALL_COLLECTIONS)

    @classmethod
    def _evolve_collection(cls, col_def: CollectionDef) -> None:
        """Add missing properties and update reranker config on existing collections."""
        from weaviate.classes.config import Reconfigure

        col = _client.collections.get(col_def.name)
        existing_props = {p.name for p in col.config.get().properties}

        for prop_def in col_def.properties:
            if prop_def.name in existing_props:
                continue
            try:
                col.config.add_property(_to_property(prop_def))
                logger.info("Added property %s.%s", col_def.name, prop_def.name)
            except Exception as exc:
                logger.debug("Property %s.%s already exists or failed: %s", col_def.name, prop_def.name, exc)

        if get_config().reranker_enabled:
            try:
                col.config.update(reranker_config=Reconfigure.Reranker.cohere())
            except Exception as exc:
                logger.debug("Reranker config for %s: %s", col_def.name, exc)

    @classmethod
    def _ensure_references(cls, collections: list[CollectionDef]) -> None:
        """Add missing cross-references (second pass, targets must exist)."""
        from weaviate.classes.config import ReferenceProperty

        for col_def in collections:
            if not col_def.references:
                continue
            col = _client.collections.get(col_def.name)
            for ref_def in col_def.references:
                try:
                    col.config.add_reference(ReferenceProperty(
                        name=ref_def.name,
                        target_collection=ref_def.target_collection,
                    ))
                    logger.info("Added reference %s.%s → %s", col_def.name, ref_def.name, ref_def.target_collection)
                except Exception as exc:
                    logger.debug("Reference %s.%s already exists or failed: %s", col_def.name, ref_def.name, exc)

    @classmethod
    def is_available(cls) -> bool:
        """Check if Weaviate is configured and reachable."""
        cfg = get_config()
        if not cfg.weaviate_enabled:
            return False
        try:
            cls.get()
            return _client is not None and _client.is_ready()
        except Exception:
            return False

    @classmethod
    def close(cls) -> None:
        """Close the shared sync client connection."""
        global _client, _schema_ensured
        with _lock:
            if _client is not None:
                try:
                    _client.close()
                except Exception:
                    pass
                _client = None
                _schema_ensured = False
                logger.info("Closed Weaviate client")

    @classmethod
    async def aclose(cls) -> None:
        """Close both sync and async clients."""
        global _async_client
        await asyncio.to_thread(cls.close)
        async with _async_lock:
            if _async_client is not None:
                try:
                    await _async_client.close()
                except Exception:
                    pass
                _async_client = None
                logger.info("Closed async Weaviate client")

    @classmethod
    def reset(cls) -> None:
        """Reset singleton state (testing utility, matches YouTubeClient.reset)."""
        global _client, _async_client, _schema_ensured
        _client = None
        _async_client = None
        _schema_ensured = False
