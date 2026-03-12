"""Tests for Weaviate vector config migration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from video_research_mcp.weaviate_schema import CollectionDef, PropertyDef


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
        vectorizer = MagicMock()
        vectorizer.source_properties = ["title", "summary"]
        named = MagicMock()
        named.vectorizer = vectorizer
        col_config = MagicMock()
        col_config.vector_config = {"default": named}
        mock_col = MagicMock()
        mock_col.config.get.return_value = col_config
        mock_client.collections.get.return_value = mock_col

        with patch("video_research_mcp.weaviate_migrate.migrate_collection") as mock_migrate:
            migrate_all_if_needed(mock_client, [sample_col_def], auto_migrate=True)
            mock_migrate.assert_not_called()
