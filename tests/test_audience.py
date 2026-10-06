"""Real canonical SQLite, durable exact comments and fixed transparent analytics."""

import copy
import json
import subprocess
import sys
from pathlib import Path
import sqlite3
from unittest.mock import AsyncMock

import pytest

from video_research_mcp.collections import execute as collections
from video_research_mcp.corpus_index import APPLICATION_ID, connect, revision
from video_research_mcp.models.collections import Configure, Create, Select
from video_research_mcp.tools.audience import audience_manage


@pytest.fixture
def scope(tmp_path, monkeypatch, clean_config):
    """GIVEN one private canonical comments collection with explicit workspace context."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    value = {"index_path": str(tmp_path / "corpus.sqlite3"), "workspace": "creator"}
    collections(
        Configure(action="configure", owned_root=str(tmp_path / "owned"), quota_bytes=100, **value)
    )
    collections(
        Create(
            action="create",
            collection="comments",
            expected_revision=0,
            kind="comments",
            label="Exact audience sample",
            **value,
        )
    )
    return {**value, "collection": "comments"}


@pytest.fixture
def sample_videos():
    """Fixed caller-declared video metadata for short/long comparisons."""
    common = {"channel_id": "channel-a", "tags": ["Nature"], "opening_text": "Why imagine 3 ideas?"}
    videos = [
        {
            **common,
            "video_id": "short-1",
            "title": "A forest",
            "format": "short",
            "published_at": "2026-01-01T23:30:00Z",
            "duration_seconds": 30,
            "view_count": 100,
            "like_count": 10,
            "comment_count": 5,
        },
        {
            **common,
            "video_id": "long-1",
            "title": "The forest",
            "format": "long",
            "published_at": "2026-01-03T23:30:00Z",
            "duration_seconds": 300,
            "view_count": 0,
            "like_count": 0,
            "comment_count": 0,
        },
    ]
    return videos


@pytest.fixture
def sample(sample_videos):
    """A fixed short/long cohort with exact Unicode quotes, a reply and an empty-view video."""
    comments = [
        {
            "video_id": "short-1",
            "comment_id": "top-1",
            "thread_id": "thread-1",
            "posted_at": "2026-01-02T09:15:00+01:00",
            "quoted_text": "  GREAT tutorial, please! α\n",
            "like_count": 2,
        },
        {
            "video_id": "short-1",
            "comment_id": "reply-1",
            "thread_id": "thread-1",
            "parent_comment_id": "top-1",
            "reply_id": "reply-1",
            "posted_at": "2026-01-02T08:16:00Z",
            "quoted_text": "Audio is confusing; not good.",
            "like_count": 0,
        },
        {
            "video_id": "long-1",
            "comment_id": "top-2",
            "thread_id": "thread-2",
            "posted_at": "2026-01-03T08:00:00Z",
            "quoted_text": "Why? thanks",
            "like_count": 1,
        },
    ]
    return {
        "sample_id": "sample-r1",
        "source_revision": "export-r1",
        "source": "caller_fixture",
        "source_url": "https://www.youtube.com/watch?v=short-1",
        "retrieved_at": "2026-01-04T12:00:00Z",
        "sampling_method": "fixed_fixture_not_platform_census",
        "sample_size": 3,
        "population_size": 1000,
        "comments": comments,
        "videos": sample_videos,
    }


async def imported(scope, sample):
    """Use the public typed tool boundary to persist the fixture."""
    value = await audience_manage(
        {**scope, "action": "import", "expected_revision": 1, "sample": sample}
    )
    assert value["status"] == "imported"
    return value


async def test_exact_reply_quote_restart_and_selection_clear(scope, sample, monkeypatch):
    """WHEN connections restart and selection clears THEN exact source fields and counts survive."""
    forbidden = AsyncMock(side_effect=AssertionError("No acquisition or inference"))
    monkeypatch.setattr("video_research_mcp.youtube.YouTubeClient.video_comments", forbidden)
    sample["comments"][2].pop("like_count")
    receipt = await imported(scope, sample)
    collections(
        Select(
            action="select",
            collection="comments",
            **{k: v for k, v in scope.items() if k != "collection"},
        )
    )
    collections(
        Select(
            action="select",
            collection=None,
            **{k: v for k, v in scope.items() if k != "collection"},
        )
    )
    with connect(scope["index_path"]) as db:
        assert db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        assert revision(db, "comments") == 2
        assert db.execute("SELECT count(*) FROM audience_samples").fetchone()[0] == 1
    result = await audience_manage(
        {**scope, "action": "search", "sample_ids": ["sample-r1"], "query": "audio"}
    )
    record = result["records"][0]
    assert all(record[key] == value for key, value in sample["comments"][1].items())
    assert record["sample_size"] == 3 and record["population_size"] == 1000
    assert record["retrieved_at"] == sample["retrieved_at"]
    assert record["sample_sha256"] == receipt["sample_sha256"]
    exact = await audience_manage(
        {**scope, "action": "search", "sample_ids": ["sample-r1"], "query": "great"}
    )
    assert exact["records"][0]["quoted_text"] == "  GREAT tutorial, please! α\n"
    missing_count = await audience_manage({**scope, "action": "search", "sample_ids": ["sample-r1"], "query": "thanks"})
    assert missing_count["records"][0]["like_count"] is None
    forbidden.assert_not_called()


async def test_immutable_idempotent_revision_and_atomic_conflict(scope, sample):
    """WHEN the same identity is replayed or changed THEN replay is stable and changes refuse."""
    first = await imported(scope, sample)
    replay = await audience_manage(
        {**scope, "action": "import", "expected_revision": 2, "sample": sample}
    )
    assert replay["status"] == "unchanged" and replay["index_revision"] == 2
    assert replay["sample_sha256"] == first["sample_sha256"]
    changed = copy.deepcopy(sample)
    changed["comments"][0]["quoted_text"] = "Changed"
    refused = await audience_manage(
        {**scope, "action": "import", "expected_revision": 2, "sample": changed}
    )
    assert "Immutable sample conflict" in refused["error"]
    stale = await audience_manage(
        {**scope, "action": "import", "expected_revision": 1, "sample": sample}
    )
    assert "revision conflict" in stale["error"]
    with connect(scope["index_path"]) as db:
        assert revision(db, "comments") == 2
        assert db.execute("SELECT count(*) FROM audience_samples").fetchone()[0] == 1


async def test_normalized_metrics_zero_denominator_and_disclosed_uncertainty(
    scope, sample, mock_gemini_client
):
    """WHEN metadata has positive and zero views THEN ratios differ from unsupported accuracy claims."""
    await imported(scope, sample)
    result = await audience_manage(
        {
            **scope,
            "action": "analyze",
            "sample_id": "sample-r1",
            "video_ids": ["short-1", "long-1"],
            "timezone": "Europe/Amsterdam",
        }
    )
    value = result["analysis"]
    videos = {v["video_id"]: v for v in value["videos"]}
    assert videos["short-1"]["likes_per_view"] == {
        "numerator": 10,
        "denominator": 100,
        "value": 0.1,
        "state": "defined",
    }
    assert videos["short-1"]["engagement_per_view"]["value"] == 0.15
    assert videos["long-1"]["likes_per_view"]["state"] == "zero_denominator"
    assert videos["long-1"]["likes_per_view"]["value"] is None
    assert videos["short-1"]["hook"]["score"]["value"] == 1
    assert value["methods"]["sentiment"] == "english_term_hit_balance_v1"
    assert "confusing" in value["methods"]["lexicon"]["negative"]
    assert value["calibrated_accuracy"] is None and value["model_generated"] is False
    assert "negation" in value["uncertainty"] and "causal" in value["uncertainty"]
    assert value["sentiment"]["mixed_hits"]["numerator"] == 1
    mock_gemini_client["get"].assert_not_called()


async def test_fixed_cohort_timezone_cadence_and_niche_evidence(scope, sample):
    """WHEN the fixed cohort is analyzed THEN time windows and niche denominators remain inspectable."""
    await imported(scope, sample)
    request = {
        **scope,
        "action": "analyze",
        "sample_id": "sample-r1",
        "video_ids": ["long-1", "short-1"],
        "timezone": "Europe/Amsterdam",
    }
    first = (await audience_manage(request))["analysis"]
    second = (await audience_manage({**request, "video_ids": ["short-1", "long-1"]}))["analysis"]
    assert first == second
    assert first["cohort"]["format_basis"] == "caller_declared_short_or_long"
    assert first["formats"]["short"]["video_ids"] == ["short-1"]
    assert first["formats"]["long"]["mean_views"]["value"] == 0
    assert first["uploads"]["timezone"] == "Europe/Amsterdam"
    assert all(v["local_time"].endswith("+01:00") for v in first["uploads"]["timestamp_evidence"])
    assert first["uploads"]["cadence"][0]["median_gap_seconds"] == 172800
    candidate = next(c for c in first["niches"]["candidates"] if c["theme"] == "tutorial_requests")
    assert candidate["comment_mentions"]["numerator"] == 1
    assert candidate["comment_mentions"]["denominator"] == 3
    assert candidate["cohort_title_tag_coverage"]["denominator"] == 2
    assert candidate["covered_video_ids"] == []
    assert candidate["comment_evidence"] == [{"video_id": "short-1", "comment_id": "top-1"}]
    evidence = next(e for e in first["evidence"] if e["comment_id"] == "top-1")
    assert evidence["quoted_text"] == sample["comments"][0]["quoted_text"]
    assert first["niches"]["market_saturation"] == "UNKNOWN"


async def test_missing_counts_opening_and_empty_comment_denominator(scope, sample):
    """WHEN supplied fields are unknown THEN local summaries retain missing and empty states."""
    sample["comments"] = []
    sample["sample_size"] = 0
    sample["videos"][0].update(view_count=None, like_count=None, opening_text=None)
    await imported(scope, sample)
    value = (
        await audience_manage(
            {
                **scope,
                "action": "analyze",
                "sample_id": "sample-r1",
                "video_ids": ["short-1"],
                "timezone": "UTC",
            }
        )
    )["analysis"]
    assert value["videos"][0]["likes_per_view"]["state"] == "missing_data"
    assert value["videos"][0]["hook"]["state"] == "missing_opening_text"
    assert value["sentiment"]["unmatched"]["state"] == "zero_denominator"
    assert value["formats"]["long"]["mean_views"]["state"] == "zero_denominator"
    assert value["uploads"]["cadence"][0]["gap_count"] == 0
    assert value["niches"]["candidates"] == []


@pytest.mark.parametrize("change", ["sample_size", "duplicate", "reply", "naive", "missing_ids"])
async def test_invalid_source_provenance_refuses_before_write(scope, sample, change):
    """GIVEN incomplete/ambiguous provenance THEN no guessed identity or new revision is stored."""
    if change == "sample_size":
        sample["sample_size"] = 10
    if change == "duplicate":
        sample["comments"][2] = copy.deepcopy(sample["comments"][0])
    if change == "reply":
        sample["comments"][1]["reply_id"] = "different"
    if change == "naive":
        sample["comments"][0]["posted_at"] = "2026-01-01T12:00:00"
    if change == "missing_ids":
        sample["comments"][0] = {"text": "legacy API stripped IDs", "likes": 1, "author": "fixture"}
    refused = await audience_manage(
        {**scope, "action": "import", "expected_revision": 1, "sample": sample}
    )
    assert "error" in refused
    with connect(scope["index_path"]) as db:
        assert revision(db, "comments") == 1
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='audience_samples'"
        ).fetchone()


async def test_cross_workspace_missing_cohort_and_bad_timezone(scope, sample):
    """WHEN scope or cohort identity is not valid THEN no unrelated comments or inferred dates escape."""
    await imported(scope, sample)
    collections(Configure(action="configure", index_path=scope["index_path"], workspace="other",
                          owned_root=str(Path(scope["index_path"]).parent / "other-owned"),
                          quota_bytes=100))
    read = {**scope, "action": "search", "sample_ids": ["sample-r1"], "query": "great"}
    assert (await audience_manage({**read, "workspace": "other"}))[
        "category"
    ] == "PERMISSION_DENIED"
    analyze = {
        **scope,
        "action": "analyze",
        "sample_id": "sample-r1",
        "video_ids": ["absent"],
        "timezone": "UTC",
    }
    assert "metadata missing" in (await audience_manage(analyze))["error"]
    assert "error" in await audience_manage(
        {**analyze, "video_ids": ["short-1"], "timezone": "No/Such_Zone"}
    )
    assert "error" in await audience_manage({**read, "sample_ids": ["sample-r1", "sample-r1"]})


async def test_tampered_payload_and_output_refusal_preserve_state(scope, sample):
    """WHEN a quote exceeds the output bound or stored identity is tampered THEN it is never silently clipped."""
    sample["comments"][0]["quoted_text"] = "GREAT " + "α" * 3000
    await imported(scope, sample)
    request = {
        **scope,
        "action": "search",
        "sample_ids": ["sample-r1"],
        "query": "great",
        "output_bytes": 2048,
    }
    result = await audience_manage(request)
    assert "output_bytes" in result["error"]
    full = await audience_manage({**request, "output_bytes": 65536})
    assert full["records"][0]["quoted_text"] == sample["comments"][0]["quoted_text"]
    with connect(scope["index_path"], mode="rw") as db:
        db.execute("UPDATE audience_samples SET payload='{}'")
        db.commit()
    corrupt = await audience_manage({**request, "output_bytes": 65536})
    assert "digest mismatch" in corrupt["error"]
    with connect(scope["index_path"]) as db:
        assert revision(db, "comments") == 2


async def test_foreign_database_and_symlink_refuse_without_mutation(scope, sample, tmp_path):
    """GIVEN foreign or symlink paths THEN existing canonical path/application fences remain effective."""
    foreign = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(foreign) as db:
        db.execute("CREATE TABLE original(value)")
    request = {**scope, "action": "import", "expected_revision": 1, "sample": sample}
    assert (
        "Foreign database"
        in (await audience_manage({**request, "index_path": str(foreign)}))["error"]
    )
    with sqlite3.connect(foreign) as db:
        assert [r[0] for r in db.execute("SELECT name FROM sqlite_master")] == ["original"]
    alias = tmp_path / "alias.sqlite3"
    alias.symlink_to(scope["index_path"])
    assert (await audience_manage({**request, "index_path": str(alias)}))[
        "category"
    ] == "PERMISSION_DENIED"


async def test_utf8_admission_and_canonical_quota_failure_are_atomic(scope, sample, monkeypatch):
    """WHEN retained bytes exceed admission or canonical quota THEN source rows and revisions roll back."""
    oversized = copy.deepcopy(sample)
    oversized["comments"] = [
        {**sample["comments"][0], "comment_id": f"c{i}", "quoted_text": "α" * 4000}
        for i in range(100)
    ]
    oversized["sample_size"] = 100
    refusal = await audience_manage(
        {**scope, "action": "import", "expected_revision": 1, "sample": oversized}
    )
    assert "512 KiB" in refusal["error"]
    monkeypatch.setattr("video_research_mcp.collections_store.MAX_INDEX_BYTES", 1)
    quota = await audience_manage(
        {**scope, "action": "import", "expected_revision": 1, "sample": sample}
    )
    assert "64 MiB" in quota["error"]
    with connect(scope["index_path"]) as db:
        assert revision(db, "comments") == 1
        assert not db.execute(
            "SELECT 1 FROM sqlite_master WHERE name='audience_samples'"
        ).fetchone()


async def test_actual_interpreter_restart_retains_public_search(scope, sample, tmp_path):
    """WHEN a new local interpreter calls the public tool THEN original bytes and identities survive."""
    await imported(scope, sample)
    request = {**scope, "action": "search", "sample_ids": ["sample-r1"], "query": "great"}
    program = """import asyncio,json,sys
