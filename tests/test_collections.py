"""Restart, canonical evidence recall and workspace context boundaries."""

import hashlib
import json
import subprocess
import sys

import pytest

from video_research_mcp.collections import execute
from video_research_mcp.corpus_index import connect, mutate, revision
from video_research_mcp.models.collections import Configure, Create, Read, Select
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.tools.collections import collections_manage


@pytest.fixture
def corpus(tmp_path, monkeypatch, clean_config):
    """GIVEN a private local root and a configured canonical index."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    scope = {"index_path": str(tmp_path / "corpus.sqlite3"), "workspace": "edit-a"}
    execute(Configure(action="configure", owned_root=str(tmp_path / "owned"), quota_bytes=100, **scope))
    execute(Create(action="create", collection="notes", expected_revision=0, kind="transcript", label="Prior work", **scope))
    return scope


def seed(scope, tmp_path, collection="notes", text="exact transcript  α"):
    """Store a real canonical observation using the existing index contract."""
    path = tmp_path / "transcript.txt"
    path.write_bytes(text.encode())
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with connect(scope["index_path"]) as db:
        expected = revision(db, collection)
    obs = {"video_id": "video-1", "observation_id": "speech-1", "source_revision": "source-r1",
           "media_digest": "a" * 64, "kind": "speech", "start_seconds": 1.125, "end_seconds": 2.875,
           "text": text, "artifact_refs": [{"artifact_id": "transcript-1", "kind": "transcript",
                                            "path": str(path), "sha256": digest}]}
    mutate(IndexRequest(action="index", index_path=scope["index_path"], collection=collection,
                        expected_revision=expected, observations=[obs]))
    return obs


def test_restart_exact_membership_and_clear_preserves_data(corpus, tmp_path):
    """WHEN the interpreter restarts THEN selection and exact membership persist."""
    obs = seed(corpus, tmp_path)
    execute(Select(action="select", collection="notes", **corpus))
    script = """import json,sys
from pathlib import Path
import video_research_mcp.dotenv as dotenv
dotenv.DEFAULT_ENV_PATH = Path(sys.argv[2])
from video_research_mcp.collections import execute
from video_research_mcp.models.collections import Read
print(json.dumps(execute(Read(action='recall',**json.loads(sys.argv[1])))))
"""
    restarted = subprocess.run([sys.executable, "-c", script, json.dumps(corpus), str(tmp_path / "absent.env")],
                               capture_output=True, text=True, timeout=20, check=True)
    result = json.loads(restarted.stdout)
    assert result["active_collection"] == "notes"
    returned = result["records"][0]
    assert all(returned[key] == value for key, value in obs.items() if key != "artifact_refs")
    assert returned["artifact_refs"][0]["sha256"] == obs["artifact_refs"][0]["sha256"]
    execute(Select(action="select", collection=None, **corpus))
    cleared = execute(Read(action="recall", **corpus))
    assert cleared["active_collection"] is None
    assert cleared["records"] == result["records"]
    with connect(corpus["index_path"]) as db:
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 1


async def test_recall_provenance_missing_and_no_provider(corpus, tmp_path, mock_gemini_client):
    """WHEN cached artifacts disappear THEN recall retains provenance and reports absence."""
    obs = seed(corpus, tmp_path)
    result = await collections_manage({"action": "recall", **corpus})
    assert result["provider_calls"] == 0
    item = result["records"][0]
    assert item["source_id"] == "video-1@source-r1"
    assert item["media_digest"] == obs["media_digest"]
    assert item["artifact_refs"][0]["availability"]["state"] == "present"
    (tmp_path / "transcript.txt").unlink()
    missing = await collections_manage({"action": "recall", **corpus})
    assert missing["records"][0]["artifact_refs"][0]["availability"]["state"] == "missing"
    assert missing["records"][0]["text"] == obs["text"]
    mock_gemini_client["get"].assert_not_called()
    mock_gemini_client["generate"].assert_not_called()


async def test_workspace_focus_and_cross_workspace_refusal(corpus, tmp_path):
    """GIVEN two contexts THEN selecting another context's collection fails closed."""
    other = {**corpus, "workspace": "edit-b"}
    execute(Configure(action="configure", owned_root=str(tmp_path / "other"), quota_bytes=100, **other))
    execute(Create(action="create", collection="comments", expected_revision=0, kind="comments", label="Audience", **other))
    execute(Select(action="select", collection="notes", **corpus))
    execute(Select(action="select", collection="comments", **other))
    error = await collections_manage({"action": "select", "collection": "notes", **other})
    assert error["category"] == "PERMISSION_DENIED"
    assert execute(Read(action="list", **corpus))["active_collection"] == "notes"
    assert execute(Read(action="list", **other))["active_collection"] == "comments"
    assert [r["collection"] for r in execute(Read(action="list", **other))["records"]] == ["comments"]


def test_existing_index_enrollment_and_revision_conflict(corpus, tmp_path):
    """WHEN existing corpus data is enrolled THEN no shadow observations are created."""
    seed(corpus, tmp_path, collection="existing")
    with connect(corpus["index_path"]) as db:
        old = revision(db, "existing")
    execute(Create(action="create", collection="existing", expected_revision=old, kind="mixed", label="Existing", **corpus))
    records = execute(Read(action="recall", collection="existing", **corpus))["records"]
    assert records[0]["text"] == "exact transcript  α"
    with connect(corpus["index_path"]) as db:
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 1
        assert revision(db, "existing") == old + 1
    with pytest.raises(ValueError, match="revision conflict"):
        execute(Create(action="create", collection="absent", expected_revision=7, kind="media", label="Bad", **corpus))


def test_pagination_output_budget_no_silent_gap(corpus, tmp_path):
    """WHEN pages are bounded THEN all returned source identities remain enumerable."""
    for name in ("b", "c"):
        execute(Create(action="create", collection=name, expected_revision=0, kind="comments", label=name, **corpus))
    first = execute(Read(action="list", limit=2, **corpus))
    second = execute(Read(action="list", limit=2, offset=first["next_offset"], **corpus))
    assert [r["collection"] for r in first["records"] + second["records"]] == ["b", "c", "notes"]
    assert second["next_offset"] is None
    seed(corpus, tmp_path, text="large " * 1000)
    with pytest.raises(ValueError, match="output_bytes"):
        execute(Read(action="recall", output_bytes=1024, **corpus))


async def test_foreign_database_unchanged_and_symlink_refused(tmp_path, monkeypatch, clean_config):
    """WHEN a foreign database or symlink is supplied THEN no schema is installed."""
    import sqlite3

    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    path = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE private_data(value TEXT)")
        db.execute("INSERT INTO private_data VALUES('preserve')")
    before = path.read_bytes()
    request = {"action": "configure", "index_path": str(path), "workspace": "w", "owned_root": str(tmp_path / "owned"), "quota_bytes": 100}
    assert "error" in await collections_manage(request)
    assert path.read_bytes() == before
    link = tmp_path / "link.sqlite3"
    link.symlink_to(path)
    assert "error" in await collections_manage({**request, "index_path": str(link)})
    assert not (tmp_path / "owned").exists()
