"""Retention and cleanup decisions on canonical SQLite history and owned files."""

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

from video_research_mcp import collections_wiki_refs
from video_research_mcp.collections import execute
from video_research_mcp.collections_media import referenced
from video_research_mcp.collections_store import transaction
from video_research_mcp.collections_wiki_refs import referenced_by_wiki
from video_research_mcp.corpus_index import canonical, connect, mutate, revision
from video_research_mcp.models.collections import Configure, Create, Delete, Prune, Put
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.models.wiki import RemoveSource, Write
from video_research_mcp.wiki_store import remove_source, write


@pytest.fixture
def history(tmp_path, monkeypatch, clean_config):
    """Bind owned dummy bytes through real corpus observations into immutable wiki history."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    scope = {"index_path": str(tmp_path / "corpus.sqlite3"), "workspace": "edit"}
    execute(Configure(action="configure", owned_root=str(tmp_path / "owned"), quota_bytes=8, **scope))
    execute(Create(action="create", collection="media", kind="media", label="Owned", expected_revision=0, **scope))
    assets = {}
    for name in ("unrelated", "linked"):
        source = tmp_path / (name + ".source")
        source.write_bytes(b"data")
        digest = hashlib.sha256(b"data").hexdigest()
        with connect(scope["index_path"]) as db:
            expected = revision(db, "media")
        result = execute(Put(action="admit", collection="media", expected_revision=expected,
                             evidence={"asset_id": name, "video_id": "v", "source_revision": "r1",
                                       "media_digest": digest, "kind": "video", "path": str(source),
                                       "sha256": digest, "size_bytes": 4}, **scope))
        assets[name] = Path(result["records"][0]["path"])
    obs = {"video_id": "v", "observation_id": "o", "source_revision": "r1", "media_digest": digest,
           "kind": "speech", "start_seconds": 1.125, "end_seconds": 2.875, "text": "Attributed claim",
           "artifact_refs": [{"artifact_id": "linked", "kind": "transcript", "path": str(assets["linked"]), "sha256": digest}]}
    mutate(IndexRequest(action="index", collection="source-index", expected_revision=0, observations=[obs], index_path=scope["index_path"]))
    link = {"evidence_id": "e", "collection": "source-index", "video_id": "v", "observation_id": "o",
            "source_revision": "r1", "media_digest": digest, "attribution": "Speaker", "claim": "Uncertain claim", "stance": "unknown"}
    value = {"scope": scope, "assets": assets, "link": link, "tmp_path": tmp_path}
    append(value)
    return value


def append(history, expected=0, body="Caller text"):
    """Append an actual wiki revision without model synthesis or a replacement store."""
    return write(Write(action="write", concept_id="concept:retained", kind="concept", title="Retained",
                       expected_revision=expected, body=body, evidence=[history["link"]],
                       index_path=history["scope"]["index_path"]))["pages"][0]


def forget_corpus(history):
    """Remove source observations through real collection deletion, leaving separate owned assets."""
    scope = history["scope"]
    execute(Create(action="create", collection="source-index", kind="transcript", label="Source",
                   expected_revision=1, **scope))
    result = execute(Delete(action="delete", collection="source-index", expected_revision=2, **scope))
    assert result["removed_observations"] == 1 and result["reclaimed_bytes"] == 0


def decisions(history):
    """Read real owned asset rows and apply the source helper inside the canonical write lock."""
    with transaction(history["scope"]["index_path"]) as db:
        return {row["asset"]: referenced_by_wiki(db, row)
                for row in db.execute("SELECT * FROM collection_assets ORDER BY asset").fetchall()}


@pytest.mark.parametrize("action", ["delete", "prune"])
def test_after_corpus_forget_linked_retention_and_unrelated_reclamation(history, action):
    """WHEN corpus references disappear THEN wiki decisions retain linked bytes and unrelated bytes stay reclaimable."""
    forget_corpus(history)
    scope = history["scope"]
    with connect(scope["index_path"]) as db:
        linked = db.execute("SELECT * FROM collection_assets WHERE asset='linked'").fetchone()
        assert referenced(db, linked)
        assert referenced_by_wiki(db, linked)
    assert decisions(history) == {"linked": True, "unrelated": False}
    if action == "delete":
        result = execute(Delete(action="delete", collection="media", asset_id="unrelated", expected_revision=3, **scope))
    else:
        result = execute(Prune(action="prune", target_bytes=4, max_assets=1, **scope))
    assert result["reclaimed_bytes"] == 4
    assert not history["assets"]["unrelated"].exists()
    assert history["assets"]["linked"].read_bytes() == b"data"
    assert decisions(history) == {"linked": True}


@pytest.mark.parametrize("action", ["delete", "prune"])
def test_cleanup_preserves_asset_linked_only_by_retired_wiki_history(history, action):
    """WHEN current links and corpus disappear THEN cleanup preserves historical bytes."""
    remove_source(RemoveSource(action="remove_source", video_id="v",
                              expected_revisions={"concept:retained": 1},
                              index_path=history["scope"]["index_path"]))
    forget_corpus(history)
    scope = history["scope"]
    if action == "delete":
        with pytest.raises(PermissionError, match="referenced"):
            execute(Delete(action="delete", collection="media", asset_id="linked",
                           expected_revision=3, **scope))
    else:
        result = execute(Prune(action="prune", target_bytes=8, max_assets=2, **scope))
        assert result["reclaimed_bytes"] == 4
    assert history["assets"]["linked"].read_bytes() == b"data"


def test_updates_retirement_and_interpreter_restart_keep_historical_reference(history):
    """WHEN current links retire and corpus is forgotten THEN prior history survives a real interpreter restart."""
    first = append(history, expected=1, body="Revised café text")
    removed = remove_source(RemoveSource(action="remove_source", video_id="v",
                                        expected_revisions={"concept:retained": 2}, index_path=history["scope"]["index_path"]))
    assert removed["pages"][0]["retired"] and not removed["pages"][0]["evidence"]
    forget_corpus(history)
    assert decisions(history) == {"linked": True, "unrelated": False}
    with connect(history["scope"]["index_path"]) as db:
        assert json.loads(db.execute("SELECT payload FROM wiki_revisions WHERE revision=2").fetchone()[0])["body"] == first["body"]
        assert db.execute("SELECT count(*) FROM wiki_revisions").fetchone()[0] == 3
    script = """import json,sys