from pathlib import Path
import video_research_mcp.dotenv as dotenv
dotenv.DEFAULT_ENV_PATH = Path(sys.argv[2])
from video_research_mcp.tools.audience import audience_manage
print(json.dumps(asyncio.run(audience_manage(json.loads(sys.argv[1])))))
"""
    outcome = subprocess.run(
        [sys.executable, "-c", program, json.dumps(request), str(tmp_path / "absent.env")],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    )
    record = json.loads(outcome.stdout)["records"][0]
    assert record["quoted_text"] == sample["comments"][0]["quoted_text"]
    assert record["posted_at"] == sample["comments"][0]["posted_at"]
    assert record["sample_size"] == 3 and record["thread_id"] == "thread-1"


async def test_literal_unicode_search_pagination_and_unknown_sample(scope, sample):
    """WHEN a query includes SQL wildcard symbols THEN search is literal and pages do not overlap."""
    sample["comments"][0]["quoted_text"] = "Straße % exact"
    sample["comments"][1]["quoted_text"] = "STRASSE % reply"
    await imported(scope, sample)
    request = {
        **scope,
        "action": "search",
        "sample_ids": ["sample-r1"],
        "query": "strasse %",
        "limit": 1,
    }
    first = await audience_manage(request)
    second = await audience_manage({**request, "offset": first["next_offset"]})
    assert first["total_matches"] == 2 and second["next_offset"] is None
    assert first["records"][0]["comment_id"] != second["records"][0]["comment_id"]
    missing = await audience_manage({**request, "sample_ids": ["absent"]})
    assert "identities must be unique and present" in missing["error"]


async def test_dst_windows_and_explicit_subset_denominators(scope, sample):
    """WHEN a fixed cohort crosses DST THEN local offsets and cohort exclusions remain explicit."""
    sample["videos"][0]["published_at"] = "2026-03-29T00:30:00Z"
    sample["videos"][1]["published_at"] = "2026-03-29T01:30:00Z"
    await imported(scope, sample)
    request = {
        **scope,
        "action": "analyze",
        "sample_id": "sample-r1",
        "video_ids": ["short-1", "long-1"],
        "timezone": "Europe/Amsterdam",
    }
    result = (await audience_manage(request))["analysis"]
    offsets = {e["video_id"]: e["local_time"] for e in result["uploads"]["timestamp_evidence"]}
    assert offsets["short-1"].endswith("01:30:00+01:00")
    assert offsets["long-1"].endswith("03:30:00+02:00")
    assert result["uploads"]["cadence"][0]["median_gap_seconds"] == 3600
    subset = (await audience_manage({**request, "video_ids": ["long-1"]}))["analysis"]
    assert subset["denominators"]["cohort_comment_count"] == 1
    assert subset["denominators"]["imported_comment_count"] == 3
    assert subset["formats"]["short"]["sample_size"] == 0


async def test_evidence_limit_omits_unsupported_candidate_but_retains_counts(scope, sample):
    """WHEN exact evidence is bounded THEN candidates require a retained quote while denominators stay fixed."""
    await imported(scope, sample)
    result = (await audience_manage({**scope, "action": "analyze", "sample_id": "sample-r1",
                                    "video_ids": ["short-1", "long-1"], "timezone": "UTC",
                                    "evidence_limit": 1}))["analysis"]
    assert len(result["evidence"]) == 1 and result["evidence_omitted_count"] == 2
    assert "tutorial_requests" in result["niches"]["omitted_for_evidence_limit"]
    assert result["niches"]["theme_counts"]["tutorial_requests"]["comment_mentions"]["denominator"] == 3
    available = {(e["video_id"], e["comment_id"]) for e in result["evidence"]}
    assert all((ref["video_id"], ref["comment_id"]) in available
               for candidate in result["niches"]["candidates"] for ref in candidate["comment_evidence"])
