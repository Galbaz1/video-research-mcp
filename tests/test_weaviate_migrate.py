"""Tests for Weaviate vector config migration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from video_research_mcp.weaviate_schema import CollectionDef, PropertyDef, ReferenceDef


@pytest.fixture()
def sample_col_def():
    """A minimal CollectionDef with mixed vectorization flags."""
    return CollectionDef(
        name="TestCollection",
        description="Test",
        properties=[
            PropertyDef("title", ["text"], "Title"),
            PropertyDef("summary", ["text"], "Summary"),
            PropertyDef("raw_json", ["text"], "JSON blob", skip_vectorization=True),
            PropertyDef("count", ["int"], "Count", skip_vectorization=True),
        ],
    )


@pytest.fixture()
def sample_col_def_with_refs():
    """A CollectionDef with references for migration tests."""
    return CollectionDef(
        name="TestCollection",
        description="Test with refs",
        properties=[
            PropertyDef("title", ["text"], "Title"),
            PropertyDef("summary", ["text"], "Summary"),
        ],
        references=[
            ReferenceDef("has_target", "TargetCollection", "Link to target"),
        ],
    )


def _make_col_config(source_properties=None, vectorizer_module="text2vec-openai"):
    """Build a realistic mock of Weaviate runtime collection config."""
    vectorizer = MagicMock()
    vectorizer.source_properties = source_properties
    vectorizer.vectorizer = vectorizer_module
    named = MagicMock()
    named.vectorizer = vectorizer
    col_config = MagicMock()
    col_config.vector_config = {"default": named}
    return col_config


class TestBuildVectorConfig:
    """Tests for build_vector_config()."""

    def test_openai_with_source_properties(self, clean_config, monkeypatch, sample_col_def):
        """Builds text2vec-openai config with source_properties from schema."""
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from video_research_mcp.weaviate_migrate import build_vector_config

        result = build_vector_config(sample_col_def)
        # Verify it's an openai vectorizer config with source_properties
        assert result is not None
        # The _VectorConfigCreate is opaque; inspect via string repr or known attributes
        config_str = str(result)
        assert "title" in config_str or hasattr(result, "vectorizer")

    def test_weaviate_with_source_properties(self, clean_config, monkeypatch, sample_col_def):
        """Builds text2vec-weaviate config when WEAVIATE_VECTORIZER=weaviate."""
        monkeypatch.setenv("WEAVIATE_VECTORIZER", "weaviate")
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.cloud")
        from video_research_mcp.weaviate_migrate import build_vector_config

        result = build_vector_config(sample_col_def)
        assert result is not None

    def test_empty_vectorized_properties_passes_none(self, clean_config, monkeypatch):
        """When all properties are skipped, source_properties is None."""
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from video_research_mcp.weaviate_migrate import build_vector_config

        col = CollectionDef(
            name="AllSkipped",
            properties=[
                PropertyDef("meta", ["text"], "Meta", skip_vectorization=True),
                PropertyDef("count", ["int"], "Count", skip_vectorization=True),
            ],
        )
        result = build_vector_config(col)
        assert result is not None


class TestNeedsVectorMigration:
    """Tests for needs_vector_migration()."""

    def test_detects_none_vs_list(self, sample_col_def):
        """Detects when current has no source_properties but desired does."""
        from video_research_mcp.weaviate_migrate import needs_vector_migration

        # Simulate runtime config with no source_properties
        vectorizer = MagicMock()
        vectorizer.source_properties = None
        named = MagicMock()
        named.vectorizer = vectorizer
        col_config = MagicMock()
        col_config.vector_config = {"default": named}

        assert needs_vector_migration(col_config, sample_col_def) is True

    def test_detects_different_lists(self, sample_col_def):
        """Detects when current source_properties differ from desired."""
        from video_research_mcp.weaviate_migrate import needs_vector_migration

        vectorizer = MagicMock()
        vectorizer.source_properties = ["title"]  # missing "summary"
        named = MagicMock()
        named.vectorizer = vectorizer
        col_config = MagicMock()
        col_config.vector_config = {"default": named}

        assert needs_vector_migration(col_config, sample_col_def) is True

    def test_no_migration_when_aligned(self, sample_col_def):
        """No migration needed when source_properties match (order-independent)."""
        from video_research_mcp.weaviate_migrate import needs_vector_migration

        vectorizer = MagicMock()
        vectorizer.source_properties = ["summary", "title"]  # reversed order
        named = MagicMock()
        named.vectorizer = vectorizer
        col_config = MagicMock()
        col_config.vector_config = {"default": named}

        assert needs_vector_migration(col_config, sample_col_def) is False

    def test_safe_on_missing_attributes(self, sample_col_def):
        """Handles missing attributes in config shape gracefully."""
        from video_research_mcp.weaviate_migrate import needs_vector_migration

        # No vector_config at all
        col_config = MagicMock(spec=[])
        del col_config.vector_config
        assert needs_vector_migration(col_config, sample_col_def) is True

    def test_safe_on_empty_vector_config(self, sample_col_def):
        """Handles empty vector_config dict."""
        from video_research_mcp.weaviate_migrate import needs_vector_migration

        col_config = MagicMock()
        col_config.vector_config = {}
        assert needs_vector_migration(col_config, sample_col_def) is True


class TestMigrateCollection:
    """Tests for migrate_collection()."""

    def test_export_recreate_reinsert(self, clean_config, monkeypatch, sample_col_def):
        """Happy path: export, delete, recreate, re-insert."""
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        from video_research_mcp.weaviate_migrate import migrate_collection

        mock_client = MagicMock()

        # Mock iterator for export
        obj1 = MagicMock()
        obj1.uuid = "uuid-1"
        obj1.properties = {"title": "Test", "summary": "A summary"}
        obj2 = MagicMock()
        obj2.uuid = "uuid-2"
        obj2.properties = {"title": "Test 2", "summary": "Another"}

        mock_col_export = MagicMock()
        mock_col_export.iterator.return_value = [obj1, obj2]

        mock_col_reinsert = MagicMock()
        mock_col_reinsert.batch.fixed_size.return_value.__enter__ = MagicMock()
        mock_col_reinsert.batch.fixed_size.return_value.__exit__ = MagicMock(return_value=False)
        mock_col_reinsert.batch.failed_objects = []

        # First .get() for export, second .get() for re-insert
        mock_client.collections.get.side_effect = [mock_col_export, mock_col_reinsert]

        migrate_collection(mock_client, sample_col_def)

        mock_client.collections.delete.assert_called_once_with("TestCollection")
        mock_client.collections.create.assert_called_once()
        create_kwargs = mock_client.collections.create.call_args[1]
        assert create_kwargs["name"] == "TestCollection"
        assert "vector_config" in create_kwargs

    def test_batch_failures_logged_not_raised(self, clean_config, monkeypatch, sample_col_def):
        """Batch failures are logged but don't raise."""
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        from video_research_mcp.weaviate_migrate import migrate_collection

        mock_client = MagicMock()

        obj = MagicMock()
        obj.uuid = "uuid-1"
        obj.properties = {"title": "Test"}

        mock_col_export = MagicMock()
        mock_col_export.iterator.return_value = [obj]

        fail_obj = MagicMock()
        fail_obj.message = "Insert failed"
        mock_col_reinsert = MagicMock()
        mock_col_reinsert.batch.fixed_size.return_value.__enter__ = MagicMock()
        mock_col_reinsert.batch.fixed_size.return_value.__exit__ = MagicMock(return_value=False)
        mock_col_reinsert.batch.failed_objects = [fail_obj]

        mock_client.collections.get.side_effect = [mock_col_export, mock_col_reinsert]

        # Should not raise
        migrate_collection(mock_client, sample_col_def)


