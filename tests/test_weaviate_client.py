"""Tests for WeaviateClient singleton."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestWeaviateClientGet:
    """Tests for WeaviateClient.get()."""

    def test_raises_when_url_not_configured(self, clean_config, monkeypatch):
        """get() raises ValueError when WEAVIATE_URL is empty."""
        monkeypatch.delenv("WEAVIATE_URL", raising=False)
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()
        with pytest.raises(ValueError, match="WEAVIATE_URL not configured"):
            WeaviateClient.get()

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_creates_client_when_configured(self, mock_connect, clean_config, monkeypatch):
        """get() creates and returns a client when WEAVIATE_URL is set."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test-cluster.weaviate.network")
        monkeypatch.setenv("WEAVIATE_API_KEY", "test-key")
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}
        mock_connect.return_value = mock_client

        result = WeaviateClient.get()
        assert result is mock_client
        mock_connect.assert_called_once()

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_returns_same_client_on_subsequent_calls(self, mock_connect, clean_config, monkeypatch):
        """get() returns the cached singleton on second call."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}
        mock_connect.return_value = mock_client

        first = WeaviateClient.get()
        second = WeaviateClient.get()
        assert first is second
        assert mock_connect.call_count == 1


class TestWeaviateClientClose:
    """Tests for close() and reset()."""

    def test_close_clears_singleton(self, clean_config):
        """close() sets internal state to None."""
        import video_research_mcp.weaviate_client as mod
        mod._client = MagicMock()
        mod._schema_ensured = True

        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.close()

        assert mod._client is None
        assert mod._schema_ensured is False

    def test_reset_clears_singleton(self, clean_config):
        """reset() clears state without calling close on the client."""
        import video_research_mcp.weaviate_client as mod
        mod._client = MagicMock()
        mod._schema_ensured = True

        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        assert mod._client is None
        assert mod._schema_ensured is False


class TestWeaviateClientIsAvailable:
    """Tests for is_available()."""

    def test_false_when_not_configured(self, clean_config, monkeypatch):
        """is_available() returns False when weaviate_enabled is False."""
        monkeypatch.delenv("WEAVIATE_URL", raising=False)
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()
        assert WeaviateClient.is_available() is False

    def test_true_when_configured_and_ready(self, mock_weaviate_client):
        """is_available() returns True when client is ready."""
        from video_research_mcp.weaviate_client import WeaviateClient
        assert WeaviateClient.is_available() is True


class TestEnsureCollections:
    """Tests for ensure_collections()."""

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_skips_existing_collections(self, mock_connect, clean_config, monkeypatch):
        """ensure_collections() does not recreate existing collections."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        mock_client = MagicMock()
        # Simulate all collections already existing
        existing = {
            name: MagicMock(name=name) for name in [
                "ResearchFindings", "VideoAnalyses", "ContentAnalyses",
                "VideoMetadata", "SessionTranscripts", "WebSearchResults", "ResearchPlans",
                "CommunityReactions", "ConceptKnowledge", "RelationshipEdges", "CallNotes",
                "DeepResearchReports",
            ]
        }
        mock_client.collections.list_all.return_value = existing
        # Mock collection config for _evolve_collection
        mock_col = MagicMock()
        mock_col.config.get.return_value = MagicMock(properties=[])
        mock_client.collections.get.return_value = mock_col
        mock_connect.return_value = mock_client

        WeaviateClient.get()
        mock_client.collections.create.assert_not_called()


class TestEvolveCollection:
    """Tests for _evolve_collection()."""

    def test_adds_missing_properties(self, clean_config):
        """_evolve_collection adds properties not present in the collection."""
        import video_research_mcp.weaviate_client as mod
        from video_research_mcp.weaviate_client import WeaviateClient
        from video_research_mcp.weaviate_schema import CollectionDef, PropertyDef

        mock_client = MagicMock()
        mod._client = mock_client

        # Existing collection has only created_at
        existing_prop = MagicMock()
        existing_prop.name = "created_at"
        mock_col = MagicMock()
        mock_col.config.get.return_value = MagicMock(properties=[existing_prop])
        mock_client.collections.get.return_value = mock_col

        col_def = CollectionDef(
            name="TestCollection",
            properties=[
                PropertyDef("created_at", ["date"], "Timestamp", skip_vectorization=True),
                PropertyDef("new_field", ["text"], "A new field"),
                PropertyDef("another_field", ["int"], "Another new field", skip_vectorization=True),
            ],
        )

        WeaviateClient._evolve_collection(col_def)
        assert mock_col.config.add_property.call_count == 2

    def test_skips_existing_properties(self, clean_config):
        """_evolve_collection doesn't re-add existing properties."""
        import video_research_mcp.weaviate_client as mod
        from video_research_mcp.weaviate_client import WeaviateClient
        from video_research_mcp.weaviate_schema import CollectionDef, PropertyDef

        mock_client = MagicMock()
        mod._client = mock_client

        # All properties already exist
        prop1 = MagicMock()
        prop1.name = "field_a"
        prop2 = MagicMock()
        prop2.name = "field_b"
        mock_col = MagicMock()
        mock_col.config.get.return_value = MagicMock(properties=[prop1, prop2])
        mock_client.collections.get.return_value = mock_col

        col_def = CollectionDef(
            name="TestCollection",
            properties=[
                PropertyDef("field_a", ["text"], "Field A"),
                PropertyDef("field_b", ["int"], "Field B"),
            ],
        )

        WeaviateClient._evolve_collection(col_def)
        mock_col.config.add_property.assert_not_called()


