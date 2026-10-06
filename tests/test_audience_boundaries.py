"""Durable public audience retirement/quota and real two-connection SQLite boundaries."""

import asyncio
from contextlib import contextmanager
import copy
import threading

import pytest

from video_research_mcp import audience_store, collections_store
from video_research_mcp.corpus_index import APPLICATION_ID, connect
from video_research_mcp.tools.audience import audience_manage
from video_research_mcp.tools.collections import collections_manage


@pytest.fixture
async def audience_scope(tmp_path, monkeypatch, clean_config):
    """GIVEN a genuine canonical comments collection enrolled through its public tool."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    scope = {"index_path": str(tmp_path / "corpus.sqlite3"), "workspace": "creator"}
    configured = await collections_manage({**scope, "action": "configure",
                                          "owned_root": str(tmp_path / "owned"), "quota_bytes": 64})
    assert configured["status"] == "configured"
    created = await collections_manage({**scope, "action": "create", "collection": "comments",
                                       "expected_revision": 0, "kind": "comments", "label": "Audience"})
    assert created["index_revision"] == 1
    return {**scope, "collection": "comments"}


@pytest.fixture
def exact_sample():
    """One immutable reply with exact identifiers, timestamp spelling and Unicode quote."""
    return {"sample_id": "initial", "source_revision": "export-r1", "source": "caller_fixture",
            "source_url": "https://www.youtube.com/watch?v=video-1", "retrieved_at": "2026-01-03T12:00:00Z",
            "sampling_method": "fixed_local_fixture", "sample_size": 1, "population_size": 10,
            "comments": [{"video_id": "video-1", "comment_id": "reply-1", "thread_id": "thread-1",
                          "parent_comment_id": "parent-1", "reply_id": "reply-1",
                          "posted_at": "2026-01-02T09:15:00+01:00", "quoted_text": "  Exact reply α\n"}],
            "videos": [{"video_id": "video-1", "channel_id": "channel-1", "title": "Fixture",
                        "published_at": "2026-01-01T12:00:00Z", "duration_seconds": 30, "format": "short"}]}


def retained(scope):
    """Inspect committed canonical metadata bytes and page allocation using a fresh connection."""
    with connect(scope["index_path"]) as db:
        assert db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID
        return {"samples": [tuple(r) for r in db.execute("SELECT * FROM audience_samples ORDER BY collection,sample")],
                "catalog": [tuple(r) for r in db.execute("SELECT * FROM collection_catalog ORDER BY name")],
                "revisions": [tuple(r) for r in db.execute("SELECT * FROM collections ORDER BY name")],
                "allocated_bytes": db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]}


async def import_initial(scope, sample):
    """Admit the exact fixture through real public validation and transactional storage."""
    result = await audience_manage({**scope, "action": "import", "expected_revision": 1, "sample": sample})
    assert result["status"] == "imported" and result["index_revision"] == 2
    return result


async def test_retired_audience_refuses_reads_import_and_retains_quota_metadata(
    audience_scope, exact_sample, monkeypatch
):
    """WHEN a comments collection retires THEN reads/import refuse and quota rollback retains all history."""
    scope = audience_scope
    receipt = await import_initial(scope, exact_sample)
    before = retained(scope)
    deleted = await collections_manage({**scope, "action": "delete", "expected_revision": 2})
    assert deleted["status"] == "deleted" and deleted["index_revision"] == 3
    after = retained(scope)
    assert after["samples"] == before["samples"]
    assert after["samples"][0][2] == receipt["sample_sha256"]
    search = {**scope, "action": "search", "sample_ids": ["initial"], "query": "exact"}
    requests = [search, {**scope, "action": "analyze", "sample_id": "initial", "video_ids": ["video-1"], "timezone": "UTC"},
                {**scope, "action": "import", "expected_revision": 3, "sample": exact_sample}]
    for request in requests:
        refused = await audience_manage(request)
        assert refused["category"] == "PERMISSION_DENIED" and "index_revision" not in refused
        assert "absent or outside" in refused["error"]
    resurrect = await collections_manage({**scope, "action": "create", "expected_revision": 3,
                                         "kind": "comments", "label": "Re-enroll"})
    assert "already enrolled" in resurrect["error"]
    assert retained(scope) == after
    live = {**scope, "collection": "other"}
    assert (await collections_manage({**live, "action": "create", "expected_revision": 0,
                                     "kind": "comments", "label": "Other"}))["status"] == "created"
    baseline = retained(scope)
    monkeypatch.setattr(collections_store, "MAX_INDEX_BYTES", baseline["allocated_bytes"])
    large = copy.deepcopy(exact_sample)
    large.update(sample_id="quota-candidate", sample_size=24, population_size=24)
    large["comments"] = [{**exact_sample["comments"][0], "comment_id": f"q-{i}", "reply_id": f"q-{i}",
                          "quoted_text": "α" * 6000} for i in range(24)]
    quota = await audience_manage({**live, "action": "import", "expected_revision": 1, "sample": large})
    assert "Canonical index exceeds" in quota["error"] and "sample_sha256" not in quota
    assert retained(scope) == baseline
    assert (await audience_manage(search))["category"] == "PERMISSION_DENIED"


def coordinate_writer(scope, sample, action, monkeypatch):
    """Trace real SQL; commit a second real connection after payload reads, before the revision read."""
    done = threading.Event()
    evidence = {"statements": [], "connections": [], "writer": [], "errors": [], "signals": 0}
    late = copy.deepcopy(sample)
    late.update(sample_id="late", source_revision="export-r2")
    late["comments"][0].update(comment_id="reply-2", reply_id="reply-2", quoted_text="Late reply β")

    def write():
        try:
            if action == "import":
                result = asyncio.run(audience_manage({**scope, "action": "import", "expected_revision": 2, "sample": late}))
            else:
                result = asyncio.run(collections_manage({**scope, "action": "delete", "expected_revision": 2}))
            evidence["writer"].append(result)
        except Exception as error:
            evidence["errors"].append(repr(error))
        finally:
            done.set()

    worker = threading.Thread(target=write, name="audience-snapshot-writer", daemon=True)

    def trace(statement):
        evidence["statements"].append(statement)
        if statement.startswith("SELECT revision FROM collections") and not evidence["signals"]:
            evidence["signals"] += 1
            worker.start()
            if not done.wait(8):
                evidence["errors"].append("writer_commit_deadline")

    @contextmanager
    def observed_connect(path, *, mode="ro"):
        with connect(path, mode=mode) as db:
            evidence["connections"].append((threading.current_thread().name, id(db)))
            if threading.current_thread() is threading.main_thread():
                db.set_trace_callback(trace)
            yield db

    monkeypatch.setattr(audience_store, "connect", observed_connect)
    monkeypatch.setattr(collections_store, "connect", observed_connect)
    return worker, done, evidence, late


@pytest.mark.parametrize("writer_action", ["import", "retire"])
async def test_two_connection_snapshot_keeps_revision_and_samples_in_one_epoch(
    audience_scope, exact_sample, monkeypatch, writer_action
):
    """WHEN another public writer commits mid-read THEN the first receipt stays old; the next sees new state."""
    scope = audience_scope
    first = await import_initial(scope, exact_sample)
    with connect(scope["index_path"], mode="rw") as db:
        assert db.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
    worker, done, evidence, late = coordinate_writer(scope, exact_sample, writer_action, monkeypatch)
    request = {**scope, "action": "search", "sample_ids": ["initial"], "query": "reply"}
    try:
        observed = await audience_manage(request)
    finally:
        if worker.ident is not None:
            worker.join(10)
    assert done.is_set() and not worker.is_alive() and not evidence["errors"], evidence
    assert evidence["signals"] == 1 and evidence["writer"][0]["index_revision"] == 3, evidence
    main_ids = {ident for name, ident in evidence["connections"] if name == threading.main_thread().name}
    writer_ids = {ident for name, ident in evidence["connections"] if name == worker.name}
    assert main_ids and writer_ids and main_ids.isdisjoint(writer_ids)
    assert any(sql.startswith("SELECT sample,digest,payload") for sql in evidence["statements"])
    assert observed["index_revision"] == 2 and observed["records"][0]["sample_sha256"] == first["sample_sha256"]
    assert observed["records"][0]["quoted_text"] == exact_sample["comments"][0]["quoted_text"]
    assert observed["records"][0]["posted_at"] == exact_sample["comments"][0]["posted_at"]
    if writer_action == "import":
        current = await audience_manage({**request, "sample_ids": ["initial", "late"]})
        assert current["index_revision"] == 3 and current["total_matches"] == 2
        records = {r["sample_id"]: r for r in current["records"]}
        assert records["late"]["sample_sha256"] == evidence["writer"][0]["sample_sha256"]
        assert records["late"]["quoted_text"] == late["comments"][0]["quoted_text"]
    else:
        assert (await audience_manage(request))["category"] == "PERMISSION_DENIED"
        assert retained(scope)["samples"][0][2] == first["sample_sha256"]