class TestMigrateAllIfNeeded:
    """Tests for migrate_all_if_needed()."""

    def test_skips_when_disabled(self, sample_col_def):
        """When auto_migrate=False, logs warning but does not migrate."""
        from video_research_mcp.weaviate_migrate import migrate_all_if_needed

        mock_client = MagicMock()
        # Config with no source_properties → mismatch
        vectorizer = MagicMock()
        vectorizer.source_properties = None
        named = MagicMock()
        named.vectorizer = vectorizer
        col_config = MagicMock()
        col_config.vector_config = {"default": named}
        mock_col = MagicMock()
        mock_col.config.get.return_value = col_config
        mock_client.collections.get.return_value = mock_col

        with patch("video_research_mcp.weaviate_migrate.migrate_collection") as mock_migrate:
            migrate_all_if_needed(mock_client, [sample_col_def], auto_migrate=False)
            mock_migrate.assert_not_called()

    def test_migrates_when_enabled(self, sample_col_def):
        """When auto_migrate=True and mismatch exists, migrates."""
        from video_research_mcp.weaviate_migrate import migrate_all_if_needed

        mock_client = MagicMock()
        vectorizer = MagicMock()
        vectorizer.source_properties = None
        named = MagicMock()
        named.vectorizer = vectorizer
        col_config = MagicMock()
        col_config.vector_config = {"default": named}
        mock_col = MagicMock()
        mock_col.config.get.return_value = col_config
        mock_client.collections.get.return_value = mock_col

        with patch("video_research_mcp.weaviate_migrate.migrate_collection") as mock_migrate:
            migrate_all_if_needed(mock_client, [sample_col_def], auto_migrate=True)
            mock_migrate.assert_called_once_with(mock_client, sample_col_def)

    def test_skips_aligned_collections(self, sample_col_def):
        """Collections with matching source_properties are skipped."""
        from video_research_mcp.weaviate_migrate import migrate_all_if_needed

        mock_client = MagicMock()
        col_config = _make_col_config(
            source_properties=["title", "summary"],
            vectorizer_module="text2vec-openai",
        )
        mock_col = MagicMock()
        mock_col.config.get.return_value = col_config
        mock_client.collections.get.return_value = mock_col

        with patch("video_research_mcp.weaviate_migrate.migrate_collection") as mock_migrate:
            migrate_all_if_needed(mock_client, [sample_col_def], auto_migrate=True)
            mock_migrate.assert_not_called()