class TestEnsureReferences:
    """Tests for _ensure_references()."""

    def test_adds_missing_references(self, clean_config):
        """_ensure_references adds cross-references from collection defs."""
        import video_research_mcp.weaviate_client as mod
        from video_research_mcp.weaviate_client import WeaviateClient
        from video_research_mcp.weaviate_schema import CollectionDef, ReferenceDef

        mock_client = MagicMock()
        mod._client = mock_client
        mock_col = MagicMock()
        mock_client.collections.get.return_value = mock_col

        collections = [
            CollectionDef(
                name="VideoAnalyses",
                references=[ReferenceDef("has_metadata", "VideoMetadata")],
            ),
            CollectionDef(name="ContentAnalyses"),  # no references
        ]

        WeaviateClient._ensure_references(collections)
        mock_col.config.add_reference.assert_called_once()

    def test_reference_failure_is_non_fatal(self, clean_config):
        """_ensure_references swallows errors from already-existing references."""
        import video_research_mcp.weaviate_client as mod
        from video_research_mcp.weaviate_client import WeaviateClient
        from video_research_mcp.weaviate_schema import CollectionDef, ReferenceDef

        mock_client = MagicMock()
        mod._client = mock_client
        mock_col = MagicMock()
        mock_col.config.add_reference.side_effect = Exception("Already exists")
        mock_client.collections.get.return_value = mock_col

        collections = [
            CollectionDef(
                name="Test",
                references=[ReferenceDef("ref", "Target")],
            ),
        ]
        # Should not raise
        WeaviateClient._ensure_references(collections)


class TestResolveDataType:
    """Tests for _resolve_data_type()."""

    def test_maps_known_types(self):
        """_resolve_data_type maps all standard type strings."""
        from weaviate.classes.config import DataType
        from video_research_mcp.weaviate_client import _resolve_data_type

        assert _resolve_data_type("text") == DataType.TEXT
        assert _resolve_data_type("text[]") == DataType.TEXT_ARRAY
        assert _resolve_data_type("int") == DataType.INT
        assert _resolve_data_type("number") == DataType.NUMBER
        assert _resolve_data_type("boolean") == DataType.BOOL
        assert _resolve_data_type("date") == DataType.DATE

    def test_raises_on_unknown_type(self):
        """_resolve_data_type raises ValueError for unknown types."""
        from video_research_mcp.weaviate_client import _resolve_data_type

        with pytest.raises(ValueError, match="Unknown data type"):
            _resolve_data_type("blob")


class TestToProperty:
    """Tests for _to_property() helper."""

    def test_converts_basic_property(self):
        """_to_property creates Property with correct data type and name."""
        from weaviate.classes.config import DataType
        from video_research_mcp.weaviate_client import _to_property
        from video_research_mcp.weaviate_schema import PropertyDef

        prop = _to_property(PropertyDef("title", ["text"], "A title"))
        assert prop.name == "title"
        assert prop.dataType == DataType.TEXT

    def test_carries_index_range_filters(self):
        """_to_property passes index_range_filters to Property."""
        from video_research_mcp.weaviate_client import _to_property
        from video_research_mcp.weaviate_schema import PropertyDef

        prop = _to_property(PropertyDef(
            "view_count", ["int"], "Views", index_range_filters=True,
        ))
        assert prop.indexRangeFilters is True

    def test_carries_index_searchable_false(self):
        """_to_property passes index_searchable=False to Property."""
        from video_research_mcp.weaviate_client import _to_property
        from video_research_mcp.weaviate_schema import PropertyDef

        prop = _to_property(PropertyDef(
            "raw_json", ["text"], "JSON", index_searchable=False,
        ))
        assert prop.indexSearchable is False

    def test_omits_index_searchable_when_none(self):
        """_to_property leaves indexSearchable as None when not explicitly set."""
        from video_research_mcp.weaviate_client import _to_property
        from video_research_mcp.weaviate_schema import PropertyDef

        prop = _to_property(PropertyDef("title", ["text"], "Title"))
        # None = Weaviate server applies its default (True for text)
        assert prop.indexSearchable is None


