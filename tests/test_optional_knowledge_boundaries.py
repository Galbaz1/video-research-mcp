"""Optional knowledge failures, acquisition ceilings, and graph provenance."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from tests.conftest import unwrap_tool
from video_research_mcp.batch_discovery import MAX_SCAN_ENTRIES
from video_research_mcp.models.content_batch import BatchContentItem
from video_research_mcp.tools import content_batch
from video_research_mcp.tools.knowledge import retrieval, search
from video_research_mcp.weaviate_store import graph
from video_research_mcp.weaviate_store.graph import extract_and_store_graph as real_graph


@pytest.fixture
def enabled_store(monkeypatch, clean_config, mock_weaviate_client):
    """Enable only the fake store and disable optional search model work."""
    monkeypatch.setenv("WEAVIATE_URL", "https://test.weaviate.network")
    monkeypatch.setenv("FLASH_SUMMARIZE", "false")
    monkeypatch.setenv("RERANKER_ENABLED", "false")
    return mock_weaviate_client


@pytest.mark.parametrize("failure", ["count", "group"])
async def test_requested_statistics_fail_explicitly(enabled_store, failure):
    """GIVEN a failed required aggregate WHEN counting THEN return an error."""
    def aggregate(**kwargs):
        if failure == "count" or "group_by" in kwargs:
            raise PermissionError("requested aggregate denied")
        return SimpleNamespace(total_count=7)

    enabled_store["collection"].aggregate.over_all.side_effect = aggregate
    result = await unwrap_tool(retrieval.knowledge_stats)(
        collection="ResearchFindings", group_by="evidence_tier",
    )
    assert "error" in result
    assert "requested aggregate denied" in result["error"]
    assert "total_objects" not in result


async def test_genuine_empty_statistics_remain_successful(enabled_store):
    """GIVEN a successful zero count WHEN counting THEN retain the zero result."""
    enabled_store["collection"].aggregate.over_all.return_value = SimpleNamespace(total_count=0)
    result = await unwrap_tool(retrieval.knowledge_stats)(collection="VideoAnalyses")
    assert "error" not in result
    assert result["total_objects"] == 0
    assert result["collections"][0]["count"] == 0


async def test_search_failure_does_not_publish_partial_hits(enabled_store):
    """GIVEN one successful and one failed collection WHEN searching THEN fail."""
    good = Mock()
    good.query.hybrid.return_value = SimpleNamespace(objects=[SimpleNamespace(
        uuid="one", properties={"summary": "hit"},
        metadata=SimpleNamespace(score=0.8, rerank_score=None),
    )])
    bad = Mock()
    bad.query.hybrid.side_effect = PermissionError("requested search denied")
    enabled_store["client"].collections.get.side_effect = [good, bad]
    result = await unwrap_tool(search.knowledge_search)(
        query="test", collections=["VideoAnalyses", "ContentAnalyses"],
    )
    assert "error" in result
    assert "requested search denied" in result["error"]
    assert "results" not in result
    good.query.hybrid.assert_called_once()
    bad.query.hybrid.assert_called_once()


async def test_duplicate_collections_query_once_in_original_order(enabled_store):
    """GIVEN many duplicate allowed names WHEN searching THEN query each once."""
    names = ["VideoAnalyses", "VideoMetadata", "VideoAnalyses"] * 100
    result = await unwrap_tool(search.knowledge_search)(query="test", collections=names, limit=1)
    assert "error" not in result
    assert [call.args[0] for call in enabled_store["client"].collections.get.call_args_list] == [
        "VideoAnalyses", "VideoMetadata",
    ]


async def test_unknown_collection_is_refused_before_queries(enabled_store):
    """GIVEN an unknown direct-call collection WHEN searching THEN refuse it."""
    result = await unwrap_tool(search.knowledge_search)(query="test", collections=["NotACollection"])
    assert "error" in result
    enabled_store["client"].collections.get.assert_not_called()


@pytest.mark.parametrize("bound", ["date_from", "date_to"])
@pytest.mark.parametrize("value", ["not-a-date", "", "2026-02-30", "2026-10-06T25:00:00"])
async def test_search_malformed_dates_refused_before_queries(enabled_store, bound, value):
    """GIVEN a malformed supplied bound THEN refuse before any collection query."""
    result = await unwrap_tool(search.knowledge_search)(
        query="test", collections=["ResearchFindings"], **{bound: value},
    )
    assert "error" in result
    assert bound in result["error"]
    assert "ISO date" in result["error"]
    assert "results" not in result
    enabled_store["client"].collections.get.assert_not_called()
    enabled_store["collection"].query.hybrid.assert_not_called()


@pytest.mark.parametrize("date_from,date_to", [
    ("2026-10-06", "2026-10-07"),
    ("2026-10-06T12:30:00+02:00", "2026-10-07T12:30:00Z"),
])
async def test_search_valid_dates_keep_collection_aware_filters(enabled_store, monkeypatch, date_from, date_to):
    """GIVEN valid ISO bounds THEN query with dates and skip an inapplicable property."""
    from weaviate.classes.query import Filter

    by_property = Mock(wraps=Filter.by_property)
    monkeypatch.setattr(Filter, "by_property", by_property)
    result = await unwrap_tool(search.knowledge_search)(
        query="test", collections=["VideoAnalyses"],
        date_from=date_from, date_to=date_to, evidence_tier="CONFIRMED",
    )
    assert "error" not in result
    assert result["filters_applied"]["date_from"] == date_from
    assert result["filters_applied"]["date_to"] == date_to
    enabled_store["collection"].query.hybrid.assert_called_once()
    col_filter = enabled_store["collection"].query.hybrid.call_args.kwargs["filters"]
    assert col_filter is not None
    assert [call.args for call in by_property.call_args_list] == [
        ("created_at",), ("created_at",),
    ]


async def test_search_absent_dates_keep_unfiltered_query(enabled_store):
    """GIVEN no date bounds THEN retain the existing unfiltered success contract."""
    result = await unwrap_tool(search.knowledge_search)(query="test", collections=["VideoAnalyses"])
    assert "error" not in result
    assert result["filters_applied"] is None
    enabled_store["collection"].query.hybrid.assert_called_once()
    assert enabled_store["collection"].query.hybrid.call_args.kwargs["filters"] is None


def test_oversized_explicit_list_refused_before_path_work(monkeypatch):
    """GIVEN ceiling plus one paths WHEN resolving THEN touch no path."""
    resolve = Mock(side_effect=AssertionError("path work before acquisition refusal"))
    monkeypatch.setattr(content_batch, "resolve_path", resolve)
    with pytest.raises(ValueError, match="Explicit file list exceeds"):
        content_batch._resolve_files(None, ["doc.txt"] * (MAX_SCAN_ENTRIES + 1), "*", 1)
    resolve.assert_not_called()


async def test_public_oversized_list_returns_existing_error_contract(monkeypatch):
    """GIVEN excess explicit paths WHEN calling the tool THEN return its error."""
    resolve = Mock(side_effect=AssertionError("path work before acquisition refusal"))
    monkeypatch.setattr(content_batch, "resolve_path", resolve)
    result = await unwrap_tool(content_batch.content_batch_analyze)(
        file_paths=["doc.txt"] * (MAX_SCAN_ENTRIES + 1), max_files=1,
    )
    assert "error" in result
    assert "Explicit file list exceeds" in result["error"]
    resolve.assert_not_called()


def test_explicit_list_exact_ceiling_preserves_result_limit(monkeypatch):
    """GIVEN exactly the ceiling WHEN resolving THEN preserve max_files slicing."""
    path = Mock()
    path.exists.return_value = True
    path.suffix = ".txt"
    resolve = Mock(return_value=path)
    monkeypatch.setattr(content_batch, "resolve_path", resolve)
    monkeypatch.setattr(content_batch, "enforce_local_access_root", lambda value: value)
    assert content_batch._resolve_files(None, ["doc.txt"] * MAX_SCAN_ENTRIES, "*", 1) == [path]
    assert resolve.call_count == MAX_SCAN_ENTRIES


async def test_disabled_store_never_requests_graph_generation(monkeypatch, mock_weaviate_disabled):
    """GIVEN disabled persistence WHEN extracting a graph THEN make no model call."""
    generate = AsyncMock(return_value='{"concepts": [], "relationships": []}')
    monkeypatch.setattr(graph.GeminiClient, "generate", generate)
    await real_graph({"summary": "substantive analysis"}, "doc.txt")
    generate.assert_not_awaited()


async def test_enabled_graph_preserves_single_source_provenance(monkeypatch, enabled_store):
    """GIVEN a stored individual analysis WHEN extracting THEN retain its source."""
    generate = AsyncMock(return_value='{"concepts": [{"name": "A", "description": "a", '
                         '"state": "know"}], "relationships": [{"from_concept": "A", '
                         '"to_concept": "B", "type": "related_to"}]}')
    concepts, edges = AsyncMock(), AsyncMock()
    monkeypatch.setattr(graph.GeminiClient, "generate", generate)
    monkeypatch.setattr(graph, "store_concept_knowledge", concepts)
    monkeypatch.setattr(graph, "store_relationship_edges", edges)
    await real_graph({"summary": "analysis"}, "doc.txt", source_tool="content_batch_analyze")
    generate.assert_awaited_once()
    assert concepts.await_args.args[0]["source_url"] == "doc.txt"
    assert edges.await_args.args[0][0]["source_url"] == "doc.txt"


async def test_comparison_keeps_content_storage_and_skips_graph(monkeypatch, tmp_path):
    """GIVEN aggregate comparison WHEN storing THEN skip single-source graph output."""
    from video_research_mcp import weaviate_store

    paths = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for path in paths:
        path.write_text("synthetic document")
    comparison = {"summary": "combined comparison"}
    monkeypatch.setattr(content_batch, "_compare_files", AsyncMock(return_value=comparison))
    store, extract = AsyncMock(), AsyncMock()
    monkeypatch.setattr(content_batch, "store_content_analysis", store)
    monkeypatch.setattr(weaviate_store, "extract_and_store_graph", extract)
    result = await unwrap_tool(content_batch.content_batch_analyze)(
        file_paths=[str(path) for path in paths], mode="compare",
    )
    assert result["comparison"] == comparison
    assert store.await_count == 2
    assert [call.args[1] for call in store.await_args_list] == [str(path) for path in paths]
    extract.assert_not_awaited()


async def test_individual_storage_and_graph_use_only_successful_item(monkeypatch, tmp_path):
    """GIVEN one failed item WHEN storing individuals THEN retain success provenance."""
    from video_research_mcp import weaviate_store

    paths = [tmp_path / "a.txt", tmp_path / "b.txt"]
    for path in paths:
        path.write_text("synthetic document")
    data = {"summary": "individual analysis"}
    items = [BatchContentItem(file_name="a.txt", file_path=str(paths[0]), result=data),
             BatchContentItem(file_name="b.txt", file_path=str(paths[1]), error="retained failure")]
    monkeypatch.setattr(content_batch, "_individual_files", AsyncMock(return_value=items))
    store, extract = AsyncMock(), AsyncMock()
    monkeypatch.setattr(content_batch, "store_content_analysis", store)
    monkeypatch.setattr(weaviate_store, "extract_and_store_graph", extract)
    result = await unwrap_tool(content_batch.content_batch_analyze)(
        file_paths=[str(path) for path in paths], mode="individual",
    )
    assert (result["successful"], result["failed"]) == (1, 1)
    store.assert_awaited_once()
    extract.assert_awaited_once_with(data, str(paths[0]), source_tool="content_batch_analyze")