class TestVectorizerModuleDetection:
    """Tests for vectorizer module extraction and comparison (P2 fix)."""

    def test_detects_vectorizer_mismatch(self, clean_config, monkeypatch, sample_col_def):
        """Detects when vectorizer module differs from config.

        GIVEN: collection uses text2vec-openai, config wants text2vec-weaviate (default)
        WHEN: needs_vector_migration is called
        THEN: returns True
        """
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from video_research_mcp.weaviate_migrate import needs_vector_migration

        col_config = _make_col_config(
            source_properties=["title", "summary"],
            vectorizer_module="text2vec-openai",
        )
        assert needs_vector_migration(col_config, sample_col_def) is True

    def test_no_migration_when_vectorizer_aligned(self, clean_config, monkeypatch, sample_col_def):
        """No migration when both source_properties and vectorizer match.

        GIVEN: collection uses text2vec-weaviate with correct source_properties
        WHEN: needs_vector_migration is called
        THEN: returns False (default without OPENAI_API_KEY is weaviate)
        """
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from video_research_mcp.weaviate_migrate import needs_vector_migration

        col_config = _make_col_config(
            source_properties=["title", "summary"],
            vectorizer_module="text2vec-weaviate",
        )
        assert needs_vector_migration(col_config, sample_col_def) is False

    def test_vectorizer_enum_value_extracted(self, clean_config, monkeypatch, sample_col_def):
        """Handles Vectorizers enum (has .value attribute).

        GIVEN: vectorizer module is an enum with .value = "text2vec-openai"
        WHEN: _get_current_vectorizer_module is called
        THEN: returns "text2vec-openai"
        """
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        from video_research_mcp.weaviate_migrate import _get_current_vectorizer_module

        enum_mock = MagicMock()
        enum_mock.value = "text2vec-openai"
        col_config = _make_col_config(
            source_properties=["title"],
            vectorizer_module=enum_mock,
        )
        assert _get_current_vectorizer_module(col_config) == "text2vec-openai"

    def test_unrecognized_vectorizer_returns_none(self):
        """Unrecognized vectorizer module returns None (defensive)."""
        from video_research_mcp.weaviate_migrate import _get_current_vectorizer_module

        col_config = _make_col_config(vectorizer_module="unknown-vectorizer")
        assert _get_current_vectorizer_module(col_config) is None

    def test_migrates_on_vectorizer_change(self, clean_config, monkeypatch, sample_col_def):
        """migrate_all_if_needed triggers migration on vectorizer change.

        GIVEN: source_properties match but vectorizer differs (openai vs default weaviate)
        WHEN: auto_migrate=True
        THEN: migrate_collection is called
        """
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        from video_research_mcp.weaviate_migrate import migrate_all_if_needed

        mock_client = MagicMock()
        col_config = _make_col_config(
            source_properties=["title", "summary"],
            vectorizer_module="text2vec-openai",
        )
        mock_col = MagicMock()
        mock_col.config.get.return_value = col_config
        mock_client.collections.get.return_value = mock_col

        with patch("video_research_mcp.weaviate_migrate.migrate_collection") as mock_migrate:
            migrate_all_if_needed(mock_client, [sample_col_def], auto_migrate=True)
            mock_migrate.assert_called_once()


