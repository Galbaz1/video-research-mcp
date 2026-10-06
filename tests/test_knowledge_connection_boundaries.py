"""Fake-provider boundaries for Weaviate admission and paper URL construction."""

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from video_research_mcp import academic_client, weaviate_client, weaviate_migrate
from video_research_mcp.weaviate_schema import CollectionDef


@pytest.fixture()
def boundary_state(monkeypatch):
    """Supply fake configuration, provider keys, SDK constructors, and client state."""
    cfg = SimpleNamespace(
        weaviate_vectorizer="weaviate", reranker_enabled=False,
        weaviate_url="https://cluster.invalid", weaviate_api_key="fake-cluster-key",
        weaviate_auto_migrate=True,
    )
    monkeypatch.setattr(weaviate_client, "get_config", lambda: cfg)
    monkeypatch.setattr(weaviate_migrate, "get_config", lambda: cfg)
    monkeypatch.setattr(weaviate_client, "_client", None)
    monkeypatch.setattr(weaviate_client, "_schema_ensured", False)
    for provider in ("OPENAI", "COHERE", "HUGGINGFACE", "JINAAI", "VOYAGEAI"):
        monkeypatch.setenv(f"{provider}_API_KEY", f"fake-{provider.lower()}")
    sdk = MagicMock()
    monkeypatch.setattr(weaviate_client, "_weaviate", lambda: sdk)
    monkeypatch.setattr(weaviate_client, "_timeout_config", lambda: "fake-timeout")
    init = ModuleType("weaviate.classes.init")
    init.Auth = MagicMock()
    config = ModuleType("weaviate.classes.config")
    config.Configure = MagicMock()
    config.Reconfigure = MagicMock()
    config.ReferenceProperty = MagicMock()
    query = ModuleType("weaviate.classes.query")
    query.MetadataQuery = MagicMock()
    query.QueryReference = MagicMock()
    for name, module in ((init.__name__, init), (config.__name__, config), (query.__name__, query)):
        monkeypatch.setitem(sys.modules, name, module)
    return cfg, sdk, config


@pytest.mark.parametrize("vectorizer", ["openai", "weaviate", "ollama"])
@pytest.mark.parametrize("reranker", [False, True])
def test_only_selected_provider_credentials(boundary_state, vectorizer, reranker):
    """Unrelated fake keys stay outside the configured cluster's headers."""
    cfg, _, _ = boundary_state
    cfg.weaviate_vectorizer = vectorizer
    cfg.reranker_enabled = reranker
    expected = {}
    if vectorizer == "openai":
        expected["X-OpenAI-Api-Key"] = "fake-openai"
    if reranker:
        expected["X-Cohere-Api-Key"] = "fake-cohere"
    assert weaviate_client._collect_provider_headers() == expected


def test_missing_selected_keys_are_not_fabricated(boundary_state, monkeypatch):
    """Configured capabilities do not manufacture missing credentials."""
    cfg, _, _ = boundary_state
    cfg.weaviate_vectorizer = "openai"
    cfg.reranker_enabled = True
    monkeypatch.delenv("OPENAI_API_KEY")
    monkeypatch.delenv("COHERE_API_KEY")
    assert weaviate_client._collect_provider_headers() == {}


@pytest.mark.parametrize("url, method", [
    ("http://localhost:8080", "connect_to_local"),
    ("https://cluster.invalid", "connect_to_weaviate_cloud"),
    ("http://cluster.invalid:8080", "connect_to_custom"),
])
@pytest.mark.parametrize("reranker", [False, True])
def test_sync_routes_use_selected_headers(boundary_state, url, method, reranker):
    """Every sync connector forwards only the selected reranker credential."""
    cfg, sdk, _ = boundary_state
    cfg.reranker_enabled = reranker
    connection = weaviate_client._connect(url, "fake-cluster-key")
    connector = getattr(sdk, method)
    assert connection is connector.return_value
    expected = {"X-Cohere-Api-Key": "fake-cohere"} if reranker else None
    assert connector.call_args.kwargs["headers"] == expected


@pytest.mark.parametrize("url, method", [
    ("http://localhost:8080", "use_async_with_local"),
    ("https://cluster.invalid", "use_async_with_weaviate_cloud"),
])
@pytest.mark.parametrize("reranker", [False, True])
async def test_async_routes_use_selected_headers(boundary_state, url, method, reranker):
    """Async connectors preserve filtering before the fake client connects."""
    cfg, sdk, _ = boundary_state
    cfg.reranker_enabled = reranker
    connector = getattr(sdk, method)
    connector.return_value.connect = AsyncMock()
    connection = await weaviate_client._aconnect(url, "fake-cluster-key")
    assert connection is connector.return_value
    expected = {"X-Cohere-Api-Key": "fake-cohere"} if reranker else None
    assert connector.call_args.kwargs["headers"] == expected
    connection.connect.assert_awaited_once()


@pytest.fixture()
def collection_client():
    """Provide a mismatched empty collection with no real database connection."""
    definition = CollectionDef(name="BoundaryCollection")
    vectorizer = SimpleNamespace(source_properties=["old"], vectorizer="text2vec-openai")
    config = SimpleNamespace(
        properties=[], vector_config={"default": SimpleNamespace(vectorizer=vectorizer)},
    )
    client = MagicMock()
    collection = client.collections.get.return_value
    collection.config.get.return_value = config
    collection.iterator.return_value = []
    client.collections.list_all.return_value = {definition.name: None}
    return definition, client, collection


