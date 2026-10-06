"""Crash liabilities, quota accounting and indexed cleanup transaction boundaries."""

import hashlib
from pathlib import Path

import pytest

from video_research_mcp.collections import execute
from video_research_mcp.collections_store import transaction
from video_research_mcp.corpus_index import connect, mutate, revision
from video_research_mcp.models.collections import Configure, Create, Delete, Pin, Prune, Put, Read
from video_research_mcp.models.corpus import IndexRequest, VectorPatch
from video_research_mcp.tools.collections import collections_manage


@pytest.fixture
def corpus(tmp_path, monkeypatch, clean_config):
    """GIVEN one collection with a finite quota and private owned directory."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    scope = {"index_path": str(tmp_path / "index.sqlite3"), "workspace": "w"}
    execute(Configure(action="configure", owned_root=str(tmp_path / "owned"), quota_bytes=16, **scope))
    execute(Create(action="create", collection="c", kind="mixed", label="Evidence", expected_revision=0, **scope))
    return scope


def admitted(corpus, tmp_path, name="a"):
    """Admit exact dummy bytes and read the actual canonical revision."""
    source = tmp_path / (name + ".source")
    source.write_bytes(b"data")
    digest = hashlib.sha256(b"data").hexdigest()
    with connect(corpus["index_path"]) as db:
        expected = revision(db, "c")
    result = execute(Put(action="admit", collection="c", expected_revision=expected,
                         evidence={"asset_id": name, "video_id": "v", "source_revision": "r", "media_digest": digest,
                                   "kind": "video", "path": str(source), "sha256": digest, "size_bytes": 4}, **corpus))
    return Path(result["records"][0]["path"]), digest


def test_delete_receipt_joins_final_revision_and_reclaimed_size(corpus, tmp_path):
    """WHEN deletion reclaims an artifact THEN its receipt equals the final index revision."""
    target, _ = admitted(corpus, tmp_path)
    with connect(corpus["index_path"]) as db:
        expected = revision(db, "c")
    result = execute(Delete(action="delete", collection="c", expected_revision=expected, asset_id="a", **corpus))
    assert result["reclaimed_bytes"] == 4
    assert not target.exists()
    with connect(corpus["index_path"]) as db:
        assert result["index_revision"] == revision(db, "c")
    assert execute(Read(action="health", **corpus))["storage"]["reserved_bytes"] == 0


def test_fsync_failure_after_unlink_retains_unknown_cleanup_charge(corpus, tmp_path, monkeypatch):
    """WHEN unlink succeeds but durability confirmation fails THEN no successful-byte claim is made."""
    target, _ = admitted(corpus, tmp_path)
    def failed_fsync(fd):
        raise OSError("fixture durability confirmation failed")
    monkeypatch.setattr("video_research_mcp.collections_media.os.fsync", failed_fsync)
    result = execute(Prune(action="prune", target_bytes=4, **corpus))
    assert result["status"] == "partial"
    assert result["reclaimed_bytes"] == 0
    assert not target.exists()
    health = execute(Read(action="health", **corpus))["storage"]
    assert health["reserved_bytes"] == 4
    assert health["liability_count"] == 1
    assert "durability confirmation failed" in health["cleanup_liabilities"][0]["liability"]


def test_grown_owned_file_refuses_further_admission(corpus, tmp_path):
    """WHEN tracked bytes grow THEN the declared-size quota cannot admit another file."""
    target, _ = admitted(corpus, tmp_path)
    target.write_bytes(b"unaccounted private data")
    with pytest.raises(PermissionError, match="quota accounting"):
        admitted(corpus, tmp_path, "b")
    assert target.read_bytes() == b"unaccounted private data"


def test_canonical_vector_terms_and_sources_removed_atomically(corpus, tmp_path):
    """WHEN unpinned collection evidence is deleted THEN all canonical index projections disappear."""
    target, digest = admitted(corpus, tmp_path)
    with connect(corpus["index_path"]) as db:
        expected = revision(db, "c")
    observation = {"video_id": "v", "observation_id": "o", "source_revision": "r", "media_digest": digest,
                   "kind": "OCR", "start_seconds": 3.25, "end_seconds": 4.75, "text": "index projection",
                   "artifact_refs": [{"artifact_id": "a", "kind": "frame", "path": str(target), "sha256": digest}]}
    result = mutate(IndexRequest(action="index", collection="c", index_path=corpus["index_path"], expected_revision=expected,
                                 observations=[observation], vectors=[VectorPatch(observation_id="o", source_revision="r", media_digest=digest, model="fixture", values=[1, 2])]))
    execute(Pin(action="pin", collection="c", expected_revision=result["index_revision"], asset_id="a", pinned=True, **corpus))
    with connect(corpus["index_path"]) as db:
        expected = revision(db, "c")
    with pytest.raises(PermissionError, match="Pinned evidence"):
        execute(Delete(action="delete", collection="c", expected_revision=expected, **corpus))
    with connect(corpus["index_path"]) as db:
        assert [db.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in ('observations', 'vectors', 'terms', 'sources')] == [1, 1, 1, 1]
    execute(Pin(action="pin", collection="c", expected_revision=expected, asset_id="a", pinned=False, **corpus))
    with connect(corpus["index_path"]) as db:
        expected = revision(db, "c")
    deleted = execute(Delete(action="delete", collection="c", expected_revision=expected, **corpus))
    assert deleted["removed_observations"] == 1
    assert deleted["reclaimed_bytes"] == 4
    with connect(corpus["index_path"]) as db:
        assert [db.execute('SELECT count(*) FROM ' + table).fetchone()[0] for table in ('observations', 'vectors', 'terms', 'sources')] == [0, 0, 0, 0]
        assert revision(db, "c") == deleted["index_revision"]


def test_health_liabilities_are_paginated_and_bounded(corpus, tmp_path):
    """WHEN several cleanup intents remain THEN health reports the full count and a finite page."""
    for name in ("a", "b", "c"):
        admitted(corpus, tmp_path, name)
    with transaction(corpus["index_path"]) as db:
        db.execute("UPDATE collection_assets SET state='cleanup',liability=?", ("failure " * 120,))
    first = execute(Read(action="health", limit=1, **corpus))["storage"]
    second = execute(Read(action="health", limit=2, offset=first["next_offset"], **corpus))["storage"]
    assert first["liability_count"] == second["liability_count"] == 3
    assert [r["asset"] for r in first["cleanup_liabilities"] + second["cleanup_liabilities"]] == ["a", "b", "c"]
    assert second["next_offset"] is None
    assert len(first["cleanup_liabilities"][0]["liability"]) == 256


def test_root_overlap_and_config_change_refused(corpus, tmp_path):
    """WHEN roots overlap or quota changes THEN enrollment refuses rather than silently reassigning bytes."""
    with pytest.raises(PermissionError, match="overlap"):
        execute(Configure(action="configure", owned_root=str(tmp_path / "owned" / "nested"), quota_bytes=16,
                          index_path=corpus["index_path"], workspace="other"))
    with pytest.raises(ValueError, match="immutable"):
        execute(Configure(action="configure", owned_root=str(tmp_path / "owned"), quota_bytes=17, **corpus))


async def test_quota_tool_receipt_is_local_terminal_and_no_provider(corpus, tmp_path, mock_gemini_client):
    """WHEN local storage is full THEN the tool returns a terminal local remediation receipt."""
    for name in ("a", "b", "c", "d"):
        admitted(corpus, tmp_path, name)
    source = tmp_path / "overflow"
    source.write_bytes(b"data")
    with connect(corpus["index_path"]) as db:
        expected = revision(db, "c")
    error = await collections_manage({"action": "admit", "collection": "c", "expected_revision": expected,
                                      "evidence": {"asset_id": "overflow", "video_id": "v", "source_revision": "r", "media_digest": "a" * 64,
                                                   "kind": "video", "path": str(source), "sha256": hashlib.sha256(b"data").hexdigest(), "size_bytes": 4}, **corpus})
    assert error["category"] == "FILE_TOO_LARGE"
    assert error["retryable"] is False
    assert "Prune unreferenced" in error["hint"]
    mock_gemini_client["get"].assert_not_called()
    assert execute(Read(action="health", **corpus))["storage"]["reserved_bytes"] == 16


def test_corrupt_unrelated_reference_retains_partial_cleanup_intent(corpus, tmp_path):
    """WHEN canonical reference metadata is corrupt THEN deletion preserves owned bytes and liability."""
    target, _ = admitted(corpus, tmp_path)
    with transaction(corpus["index_path"]) as db:
        db.execute("INSERT INTO observations(collection,observation,video,revision,digest,payload) VALUES('unmanaged','bad','v','r',?,'{broken')", ("a" * 64,))
        expected = revision(db, "c")
    result = execute(Delete(action="delete", collection="c", expected_revision=expected, **corpus))
    assert result["status"] == "partial"
    assert result["reclaimed_bytes"] == 0
    assert result["cleanup_liabilities"]
    assert target.read_bytes() == b"data"
    health = execute(Read(action="health", **corpus))["storage"]
    assert health["reserved_bytes"] == 4
    assert health["liability_count"] == 1
    with connect(corpus["index_path"]) as db:
        assert db.execute("SELECT count(*) FROM observations WHERE collection='unmanaged'").fetchone()[0] == 1
