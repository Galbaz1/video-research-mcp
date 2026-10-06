"""Canonical identity, attributed source links and immutable restart history."""

import hashlib
import json
import subprocess
import sys

import pytest

from video_research_mcp.corpus_index import connect, mutate
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.models.wiki import Read, RemoveSource, Write
from video_research_mcp.wiki import read
from video_research_mcp.wiki_store import write, remove_source


@pytest.fixture
def sources(tmp_path, monkeypatch, clean_config):
    """GIVEN two canonical source records with independently known intervals and bytes."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    scope = {"index_path": str(tmp_path / "corpus.sqlite3")}
    observations, links = [], []
    for number, stance in [(1, "unknown"), (2, "conflicting")]:
        path = tmp_path / f"source-{number}.txt"
        text = f"source {number} reports a different claim"
        path.write_text(text)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        observations.append({"video_id": f"video-{number}", "observation_id": f"obs-{number}", "source_revision": "r1",
                             "media_digest": digest, "kind": "speech", "start_seconds": number + 0.125,
                             "end_seconds": number + 0.875, "text": text,
                             "artifact_refs": [{"artifact_id": f"transcript-{number}", "kind": "transcript", "path": str(path), "sha256": digest}]})
        links.append({"evidence_id": f"link-{number}", "collection": "sources", "video_id": f"video-{number}",
                      "observation_id": f"obs-{number}", "source_revision": "r1", "media_digest": digest,
                      "attribution": f"speaker-{number}", "claim": f"claim-{number}", "stance": stance})
    mutate(IndexRequest(action="index", collection="sources", expected_revision=0, observations=observations, **scope))
    return scope, links, observations


def update(scope, evidence, expected=0, concept="concept:shared", body="Attributable observations", kind="concept", tags=None):
    """Write an explicit identity using actual canonical source links."""
    return write(Write(action="write", concept_id=concept, kind=kind, title="Shared concept", body=body,
                       expected_revision=expected, tags=tags or [], evidence=evidence, **scope))["pages"][0]


def test_two_sources_one_canonical_concept_exact_timestamped_links(sources):
    """WHEN two sources name one explicit identity THEN one concept holds two exact attributed links."""
    scope, links, observations = sources
    page = update(scope, links)
    assert page["concept_id"] == "concept:shared"
    assert len(page["evidence"]) == 2
    for link, observation in zip(page["evidence"], observations, strict=True):
        assert link["start_seconds"] == observation["start_seconds"]
        assert link["end_seconds"] == observation["end_seconds"]
        assert link["media_digest"] == observation["media_digest"]
        assert link["source_id"] == observation["video_id"] + "@r1"
        assert link["linked_at"].endswith("+00:00")
        assert link["artifact_refs"] == observation["artifact_refs"]
    with connect(scope["index_path"]) as db:
        assert db.execute("SELECT count(*) FROM wiki_concepts").fetchone()[0] == 1
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 2
        assert db.execute("SELECT revision FROM collections WHERE name='sources'").fetchone()[0] == 1


def test_restart_recovers_exact_revision_digest_and_attribution(sources, tmp_path):
    """WHEN page text updates and the interpreter restarts THEN prior revision bytes remain recoverable."""
    scope, links, _ = sources
    first = update(scope, links[:1])
    second = update(scope, links[1:], expected=1, body="Revised caller prose")
    script = """import json,sys
