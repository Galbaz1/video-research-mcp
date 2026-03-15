"""Tests for knowledge query tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock


class TestKnowledgeSearch:
    """Tests for knowledge_search tool."""

    async def test_returns_empty_when_disabled(self, mock_weaviate_disabled):
        """knowledge_search returns empty result when Weaviate not configured."""
        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="AI research")
        assert result["query"] == "AI research"
        assert result["total_results"] == 0

    async def test_returns_search_result_structure(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search returns KnowledgeSearchResult dict."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="AI research")
        assert "query" in result
        assert "total_results" in result
        assert "results" in result
        assert result["query"] == "AI research"

    async def test_searches_all_collections_by_default(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search queries all 11 collections when none specified."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        await knowledge_search(query="test")
        assert mock_weaviate_client["client"].collections.get.call_count == 11

    async def test_respects_collection_filter(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search only queries specified collections."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        await knowledge_search(query="test", collections=["VideoAnalyses", "VideoMetadata"])
        assert mock_weaviate_client["client"].collections.get.call_count == 2

    async def test_returns_ranked_results(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search returns results sorted by score descending."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        obj1 = MagicMock()
        obj1.uuid = "uuid-1"
        obj1.properties = {"title": "First"}
        obj1.metadata = MagicMock(score=0.9)

        obj2 = MagicMock()
        obj2.uuid = "uuid-2"
        obj2.properties = {"title": "Second"}
        obj2.metadata = MagicMock(score=0.5)

        mock_collection = MagicMock()
        mock_collection.query.hybrid.return_value = MagicMock(objects=[obj2, obj1])
        mock_weaviate_client["client"].collections.get.return_value = mock_collection

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="test", collections=["VideoAnalyses"])
        assert len(result["results"]) == 2
        assert result["results"][0]["score"] >= result["results"][1]["score"]

    async def test_passes_filters_to_hybrid(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search passes filter object to hybrid() when filters provided."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(
            query="AI", collections=["ResearchFindings"], evidence_tier="CONFIRMED",
        )
        call_kwargs = mock_weaviate_client["collection"].query.hybrid.call_args[1]
        assert call_kwargs["filters"] is not None
        assert result["filters_applied"] == {"evidence_tier": "CONFIRMED"}

    async def test_filter_skipped_for_inapplicable_collection(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search skips evidence_tier filter for VideoAnalyses (no such property)."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        await knowledge_search(
            query="test", collections=["VideoAnalyses"], evidence_tier="CONFIRMED",
        )
        # VideoAnalyses doesn't have evidence_tier, so filters should be None
        call_kwargs = mock_weaviate_client["collection"].query.hybrid.call_args[1]
        assert call_kwargs["filters"] is None

    async def test_source_tool_filter(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search applies source_tool filter to any collection."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(
            query="test", collections=["VideoAnalyses"], source_tool="video_analyze",
        )
        call_kwargs = mock_weaviate_client["collection"].query.hybrid.call_args[1]
        assert call_kwargs["filters"] is not None
        assert result["filters_applied"] == {"source_tool": "video_analyze"}

    async def test_no_filters_applied_field_when_no_filters(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search returns filters_applied=None when no filters used."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="test")
        assert result["filters_applied"] is None

    async def test_global_limit_truncates_merged_results(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """GIVEN 3 collections return 5 hits each WHEN limit=5 THEN only 5 total results returned."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")

        def make_obj(uuid_str, score):
            obj = MagicMock()
            obj.uuid = uuid_str
            obj.properties = {"title": f"Hit {uuid_str}"}
            obj.metadata = MagicMock(score=score, rerank_score=None)
            return obj

        # 5 objects per collection, 3 collections = 15 total raw results
        objects_batch = [make_obj(f"uuid-{i}", 0.9 - i * 0.1) for i in range(5)]
        mock_collection = MagicMock()
        mock_collection.query.hybrid.return_value = MagicMock(objects=objects_batch)
        mock_weaviate_client["client"].collections.get.return_value = mock_collection

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(
            query="test", collections=["VideoAnalyses", "VideoMetadata", "ResearchFindings"], limit=5
        )

        # Should be truncated to 5, not 15
        assert result["total_results"] == 5
        assert len(result["results"]) == 5

    async def test_rejects_non_list_collections(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """GIVEN collections is a plain string WHEN calling THEN validation error is returned."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search

        result = await knowledge_search(query="test", collections="VideoAnalyses")

        assert "error" in result
        assert "list of strings" in result["error"]


class TestKnowledgeRelated:
    """Tests for knowledge_related tool."""

    async def test_returns_empty_when_disabled(self, mock_weaviate_disabled):
        """knowledge_related returns empty result when Weaviate not configured."""
        from video_research_mcp.tools.knowledge import knowledge_related
        result = await knowledge_related(object_id="test-uuid", collection="VideoAnalyses")
        assert result["related"] == []

    async def test_excludes_self_from_results(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_related excludes the source object from results."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        self_obj = MagicMock()
        self_obj.uuid = "source-uuid"
        self_obj.properties = {"title": "Self"}
        self_obj.metadata = MagicMock(distance=0.0)

        other_obj = MagicMock()
        other_obj.uuid = "other-uuid"
        other_obj.properties = {"title": "Other"}
        other_obj.metadata = MagicMock(distance=0.3)

        mock_collection = MagicMock()
        mock_collection.query.near_object.return_value = MagicMock(objects=[self_obj, other_obj])
        mock_weaviate_client["client"].collections.get.return_value = mock_collection

        from video_research_mcp.tools.knowledge import knowledge_related
        result = await knowledge_related(object_id="source-uuid", collection="VideoAnalyses")
        assert len(result["related"]) == 1
        assert result["related"][0]["object_id"] == "other-uuid"


class TestKnowledgeStats:
    """Tests for knowledge_stats tool."""

    async def test_returns_empty_when_disabled(self, mock_weaviate_disabled):
        """knowledge_stats returns empty when Weaviate not configured."""
        from video_research_mcp.tools.knowledge import knowledge_stats
        result = await knowledge_stats()
        assert result["total_objects"] == 0

    async def test_returns_stats_for_all_collections(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_stats returns stats for all 7 collections."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        mock_agg = MagicMock(total_count=5)
        mock_col = MagicMock()
        mock_col.aggregate.over_all.return_value = mock_agg
        mock_weaviate_client["client"].collections.get.return_value = mock_col

        from video_research_mcp.tools.knowledge import knowledge_stats
        result = await knowledge_stats()
        assert len(result["collections"]) == 11
        assert result["total_objects"] == 55

    async def test_returns_stats_for_single_collection(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_stats returns stats for a single collection."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        mock_agg = MagicMock(total_count=10)
        mock_col = MagicMock()
        mock_col.aggregate.over_all.return_value = mock_agg
        mock_weaviate_client["client"].collections.get.return_value = mock_col

        from video_research_mcp.tools.knowledge import knowledge_stats
        result = await knowledge_stats(collection="VideoAnalyses")
        assert len(result["collections"]) == 1
        assert result["collections"][0]["count"] == 10

    async def test_group_by_returns_groups(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_stats with group_by returns grouped counts."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        mock_agg = MagicMock(total_count=10)
        mock_col = MagicMock()
        mock_col.aggregate.over_all.return_value = mock_agg

        # Mock grouped aggregation response
        group1 = MagicMock()
        group1.grouped_by = MagicMock(value="CONFIRMED")
        group1.total_count = 7
        group2 = MagicMock()
        group2.grouped_by = MagicMock(value="INFERENCE")
        group2.total_count = 3
        mock_grouped_response = MagicMock()
        mock_grouped_response.groups = [group1, group2]

        # First call returns total count, second returns grouped
        call_count = [0]
        def over_all_side_effect(**kwargs):
            call_count[0] += 1
            if "group_by" in kwargs:
                return mock_grouped_response
            return mock_agg
        mock_col.aggregate.over_all.side_effect = over_all_side_effect

        mock_weaviate_client["client"].collections.get.return_value = mock_col

        from video_research_mcp.tools.knowledge import knowledge_stats
        result = await knowledge_stats(collection="ResearchFindings", group_by="evidence_tier")
        assert len(result["collections"]) == 1
        stats = result["collections"][0]
        assert stats["groups"] is not None
        assert stats["groups"]["CONFIRMED"] == 7
        assert stats["groups"]["INFERENCE"] == 3

    async def test_group_by_skipped_for_inapplicable_property(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_stats ignores group_by when property doesn't exist in collection."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        mock_agg = MagicMock(total_count=5)
        mock_col = MagicMock()
        mock_col.aggregate.over_all.return_value = mock_agg
        mock_weaviate_client["client"].collections.get.return_value = mock_col

        from video_research_mcp.tools.knowledge import knowledge_stats
        # VideoAnalyses doesn't have evidence_tier
        result = await knowledge_stats(collection="VideoAnalyses", group_by="evidence_tier")
        assert result["collections"][0]["groups"] is None


class TestKnowledgeIngest:
    """Tests for knowledge_ingest tool."""

    async def test_returns_error_when_disabled(self, mock_weaviate_disabled):
        """knowledge_ingest returns error when Weaviate not configured."""
        from video_research_mcp.tools.knowledge import knowledge_ingest
        result = await knowledge_ingest(collection="VideoAnalyses", properties={"title": "x"})
        assert "error" in result

    async def test_returns_ingest_result(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_ingest returns KnowledgeIngestResult dict."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_ingest
        result = await knowledge_ingest(
            collection="VideoAnalyses",
            properties={"title": "Manual entry", "summary": "Test"},
        )
        assert result["collection"] == "VideoAnalyses"
        assert result["status"] == "success"

    async def test_rejects_unknown_properties(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_ingest rejects properties not in schema."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_ingest
        result = await knowledge_ingest(
            collection="VideoAnalyses",
            properties={"title": "ok", "totally_fake_field": "bad"},
        )
        assert "error" in result

    async def test_handles_insert_error(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_ingest returns error dict on failure."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        mock_weaviate_client["collection"].data.insert.side_effect = RuntimeError("Insert failed")

        from video_research_mcp.tools.knowledge import knowledge_ingest
        result = await knowledge_ingest(
            collection="VideoAnalyses",
            properties={"title": "Will fail"},
        )
        assert "error" in result


class TestSearchModes:
    """Tests for search_type parameter in knowledge_search."""

    async def test_default_uses_hybrid(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search defaults to hybrid search."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        await knowledge_search(query="test", collections=["VideoAnalyses"])
        mock_weaviate_client["collection"].query.hybrid.assert_called_once()
        mock_weaviate_client["collection"].query.near_text.assert_not_called()
        mock_weaviate_client["collection"].query.bm25.assert_not_called()

    async def test_semantic_uses_near_text(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """search_type="semantic" dispatches to near_text."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        obj = MagicMock()
        obj.uuid = "uuid-1"
        obj.properties = {"title": "Result"}
        obj.metadata = MagicMock(distance=0.2)
        mock_weaviate_client["collection"].query.near_text.return_value = MagicMock(objects=[obj])

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(
            query="test", collections=["VideoAnalyses"], search_type="semantic",
        )
        mock_weaviate_client["collection"].query.near_text.assert_called_once()
        mock_weaviate_client["collection"].query.hybrid.assert_not_called()
        assert result["total_results"] == 1
        assert result["results"][0]["score"] == 0.8  # 1.0 - 0.2

    async def test_keyword_uses_bm25(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """search_type="keyword" dispatches to bm25."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        obj = MagicMock()
        obj.uuid = "uuid-1"
        obj.properties = {"query": "AI"}
        obj.metadata = MagicMock(score=2.5)
        mock_weaviate_client["collection"].query.bm25.return_value = MagicMock(objects=[obj])

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(
            query="AI", collections=["WebSearchResults"], search_type="keyword",
        )
        mock_weaviate_client["collection"].query.bm25.assert_called_once()
        mock_weaviate_client["collection"].query.hybrid.assert_not_called()
        assert result["total_results"] == 1
        assert result["results"][0]["score"] == 2.5

    async def test_semantic_passes_filters(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """Semantic search respects collection filters."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        mock_weaviate_client["collection"].query.near_text.return_value = MagicMock(objects=[])

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(
            query="AI", collections=["ResearchFindings"],
            search_type="semantic", evidence_tier="CONFIRMED",
        )
        call_kwargs = mock_weaviate_client["collection"].query.near_text.call_args[1]
        assert call_kwargs["filters"] is not None
        assert result["filters_applied"] == {"evidence_tier": "CONFIRMED"}


class TestKnowledgeFetch:
    """Tests for knowledge_fetch tool."""

    async def test_returns_error_when_disabled(self, mock_weaviate_disabled):
        """knowledge_fetch returns error when Weaviate not configured."""
        from video_research_mcp.tools.knowledge import knowledge_fetch
        result = await knowledge_fetch(object_id="test-uuid", collection="VideoAnalyses")
        assert "error" in result

    async def test_returns_object_when_found(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_fetch returns properties when object exists."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        obj = MagicMock()
        obj.uuid = "test-uuid-1234"
        obj.properties = {"title": "My Video", "summary": "A summary"}
        mock_weaviate_client["collection"].query.fetch_object_by_id.return_value = obj

        from video_research_mcp.tools.knowledge import knowledge_fetch
        result = await knowledge_fetch(object_id="test-uuid-1234", collection="VideoAnalyses")
        assert result["found"] is True
        assert result["collection"] == "VideoAnalyses"
        assert result["properties"]["title"] == "My Video"

    async def test_returns_not_found_for_missing_object(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_fetch returns found=False when UUID doesn't exist."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        mock_weaviate_client["collection"].query.fetch_object_by_id.return_value = None

        from video_research_mcp.tools.knowledge import knowledge_fetch
        result = await knowledge_fetch(object_id="nonexistent", collection="VideoAnalyses")
        assert result["found"] is False
        assert result["properties"] == {}

    async def test_handles_fetch_error(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_fetch returns error dict on failure."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        mock_weaviate_client["collection"].query.fetch_object_by_id.side_effect = RuntimeError("fail")

        from video_research_mcp.tools.knowledge import knowledge_fetch
        result = await knowledge_fetch(object_id="test-uuid", collection="VideoAnalyses")
        assert "error" in result


class TestMCPSerialization:
    """Tests for MCP JSON-RPC dict/list string coercion."""

    async def test_search_collections_from_json_string(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search parses collections from JSON string (MCP transport)."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        await knowledge_search(query="test", collections='["VideoAnalyses"]')
        assert mock_weaviate_client["client"].collections.get.call_count == 1

    async def test_search_collections_none_unchanged(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search searches all collections when None passed."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        await knowledge_search(query="test", collections=None)
        assert mock_weaviate_client["client"].collections.get.call_count == 11

    async def test_ingest_properties_from_json_string(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_ingest parses properties from JSON string (MCP transport)."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_ingest
        result = await knowledge_ingest(
            collection="VideoAnalyses",
            properties=json.dumps({"title": "Test", "summary": "A summary"}),
        )
        assert result["status"] == "success"

    async def test_ingest_invalid_json_string(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_ingest treats invalid JSON string as raw string (fails validation)."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_ingest
        result = await knowledge_ingest(
            collection="VideoAnalyses",
            properties="not valid json",
        )
        # String has no keys so set(properties) fails — should return error
        assert "error" in result


class TestReranking:
    """Tests for Cohere reranking integration in knowledge_search."""

    async def test_reranked_flag_false_when_disabled(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search returns reranked=False when reranker is disabled."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="test", collections=["VideoAnalyses"])
        assert result["reranked"] is False

    async def test_reranked_flag_true_when_enabled(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search returns reranked=True when reranker is enabled."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        monkeypatch.setenv("COHERE_API_KEY", "test-cohere-key")
        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="test", collections=["VideoAnalyses"])
        assert result["reranked"] is True

    async def test_overfetch_when_reranking_enabled(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search overfetches by 3x when reranking is enabled."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        monkeypatch.setenv("COHERE_API_KEY", "test-cohere-key")
        from video_research_mcp.tools.knowledge import knowledge_search
        await knowledge_search(query="test", collections=["VideoAnalyses"], limit=5)
        call_kwargs = mock_weaviate_client["collection"].query.hybrid.call_args[1]
        assert call_kwargs["limit"] == 15  # 5 * 3

    async def test_rerank_score_extracted(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search extracts rerank_score from metadata."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        monkeypatch.setenv("COHERE_API_KEY", "test-cohere-key")

        obj = MagicMock()
        obj.uuid = "uuid-1"
        obj.properties = {"title": "Test"}
        obj.metadata = MagicMock(score=0.5, rerank_score=0.92)
        mock_weaviate_client["collection"].query.hybrid.return_value = MagicMock(objects=[obj])

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="test", collections=["VideoAnalyses"])
        assert result["results"][0]["rerank_score"] == 0.92

    async def test_flash_processed_reflects_actual_success(
        self, mock_weaviate_client, clean_config, monkeypatch, mock_gemini_client
    ):
        """knowledge_search sets flash_processed based on whether summaries were generated."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        obj = MagicMock()
        obj.uuid = "uuid-1"
        obj.properties = {"title": "Test"}
        obj.metadata = MagicMock(score=0.5, rerank_score=None)
        mock_weaviate_client["collection"].query.hybrid.return_value = MagicMock(objects=[obj])

        from video_research_mcp.models.knowledge import HitSummary, HitSummaryBatch
        mock_gemini_client["generate_structured"].return_value = HitSummaryBatch(
            summaries=[HitSummary(
                object_id="uuid-1", relevance=0.9, summary="Relevant", useful_properties=["title"],
            )],
        )

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="test", collections=["VideoAnalyses"])
        assert result["flash_processed"] is True

    async def test_flash_processed_false_on_silent_failure(
        self, mock_weaviate_client, clean_config, monkeypatch, mock_gemini_client
    ):
        """knowledge_search sets flash_processed=False when Flash fails silently."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        obj = MagicMock()
        obj.uuid = "uuid-1"
        obj.properties = {"title": "Test"}
        obj.metadata = MagicMock(score=0.5, rerank_score=None)
        mock_weaviate_client["collection"].query.hybrid.return_value = MagicMock(objects=[obj])

        mock_gemini_client["generate_structured"].side_effect = RuntimeError("Flash down")

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="test", collections=["VideoAnalyses"])
        assert result["flash_processed"] is False

    async def test_flash_disabled_flag(
        self, mock_weaviate_client, clean_config, monkeypatch
    ):
        """knowledge_search returns flash_processed=False when FLASH_SUMMARIZE=false."""
        monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
        monkeypatch.setenv("FLASH_SUMMARIZE", "false")
        obj = MagicMock()
        obj.uuid = "uuid-1"
        obj.properties = {"title": "Test"}
        obj.metadata = MagicMock(score=0.5, rerank_score=None)
        mock_weaviate_client["collection"].query.hybrid.return_value = MagicMock(objects=[obj])

        from video_research_mcp.tools.knowledge import knowledge_search
        result = await knowledge_search(query="test", collections=["VideoAnalyses"])
        assert result["flash_processed"] is False