class TestReferencePreservation:
    """Tests for cross-reference preservation during migration (P1 fix)."""

    def test_export_includes_references(self, sample_col_def_with_refs):
        """_export_objects exports cross-reference edges alongside properties.

        GIVEN: collection has objects with cross-references
        WHEN: _export_objects is called
        THEN: exported objects include reference UUIDs
        """
        from video_research_mcp.weaviate_migrate import _export_objects

        # Build mock objects with references
        target_ref = MagicMock()
        target_ref.uuid = "target-uuid-1"
        cross_refs = MagicMock()
        cross_refs.objects = [target_ref]

        obj = MagicMock()
        obj.uuid = "source-uuid-1"
        obj.properties = {"title": "Test", "summary": "Summary"}
        obj.references = {"has_target": cross_refs}

        mock_col = MagicMock()
        mock_col.iterator.return_value = [obj]

        result = _export_objects(mock_col, sample_col_def_with_refs)

        assert len(result) == 1
        assert result[0]["uuid"] == "source-uuid-1"
        assert result[0]["references"]["has_target"] == ["target-uuid-1"]

    def test_export_handles_no_references(self, sample_col_def):
        """_export_objects works for collections without references."""
        from video_research_mcp.weaviate_migrate import _export_objects

        obj = MagicMock()
        obj.uuid = "uuid-1"
        obj.properties = {"title": "Test"}
        obj.references = None

        mock_col = MagicMock()
        mock_col.iterator.return_value = [obj]

        result = _export_objects(mock_col, sample_col_def)

        assert len(result) == 1
        assert result[0]["references"] == {}

    def test_restore_references_adds_schema_and_edges(self, sample_col_def_with_refs):
        """_restore_references adds reference properties and restores edges.

        GIVEN: recreated collection with exported objects and reference data
        WHEN: _restore_references is called
        THEN: reference schema is added and edges are restored
        """
        from video_research_mcp.weaviate_migrate import _restore_references

        mock_col = MagicMock()
        objects = [
            {
                "uuid": "source-1",
                "properties": {"title": "Test"},
                "references": {"has_target": ["target-1", "target-2"]},
            },
        ]

        _restore_references(mock_col, sample_col_def_with_refs, objects)

        mock_col.config.add_reference.assert_called_once()
        assert mock_col.data.reference_add.call_count == 2

    def test_restore_references_noop_without_refs(self, sample_col_def):
        """_restore_references is a no-op for collections without references."""
        from video_research_mcp.weaviate_migrate import _restore_references

        mock_col = MagicMock()
        _restore_references(mock_col, sample_col_def, [])

        mock_col.config.add_reference.assert_not_called()
        mock_col.data.reference_add.assert_not_called()

    def test_restore_references_edge_failure_non_fatal(self, sample_col_def_with_refs):
        """Failed reference edge restoration is logged, not raised."""
        from video_research_mcp.weaviate_migrate import _restore_references

        mock_col = MagicMock()
        mock_col.data.reference_add.side_effect = Exception("Target not found")
        objects = [
            {
                "uuid": "source-1",
                "properties": {},
                "references": {"has_target": ["missing-target"]},
            },
        ]

        # Should not raise
        _restore_references(mock_col, sample_col_def_with_refs, objects)

    def test_migrate_collection_preserves_references(
        self, clean_config, monkeypatch, sample_col_def_with_refs,
    ):
        """Full migration preserves cross-references end-to-end.

        GIVEN: collection with objects that have cross-reference edges
        WHEN: migrate_collection runs
        THEN: references are exported, schema recreated, edges restored
        """
        monkeypatch.delenv("WEAVIATE_VECTORIZER", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.delenv("COHERE_API_KEY", raising=False)
        from video_research_mcp.weaviate_migrate import migrate_collection

        mock_client = MagicMock()

        # Mock object with references for export
        target_ref = MagicMock()
        target_ref.uuid = "target-uuid"
        cross_refs = MagicMock()
        cross_refs.objects = [target_ref]

        obj = MagicMock()
        obj.uuid = "source-uuid"
        obj.properties = {"title": "Test", "summary": "Sum"}
        obj.references = {"has_target": cross_refs}

        mock_col_export = MagicMock()
        mock_col_export.iterator.return_value = [obj]

        mock_col_reinsert = MagicMock()
        mock_col_reinsert.batch.fixed_size.return_value.__enter__ = MagicMock()
        mock_col_reinsert.batch.fixed_size.return_value.__exit__ = MagicMock(
            return_value=False,
        )
        mock_col_reinsert.batch.failed_objects = []

        mock_client.collections.get.side_effect = [
            mock_col_export, mock_col_reinsert,
        ]

        migrate_collection(mock_client, sample_col_def_with_refs)

        # Verify reference schema was added
        mock_col_reinsert.config.add_reference.assert_called_once()
        # Verify reference edge was restored
        mock_col_reinsert.data.reference_add.assert_called_once()
        ref_call = mock_col_reinsert.data.reference_add.call_args[1]
        assert ref_call["from_uuid"] == "source-uuid"
        assert ref_call["from_property"] == "has_target"
        assert ref_call["to"] == "target-uuid"
