"""Persistence, local path and page/citation integrity boundaries."""

import hashlib
import sqlite3

import pytest

from video_research_mcp.corpus_index import connect, mutate
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.models.wiki import Read, Write
from video_research_mcp.tools.wiki import wiki_manage
from video_research_mcp.wiki import read
from video_research_mcp.wiki_store import write


@pytest.fixture
def source(tmp_path, monkeypatch, clean_config):
    """GIVEN a canonical source observation and an explicit wiki contribution."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    scope = {"index_path": str(tmp_path / "index.sqlite3")}
    path = tmp_path / "source"
    path.write_bytes(b"recorded source")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    obs = {"video_id": "v", "observation_id": "o", "source_revision": "r", "media_digest": digest, "kind": "description",
           "start_seconds": 0.5, "end_seconds": 1.5, "text": "Source statement",
           "artifact_refs": [{"artifact_id": "a", "kind": "description", "path": str(path), "sha256": digest}]}
    mutate(IndexRequest(action="index", collection="c", expected_revision=0, observations=[obs], **scope))
    link = {"evidence_id": "link", "collection": "c", "video_id": "v", "observation_id": "o", "source_revision": "r",
            "media_digest": digest, "attribution": "source speaker", "claim": "attributed claim", "stance": "unknown"}
    return scope, link, path


def put(scope, link, concept="concept", expected=0):
    """Write a concrete page for a boundary fixture."""
    return write(Write(action="write", concept_id=concept, kind="concept", title="Boundary", expected_revision=expected,
                       evidence=[link], **scope))["pages"][0]


def test_sql_history_mutation_refused_and_prior_hash_exact(source):
    """WHEN another canonical connection tries to rewrite/delete history THEN SQLite refuses both effects."""
    scope, link, _ = source
    page = put(scope, link)
    with connect(scope["index_path"], mode="rw") as db:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE wiki_revisions SET payload='rewritten'")
        db.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("DELETE FROM wiki_revisions")
        db.rollback()
    assert read(Read(action="history", concept_id="concept", **scope))["pages"] == [page]


async def test_foreign_database_and_missing_index_never_create_wiki_store(tmp_path, monkeypatch, clean_config):
    """WHEN the path is foreign or absent THEN wiki refuses and creates no independent engine database."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    foreign = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(foreign) as db:
        db.execute("CREATE TABLE private(value TEXT)")
        db.execute("INSERT INTO private VALUES('preserved')")
    before = foreign.read_bytes()
    result = await wiki_manage({"action": "list", "index_path": str(foreign)})
    assert "Foreign database refused" in result["error"]
    assert foreign.read_bytes() == before
    absent = tmp_path / "missing.sqlite3"
    assert "error" in await wiki_manage({"action": "list", "index_path": str(absent)})
    assert not absent.exists()


async def test_parent_symlink_uri_and_outside_fence_refused(source, tmp_path):
    """WHEN a database path leaves the local policy THEN no page is read or written through it."""
    scope, link, _ = source
    put(scope, link)
    parent = tmp_path / "alias"
    parent.symlink_to(tmp_path, target_is_directory=True)
    for path in [str(parent / "index.sqlite3"), "https://example.invalid/index.sqlite3", str(tmp_path.parent / "outside.sqlite3")]:
        result = await wiki_manage({"action": "list", "index_path": path})
        assert "error" in result
    assert read(Read(action="list", **scope))["pages"][0]["concept_id"] == "concept"


def test_symlink_evidence_rolls_back_first_wiki_initialization(source):
    """WHEN legacy corpus metadata points to a symlink THEN wiki binding refuses without schema admission."""
    scope, link, path = source
    real = path.with_name("original")
    path.rename(real)
    path.symlink_to(real)
    with pytest.raises(PermissionError, match="symlinks"):
        put(scope, link)
    with connect(scope["index_path"]) as db:
        assert db.execute("SELECT 1 FROM sqlite_master WHERE name='wiki_concepts'").fetchone() is None
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 1


async def test_citation_ids_disambiguate_page_scoped_evidence_ids(source, mock_gemini_client):
    """WHEN two pages use the same local link ID THEN generated citations must select an unambiguous context key."""
    scope, link, _ = source
    put(scope, link, concept="concept-a")
    put(scope, {**link, "claim": "separately attributed interpretation"}, concept="concept-b")
    request = {"action": "ask", "question": "boundary", "concept_ids": ["concept-a", "concept-b"], **scope}
    result = await wiki_manage(request)
    keys = [p["evidence"][0]["citation_id"] for p in result["context"]]
    assert keys[0] != keys[1]
    mock_gemini_client["generate_structured"].return_value = {"text": "Ambiguous citation", "evidence_ids": ["link"]}
    error = await wiki_manage({**request, "mode": "gemini"})
    assert "outside retrieved context" in error["error"]


def test_snapshot_metadata_survives_canonical_observation_removal(source):
    """WHEN corpus data is removed independently THEN page history retains original source digests and spans."""
    scope, link, _ = source
    page = put(scope, link)
    with connect(scope["index_path"], mode="rw") as db:
        db.execute("DELETE FROM terms")
        db.execute("DELETE FROM observations")
        db.commit()
    history = read(Read(action="history", concept_id="concept", **scope))["pages"]
    assert history == [page]
    assert history[0]["evidence"][0]["media_digest"] == link["media_digest"]
    assert history[0]["evidence"][0]["start_seconds"] == 0.5


def test_oversized_page_and_duplicate_evidence_are_atomic(source):
    """WHEN a page cannot fit its finite envelope THEN no history, FTS or concept head is admitted."""
    scope, link, _ = source
    many = [{**link, "evidence_id": f"e-{i}", "claim": "x" * 2000} for i in range(60)]
    with pytest.raises(ValueError, match="128 KiB"):
        write(Write(action="write", concept_id="big", kind="concept", title="Big", expected_revision=0, evidence=many, **scope))
    with pytest.raises(ValueError, match="Duplicate evidence_id"):
        write(Write(action="write", concept_id="duplicate", kind="concept", title="Duplicate", expected_revision=0, evidence=[link, link], **scope))
    assert read(Read(action="list", **scope))["status"] == "no_evidence"


async def test_blank_search_and_wrong_synthesis_mode_are_typed_errors(source, mock_gemini_client):
    """WHEN required operation inputs are absent THEN validation refuses before any provider invocation."""
    scope, _, _ = source
    assert "error" in await wiki_manage({"action": "search", "query": " ", **scope})
    assert "error" in await wiki_manage({"action": "history", **scope})
    assert "error" in await wiki_manage({"action": "ask", "question": "q", "mode": "caller", **scope})
    mock_gemini_client["generate_structured"].assert_not_called()