from pathlib import Path
import video_research_mcp.dotenv as dotenv
dotenv.DEFAULT_ENV_PATH=Path(sys.argv[2])
from video_research_mcp.corpus_index import connect
from video_research_mcp.collections_wiki_refs import referenced_by_wiki
with connect(sys.argv[1]) as db:
 asset=db.execute("SELECT * FROM collection_assets WHERE asset='linked'").fetchone()
 print(json.dumps({'retained':referenced_by_wiki(db,asset)}))
"""
    result = subprocess.run([sys.executable, "-c", script, history["scope"]["index_path"], str(history["tmp_path"] / "absent.env")],
                            capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(result.stdout) == {"retained": True}
    assert history["assets"]["linked"].read_bytes() == b"data"


def test_no_wiki_schema_returns_false_without_creating_tables(history):
    """WHEN wiki has never initialized in a corpus THEN cleanup acquires no new persistent state."""
    path = str(history["tmp_path"] / "plain.sqlite3")
    with connect(path, mode="rwc") as db:
        before = db.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall()
        assert not referenced_by_wiki(db, {"path": str(history["assets"]["linked"]), "digest": "a" * 64})
        assert db.execute("SELECT name FROM sqlite_master ORDER BY name").fetchall() == before


@pytest.mark.parametrize("tamper", ["digest", "json", "identity", "extra_field", "artifact_digest"])
def test_malformed_retained_payload_refuses_without_touching_files(history, tamper):
    """WHEN retained bytes or typed provenance are altered THEN cleanup cannot receive a false unreferenced result."""
    with transaction(history["scope"]["index_path"]) as db:
        db.execute("DROP TRIGGER wiki_history_no_update")
        row = db.execute("SELECT * FROM wiki_revisions").fetchone()
        value = json.loads(row["payload"])
        if tamper == "identity":
            value["revision"] = 2
        elif tamper == "extra_field":
            value["unexpected"] = True
        elif tamper == "artifact_digest":
            value["evidence"][0]["artifact_refs"][0]["sha256"] = "invalid"
        payload = "{broken" if tamper == "json" else canonical(value)
        digest = "a" * 64 if tamper == "digest" else hashlib.sha256(payload.encode()).hexdigest()
        db.execute("UPDATE wiki_revisions SET payload=?,digest=?", (payload, digest))
    with pytest.raises(ValueError):
        decisions(history)
    assert all(p.read_bytes() == b"data" for p in history["assets"].values())


def test_same_linked_path_with_conflicting_hash_refuses(history):
    """WHEN a retained path claims different bytes THEN uncertain ownership cannot become cleanup permission."""
    with connect(history["scope"]["index_path"]) as db:
        with pytest.raises(ValueError, match="conflicting digest"):
            referenced_by_wiki(db, {"path": str(history["assets"]["linked"]), "digest": "b" * 64})
    assert history["assets"]["linked"].read_bytes() == b"data"


def test_unrelated_malformed_revision_is_checked_after_matching_link(history):
    """WHEN a later historical row is corrupt THEN an early positive match cannot hide the refusal."""
    append(history, expected=1)
    with transaction(history["scope"]["index_path"]) as db:
        db.execute("DROP TRIGGER wiki_history_no_update")
        db.execute("UPDATE wiki_revisions SET digest=? WHERE revision=2", ("b" * 64,))
    with pytest.raises(ValueError, match="payload digest mismatch"):
        decisions(history)


def test_existing_revision_bound_refuses_overflow_on_small_sqlite_fixture(history, monkeypatch):
    """WHEN the scan crosses its finite row limit THEN it refuses rather than silently truncating."""
    assert collections_wiki_refs.MAX_WIKI_REVISIONS == 1000 * 100
    append(history, expected=1)
    append(history, expected=2)
    monkeypatch.setattr(collections_wiki_refs, "MAX_WIKI_REVISIONS", 2)
    with pytest.raises(ValueError, match="1000 concepts x 100"):
        decisions(history)


def test_oversized_payload_refuses_before_page_validation(history):
    """WHEN even valid JSON exceeds the existing byte cap THEN retention refuses bounded acquisition."""
    with transaction(history["scope"]["index_path"]) as db:
        db.execute("DROP TRIGGER wiki_history_no_update")
        payload = db.execute("SELECT payload FROM wiki_revisions").fetchone()[0] + " " * (128 * 1024)
        db.execute("UPDATE wiki_revisions SET payload=?,digest=?", (payload, hashlib.sha256(payload.encode()).hexdigest()))
    with pytest.raises(ValueError, match="128 KiB"):
        decisions(history)


@pytest.mark.parametrize("schema", ["missing_history", "missing_column"])
def test_partial_or_altered_schema_refuses_without_repair(history, schema):
    """WHEN wiki schema is incomplete THEN source checking refuses without initializing or repairing it."""
    with transaction(history["scope"]["index_path"]) as db:
        db.execute("DROP TABLE wiki_revisions")
        if schema == "missing_column":
            db.execute("CREATE TABLE wiki_revisions(concept TEXT,revision INTEGER,digest TEXT)")
    with pytest.raises(ValueError, match="schema"):
        decisions(history)
    assert history["assets"]["linked"].read_bytes() == b"data"


def test_symlinked_retained_reference_refuses_even_for_unrelated_asset(history):
    """WHEN a retained path becomes a symlink THEN another asset cannot bypass the path refusal."""
    linked = history["assets"]["linked"]
    outside = history["tmp_path"] / "external-fixture"
    outside.write_bytes(b"data")
    linked.unlink()
    linked.symlink_to(outside)
    with connect(history["scope"]["index_path"]) as db:
        asset = db.execute("SELECT * FROM collection_assets WHERE asset='unrelated'").fetchone()
        with pytest.raises(PermissionError, match="symlinks"):
            referenced_by_wiki(db, asset)
    assert outside.read_bytes() == b"data"
    assert history["assets"]["unrelated"].read_bytes() == b"data"


@pytest.mark.parametrize("missing", ["first", "middle", "current", "all", "orphan"])
@pytest.mark.parametrize("action", ["delete", "prune"])
def test_incomplete_history_refuses_cleanup_without_changing_owned_state(history, missing, action):
    """WHEN retained history is incomplete THEN delete/prune leave bytes, quota and revisions unchanged."""
    head = 1
    if missing != "first":
        append(history, expected=1)
        head = 2
    remove_source(RemoveSource(action="remove_source", video_id="v",
                              expected_revisions={"concept:retained": head},
                              index_path=history["scope"]["index_path"]))
    forget_corpus(history)
    scope = history["scope"]
    with connect(scope["index_path"], mode="rw") as db:
        db.execute("PRAGMA foreign_keys=OFF")
        db.execute("DROP TRIGGER wiki_history_no_delete")
        if missing == "orphan":
            db.execute("DELETE FROM wiki_concepts")
        elif missing == "all":
            db.execute("DELETE FROM wiki_revisions")
        else:
            version = 1 if missing == "first" else 2 if missing == "middle" else head + 1
            db.execute("DELETE FROM wiki_revisions WHERE revision=?", (version,))
        before = [tuple(row) for row in db.execute("SELECT * FROM collection_assets ORDER BY asset")]
        revisions = [tuple(row) for row in db.execute("SELECT * FROM collection_catalog ORDER BY name")]
        db.commit()
    with pytest.raises(ValueError, match="incomplete"):
        if action == "delete":
            execute(Delete(action="delete", collection="media", asset_id="linked", expected_revision=3, **scope))
        else:
            execute(Prune(action="prune", target_bytes=8, max_assets=2, **scope))
    with connect(scope["index_path"]) as db:
        assert [tuple(row) for row in db.execute("SELECT * FROM collection_assets ORDER BY asset")] == before
        assert [tuple(row) for row in db.execute("SELECT * FROM collection_catalog ORDER BY name")] == revisions
    assert all(path.read_bytes() == b"data" for path in history["assets"].values())
