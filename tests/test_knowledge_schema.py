"""Tests for knowledge_schema tool and enriched ingest error messages."""

from __future__ import annotations


class TestKnowledgeSchema:
    """Tests for knowledge_schema tool."""

    async def test_schema_single_collection(self):
        """knowledge_schema returns properties for a single collection."""
        from video_research_mcp.tools.knowledge import knowledge_schema

        result = await knowledge_schema(collection="VideoMetadata")
        assert "schemas" in result
        assert "VideoMetadata" in result["schemas"]
        assert result["total_collections"] == 1
        props = result["schemas"]["VideoMetadata"]
        assert isinstance(props, list)
        assert len(props) > 0
        # Every property has name, type, description
        for p in props:
            assert "name" in p
            assert "type" in p
            assert "description" in p

    async def test_schema_all_collections(self):
        """knowledge_schema returns all 12 collections when no filter given."""
        from video_research_mcp.tools.knowledge import knowledge_schema

        result = await knowledge_schema()
        assert result["total_collections"] == 12
        assert len(result["schemas"]) == 12

    async def test_schema_no_weaviate(self):
        """knowledge_schema works without Weaviate configured."""
        from video_research_mcp.tools.knowledge import knowledge_schema

        # knowledge_schema reads from local CollectionDef objects,
        # not from Weaviate — should always work
        result = await knowledge_schema(collection="ResearchFindings")
        assert "schemas" in result
        assert "ResearchFindings" in result["schemas"]


class TestIngestErrorShowsAllowed:
    """Tests for enriched ingest error messages."""

    async def test_ingest_error_shows_allowed_types(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """Ingest error for unknown props includes name:type pairs and schema hint."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_ingest

        result = await knowledge_ingest(
            collection="VideoAnalyses",
            properties={"title": "ok", "totally_fake_field": "bad"},
        )
        assert "error" in result
        error_msg = result["error"]
        # Should list the unknown field
        assert "totally_fake_field" in error_msg
        # Should include name:type pairs
        assert "Allowed:" in error_msg
        assert ":" in error_msg.split("Allowed:")[1]  # at least one name:type
        # Should hint at knowledge_schema
        assert "knowledge_schema" in error_msg