from pathlib import Path
import video_research_mcp.dotenv as dotenv
dotenv.DEFAULT_ENV_PATH=Path(sys.argv[2])
from video_research_mcp.models.wiki import Read
from video_research_mcp.wiki import read
print(json.dumps(read(Read(action='history',concept_id='concept:shared',**json.loads(sys.argv[1])))))
"""
    result = subprocess.run([sys.executable, "-c", script, json.dumps(scope), str(tmp_path / "absent.env")],
                            capture_output=True, text=True, timeout=20, check=True)
    pages = json.loads(result.stdout)["pages"]
    assert pages == [second, first]
    assert pages[1]["evidence"][0]["media_digest"] == links[0]["media_digest"]
    assert second["evidence"][0] == first["evidence"][0]
    assert first["page_sha256"] != second["page_sha256"]


def test_unknown_conflicts_remain_attributed_and_ids_do_not_auto_merge(sources):
    """WHEN claims disagree THEN neither source becomes a merged verified fact."""
    scope, links, _ = sources
    page = update(scope, links)
    assert [(e["claim"], e["attribution"], e["stance"]) for e in page["evidence"]] == [
        ("claim-1", "speaker-1", "unknown"), ("claim-2", "speaker-2", "conflicting")]
    assert page["claims_are_attributed"] is True
    assert page["text_origin"] == "caller_text"
    update(scope, links[:1], concept="concept:Shared")
    listing = read(Read(action="list", **scope))
    assert {p["concept_id"] for p in listing["pages"]} == {"concept:shared", "concept:Shared"}


def test_stale_revision_bad_source_and_immutable_claim_rollback(sources):
    """WHEN an update has stale or conflicting provenance THEN history and current FTS remain unchanged."""
    scope, links, _ = sources
    first = update(scope, links[:1])
    with pytest.raises(ValueError, match="revision conflict"):
        update(scope, links[1:], expected=0)
    bad = {**links[1], "media_digest": "0" * 64}
    with pytest.raises(ValueError, match="digest mismatch"):
        update(scope, [links[0], bad], expected=1)
    with pytest.raises(ValueError, match="Immutable evidence"):
        update(scope, [{**links[0], "claim": "quietly rewritten"}], expected=1)
    assert read(Read(action="get", concept_id="concept:shared", **scope))["pages"] == [first]
    assert read(Read(action="history", concept_id="concept:shared", **scope))["pages"] == [first]


def test_source_removal_versions_all_affected_pages_and_keeps_corpus(sources):
    """WHEN a source is removed THEN other contributions survive and all earlier history remains."""
    scope, links, _ = sources
    first = update(scope, links)
    video = update(scope, links[:1], concept="video:1", kind="video")
    with pytest.raises(ValueError, match="exactly all affected"):
        remove_source(RemoveSource(action="remove_source", video_id="video-1", expected_revisions={"concept:shared": 1}, **scope))
    result = remove_source(RemoveSource(action="remove_source", video_id="video-1", expected_revisions={"concept:shared": 1, "video:1": 1}, **scope))
    assert result["modified_pages"] == 2
    shared = read(Read(action="get", concept_id="concept:shared", **scope))["pages"][0]
    assert [e["evidence_id"] for e in shared["evidence"]] == ["link-2"]
    assert shared["body"] == ""
    assert read(Read(action="get", concept_id="video:1", **scope))["pages"][0]["retired"] is True
    assert read(Read(action="get", concept_id="video:1", revision=1, **scope))["pages"] == [video]
    assert read(Read(action="history", concept_id="concept:shared", **scope))["pages"][1] == first
    with connect(scope["index_path"]) as db:
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 2


def test_list_toc_search_filters_and_page_budget(sources):
    """WHEN bounded retrieval is requested THEN filters and pagination retain enumerable identities."""
    scope, links, _ = sources
    update(scope, links, tags=["physics"])
    update(scope, links[:1], concept="topic:other", kind="topic", body="Orbital mechanics", tags=["space"])
    assert read(Read(action="search", query="orbital", **scope))["pages"][0]["concept_id"] == "topic:other"
    assert read(Read(action="search", query='"; DROP TABLE wiki_concepts; --', **scope))["status"] == "no_evidence"
    assert read(Read(action="toc", kind="topic", tag="space", **scope))["pages"][0]["concept_id"] == "topic:other"
    first = read(Read(action="list", limit=1, **scope))
    second = read(Read(action="list", offset=first["next_offset"], limit=1, **scope))
    assert len(first["pages"] + second["pages"]) == 2
    assert second["next_offset"] is None
    with pytest.raises(ValueError, match="output_bytes"):
        read(Read(action="get", concept_id="concept:shared", output_bytes=1024, **scope))