def test_populated_migration_refuses_before_delete(boundary_state, collection_client):
    """GIVEN an object, WHEN migration starts, THEN no delete or restore is attempted."""
    definition, client, collection = collection_client
    seen = []

    def objects(**_kwargs):
        seen.append("first")
        yield SimpleNamespace(uuid="fake-uuid", properties={"title": "retained"})
        seen.append("second")
        yield SimpleNamespace(uuid="fake-second", properties={})

    collection.iterator.side_effect = objects
    with pytest.raises(RuntimeError, match="populated.*durable recovery"):
        weaviate_migrate.migrate_collection(client, definition)
    client.collections.delete.assert_not_called()
    client.collections.create.assert_not_called()
    collection.batch.fixed_size.assert_not_called()
    assert seen == ["first"]


def test_iterator_failure_prevents_delete(boundary_state, collection_client):
    """An unverified empty collection is never admitted to deletion."""
    definition, client, collection = collection_client
    collection.iterator.side_effect = ConnectionError("fake inspection failure")
    with pytest.raises(ConnectionError, match="fake inspection failure"):
        weaviate_migrate.migrate_collection(client, definition)
    client.collections.delete.assert_not_called()


@pytest.mark.parametrize("reranker", [False, True])
def test_empty_migration_preserves_selected_configuration(boundary_state, collection_client, reranker):
    """Verified empty iteration permits recreation with the existing provider choices."""
    cfg, _, sdk_config = boundary_state
    cfg.reranker_enabled = reranker
    definition, client, _ = collection_client
    weaviate_migrate.migrate_collection(client, definition)
    client.collections.delete.assert_called_once_with(definition.name)
    create = client.collections.create.call_args.kwargs
    assert create["vector_config"] is sdk_config.Configure.Vectors.text2vec_weaviate.return_value
    assert create["name"] == definition.name
    if reranker:
        assert create["reranker_config"] is sdk_config.Configure.Reranker.cohere.return_value
    else:
        assert "reranker_config" not in create


def test_disabled_migration_preserves_populated_collection(boundary_state, collection_client):
    """The disabled default performs no inspection, deletion, or recreation."""
    definition, client, collection = collection_client
    weaviate_migrate.migrate_all_if_needed(client, [definition], auto_migrate=False)
    collection.iterator.assert_not_called()
    client.collections.delete.assert_not_called()
    client.collections.create.assert_not_called()


@pytest.mark.parametrize("failure", ["populated", "create", "iterator"])
def test_admission_failure_keeps_schema_unensured(boundary_state, collection_client, monkeypatch, failure):
    """GIVEN failed migration, WHEN get runs twice, THEN failure propagates on both attempts."""
    from video_research_mcp import weaviate_schema

    definition, client, collection = collection_client
    monkeypatch.setattr(weaviate_schema, "ALL_COLLECTIONS", [definition])
    monkeypatch.setattr(weaviate_client, "_connect", lambda url, key: client)
    if failure == "populated":
        collection.iterator.return_value = [SimpleNamespace(uuid="fake-uuid", properties={})]
    elif failure == "create":
        client.collections.create.side_effect = RuntimeError("fake recreation failure")
    else:
        collection.iterator.side_effect = RuntimeError("fake inspection failure")
    for _ in range(2):
        with pytest.raises(RuntimeError):
            weaviate_client.WeaviateClient.get()
        assert weaviate_client._schema_ensured is False
    if failure != "create":
        client.collections.delete.assert_not_called()


@pytest.mark.parametrize("enabled", [False, True])
def test_configuration_check_failure_is_not_admitted(boundary_state, collection_client, enabled):
    """Opt-in migration requires a successful external schema check."""
    definition, client, collection = collection_client
    collection.config.get.side_effect = ConnectionError("fake schema check failure")
    if enabled:
        with pytest.raises(ConnectionError, match="fake schema check failure"):
            weaviate_migrate.migrate_all_if_needed(client, [definition], auto_migrate=True)
    else:
        weaviate_migrate.migrate_all_if_needed(client, [definition], auto_migrate=False)
    client.collections.delete.assert_not_called()


@pytest.mark.parametrize("method, suffix", [
    ("get_paper", ""), ("get_references", "/references"), ("get_citations", "/citations"),
])
@pytest.mark.parametrize("paper_id, component", [
    ("DOI:10.1234/a?b#c", "DOI%3A10.1234%2Fa%3Fb%23c"),
    ("DOI:10.1234/a/../../author", "DOI%3A10.1234%2Fa%2F..%2F..%2Fauthor"),
    ("DOI:10.1234/é%2F", "DOI%3A10.1234%2F%C3%A9%252F"),
    ("CorpusID:123", "CorpusID%3A123"),
    ("a" * 40, "a" * 40),
])
async def test_identifiers_are_one_encoded_path_component(monkeypatch, method, suffix, paper_id, component):
    """Accepted DOI characters stay identifier data in every outgoing path."""
    request = AsyncMock(return_value={"paperId": "fake-paper"})
    monkeypatch.setattr(academic_client.SemanticScholarClient, "_request", request)
    assert academic_client.validate_paper_id(paper_id) == paper_id
    result = await getattr(academic_client.SemanticScholarClient, method)(paper_id)
    assert result == {"paperId": "fake-paper"}
    assert request.call_args.args == ("GET", f"/graph/v1/paper/{component}{suffix}")
    assert "fields" in request.call_args.kwargs["params"]


async def test_invalid_identifier_never_reaches_request(monkeypatch):
    """Malformed identifiers still fail before the mocked HTTP boundary."""
    request = AsyncMock()
    monkeypatch.setattr(academic_client.SemanticScholarClient, "_request", request)
    with pytest.raises(ValueError, match="Invalid paper ID"):
        await academic_client.SemanticScholarClient.get_paper("https://untrusted.invalid/paper")
    request.assert_not_awaited()