class TestTimeoutConfig:
    """Tests for timeout configuration in _connect()."""

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_cloud_connection_passes_timeout(self, mock_connect, clean_config, monkeypatch):
        """Cloud connection includes AdditionalConfig with timeouts."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        monkeypatch.setenv("WEAVIATE_API_KEY", "test-key")
        from video_research_mcp.weaviate_client import WeaviateClient, _ADDITIONAL_CONFIG
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}
        mock_connect.return_value = mock_client

        WeaviateClient.get()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["additional_config"] is _ADDITIONAL_CONFIG

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_local")
    def test_local_connection_passes_timeout(self, mock_connect, clean_config, monkeypatch):
        """Local connection includes AdditionalConfig with timeouts."""
        monkeypatch.setenv("WEAVIATE_URL", "http://localhost:8080")
        from video_research_mcp.weaviate_client import WeaviateClient, _ADDITIONAL_CONFIG
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}
        mock_connect.return_value = mock_client

        WeaviateClient.get()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["additional_config"] is _ADDITIONAL_CONFIG

    def test_timeout_values(self):
        """Timeout is configured with init=30, query=60, insert=120."""
        from video_research_mcp.weaviate_client import _TIMEOUT
        assert _TIMEOUT.init == 30
        assert _TIMEOUT.query == 60
        assert _TIMEOUT.insert == 120


class TestV4PropertyAPI:
    """Tests for v4 Property API migration in ensure_collections."""

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_uses_create_not_create_from_dict(self, mock_connect, clean_config, monkeypatch):
        """ensure_collections uses client.collections.create() not create_from_dict()."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}  # no existing collections
        mock_connect.return_value = mock_client

        WeaviateClient.get()
        assert mock_client.collections.create.call_count == 12
        mock_client.collections.create_from_dict.assert_not_called()

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_create_passes_property_objects(self, mock_connect, clean_config, monkeypatch):
        """ensure_collections passes Property objects (not dicts) to create()."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from weaviate.classes.config import Property
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}
        mock_connect.return_value = mock_client

        WeaviateClient.get()
        first_call = mock_client.collections.create.call_args_list[0]
        props = first_call[1]["properties"]
        assert all(isinstance(p, Property) for p in props)


class TestRerankerConfig:
    """Tests for reranker configuration in ensure_collections."""

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_passes_reranker_when_enabled(self, mock_connect, clean_config, monkeypatch):
        """ensure_collections passes reranker_config when reranker is enabled."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        monkeypatch.setenv("COHERE_API_KEY", "test-cohere-key")
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}
        mock_connect.return_value = mock_client

        WeaviateClient.get()
        first_call = mock_client.collections.create.call_args_list[0]
        assert "reranker_config" in first_call[1]
        assert first_call[1]["reranker_config"] is not None

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_no_reranker_when_disabled(self, mock_connect, clean_config, monkeypatch):
        """ensure_collections omits reranker_config when reranker is disabled."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}
        mock_connect.return_value = mock_client

        WeaviateClient.get()
        first_call = mock_client.collections.create.call_args_list[0]
        assert "reranker_config" not in first_call[1]

    def test_evolve_adds_reranker(self, clean_config, monkeypatch):
        """_evolve_collection updates reranker config when enabled."""
        monkeypatch.setenv("COHERE_API_KEY", "test-cohere-key")
        import video_research_mcp.weaviate_client as mod
        from video_research_mcp.weaviate_client import WeaviateClient
        from video_research_mcp.weaviate_schema import CollectionDef

        mock_client = MagicMock()
        mod._client = mock_client
        mock_col = MagicMock()
        mock_col.config.get.return_value = MagicMock(properties=[])
        mock_client.collections.get.return_value = mock_col

        col_def = CollectionDef(name="TestCollection", properties=[])
        WeaviateClient._evolve_collection(col_def)
        mock_col.config.update.assert_called_once()


class TestProviderHeaders:
    """Tests for _collect_provider_headers()."""

    def test_collects_env_headers(self, monkeypatch):
        """_collect_provider_headers returns headers for set env vars."""
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test-123")
        monkeypatch.setenv("COHERE_API_KEY", "cohere-test")
        from video_research_mcp.weaviate_client import _collect_provider_headers
        headers = _collect_provider_headers()
        assert headers["X-OpenAI-Api-Key"] == "sk-test-123"
        assert headers["X-Cohere-Api-Key"] == "cohere-test"
        assert len(headers) == 2

    def test_returns_empty_when_no_keys(self, monkeypatch):
        """_collect_provider_headers returns empty dict when no provider keys set."""
        for key in ("OPENAI_API_KEY", "COHERE_API_KEY", "HUGGINGFACE_API_KEY",
                     "JINAAI_API_KEY", "VOYAGEAI_API_KEY"):
            monkeypatch.delenv(key, raising=False)
        from video_research_mcp.weaviate_client import _collect_provider_headers
        assert _collect_provider_headers() == {}

    @patch("video_research_mcp.weaviate_client.weaviate.connect_to_weaviate_cloud")
    def test_cloud_connection_passes_headers(self, mock_connect, clean_config, monkeypatch):
        """Cloud connection passes provider headers to connect_to_weaviate_cloud."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        monkeypatch.setenv("WEAVIATE_API_KEY", "test-key")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        from video_research_mcp.weaviate_client import WeaviateClient
        WeaviateClient.reset()

        mock_client = MagicMock()
        mock_client.collections.list_all.return_value = {}
        mock_connect.return_value = mock_client

        WeaviateClient.get()
        call_kwargs = mock_connect.call_args[1]
        assert call_kwargs["headers"] == {"X-OpenAI-Api-Key": "sk-test"}
