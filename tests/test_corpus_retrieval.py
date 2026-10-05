"""Controlled source boundaries for corpus retrieval; no service or model execution."""

import json
import sqlite3

import httpx
import pytest
from pydantic import ValidationError

from video_research_mcp.corpus_retrieval import estimate_tokens
from video_research_mcp.models.corpus import Observation, QueryRequest, VectorPatch
from video_research_mcp.tools.corpus import corpus_retrieve

SHA = "a" * 64
OTHER_SHA = "b" * 64


@pytest.fixture
def corpus(tmp_path):
    """A bounded deterministic corpus of speech, OCR and description observations."""
    def obs(oid, text="copper circuit", video="video-a", revision="r1", kind="speech"):
        return {"video_id": video, "observation_id": oid, "source_revision": revision,
                "media_digest": SHA, "kind": kind, "start_seconds": 1.125,
                "end_seconds": 2.875, "text": text, "entities": ["Copper"],
                "artifact_refs": [{"artifact_id": "artifact-" + oid,
                                   "kind": "transcript" if kind == "speech" else "frame",
                                   "path": str(tmp_path / (oid + ".json")), "sha256": SHA}]}
    def patch(oid, vector, revision="r1", model="fixture-v1"):
        return {"observation_id": oid, "source_revision": revision, "media_digest": SHA,
                "model": model, "values": vector}
    def request(action="query", collection="fixture", **values):
        base = {"action": action, "collection": collection,
                "index_path": str(tmp_path / "corpus.sqlite3")}
        if action == "query":
            base.update(query="copper", source_revisions={"video-a": "r1", "video-b": "r1"})
        return base | values
    return obs, patch, request


async def seed(corpus, observations=None, vectors=None, collection="fixture", revision=0):
    """Index real supplied metadata through the public tool boundary."""
    obs, _, request = corpus
    return await corpus_retrieve(request("index", collection, expected_revision=revision,
                                        observations=observations or [obs("one")], vectors=vectors or []))


def ids(result):
    return [c["observation_id"] for c in result["context"]["chunks"]]


async def test_fixed_cross_video_exact_sources_and_explicit_absence(corpus):
    """GIVEN three evidence types WHEN queried THEN exact source intervals survive."""
    obs, _, request = corpus
    records = [obs("speech"), obs("ocr", video="video-b", kind="OCR"),
               obs("description", video="video-b", kind="description")]
    assert (await seed(corpus, records))["status"] == "indexed"
    result = await corpus_retrieve(request(mode="fts"))
    assert set(ids(result)) == {"speech", "ocr", "description"}
    assert result["retrieval"]["active_mode"] == "fts"
    for chunk in result["context"]["chunks"]:
        original = next(o for o in records if o["observation_id"] == chunk["observation_id"])
        assert all(chunk[k] == v for k, v in original.items())
        assert chunk["source_id"] == original["video_id"] + "@r1"
    assert "answer" not in result
    assert result["evidence_verification"] == "supplied_artifact_identities_not_independently_verified"
    absent = await corpus_retrieve(request(query="unicorn", mode="fts"))
    assert absent["status"] == "no_evidence" and ids(absent) == []


@pytest.mark.parametrize("mode,vector,model,active,expected", [
    ("fts", None, None, "fts", ["a", "b"]),
    ("dense", [0, 1], "fixture-v1", "dense", ["b"]),
    ("hybrid", [0, 1], "fixture-v1", "hybrid", ["b", "a"]),
    ("dense", None, None, "fts", ["a", "b"]),
    ("hybrid", [0, 1], "wrong-model", "fts", ["a", "b"]),
    ("hybrid", [0, 1], "fixture-v1", "hybrid", ["b", "a"]),
])
async def test_modes_fallback_and_recorded_rrf(corpus, mode, vector, model, active, expected):
    obs, patch, request = corpus
    await seed(corpus, [obs("a"), obs("b", video="video-b")],
               [patch("a", [1, 0]), patch("b", [0, 1])])
    result = await corpus_retrieve(request(mode=mode, query_vector=vector, vector_model=model))
    assert result["retrieval"]["active_mode"] == active
    assert ids(result) == expected
    if active == "hybrid":
        assert result["retrieval"]["candidates"] == {"fts": ["a", "b"], "dense": ["b"]}
        assert result["retrieval"]["scores"]["b"] == pytest.approx(1 / 62 + 1 / 61)
    if mode == "dense" and vector is None:
        assert result["retrieval"]["fallback_reason"] == "no_compatible_supplied_vectors"


async def test_dense_only_fallback_and_no_dense_evidence(corpus):
    obs, patch, request = corpus
    await seed(corpus, [obs("a", "ceramic")], [patch("a", [1, 0])])
    dense = await corpus_retrieve(request(query="unicorn", query_vector=[1, 0], vector_model="fixture-v1"))
    assert dense["retrieval"]["active_mode"] == "dense" and ids(dense) == ["a"]
    absent = await corpus_retrieve(request(query="ceramic", mode="dense", query_vector=[-1, 0],
                                         vector_model="fixture-v1"))
    assert absent["status"] == "no_evidence" and absent["retrieval"]["active_mode"] == "dense"
    wrong_dim = await corpus_retrieve(request(mode="dense", query_vector=[1, 0, 0], vector_model="fixture-v1"))
    assert wrong_dim["retrieval"]["active_mode"] == "fts"


async def test_collection_revision_stale_vectors_and_atomic_repairs(corpus):
    """GIVEN old and current revisions WHEN repairing THEN only current vector state changes."""
    obs, patch, request = corpus
    await seed(corpus, [obs("a")], [patch("a", [1, 0])])
    await seed(corpus, [obs("a", "copper new", revision="r2")], revision=1)
    await seed(corpus, [obs("outsider")], collection="other")
    stale = await corpus_retrieve(request())
    assert stale["status"] == "no_evidence"
    current = request(source_revisions={"video-a": "r2"})
    result = await corpus_retrieve(current)
    assert ids(result) == ["a"] and result["retrieval"]["active_mode"] == "fts"
    with sqlite3.connect(current["index_path"]) as db:
        before = {t: db.execute("SELECT * FROM " + t).fetchall() for t in ("sources", "observations", "terms")}
    bad = await corpus_retrieve(request("repair", expected_revision=2, vectors=[patch("a", [0, 1])]))
    assert "error" in bad and "stale" in bad["error"]
    repaired = await corpus_retrieve(request("repair", expected_revision=2,
                                            vectors=[patch("a", [0, 1], revision="r2")]))
    assert repaired["status"] == "repaired" and repaired["retrieval"]["media_reads"] == 0
    with sqlite3.connect(current["index_path"]) as db:
        after = {t: db.execute("SELECT * FROM " + t).fetchall() for t in before}
    assert before == after
    assert ids(await corpus_retrieve(current | {"mode": "dense", "query_vector": [0, 1],
                                                "vector_model": "fixture-v1"})) == ["a"]
    conflict = await corpus_retrieve(request("repair", expected_revision=2,
                                            vectors=[patch("a", [1, 0], revision="r2")]))
    assert "revision conflict" in conflict["error"]


async def test_immutable_conflicts_rollback_whole_batch(corpus):
    obs, _, request = corpus
    await seed(corpus)
    failure = await seed(corpus, [obs("new"), obs("one", "tampered")], revision=1)
    assert "Immutable observation conflict" in failure["error"]
    result = await corpus_retrieve(request())
    assert ids(result) == ["one"] and result["index_revision"] == 1


async def test_context_budget_counts_complete_utf8_payload(corpus):
    obs, _, request = corpus
    await seed(corpus, [obs("a", "copper café"), obs("b", "copper résumé", video="video-b")])
    result = await corpus_retrieve(request(token_budget=256))
    assert result["estimated_tokens"] == estimate_tokens(result["context"]) <= 256
    assert result["token_estimator"] == "utf8_bytes_div4_ceil_v1"
    assert result["context"]["source_ids"] == sorted({c["source_id"] for c in result["context"]["chunks"]})
    chosen = {c["observation_id"] for c in result["context"]["chunks"]}
    assert all(set(e["observation_ids"]) <= chosen for e in result["context"]["entities"])
    tiny = await corpus_retrieve(request(token_budget=32))
    assert tiny["status"] == "no_evidence" and tiny["estimated_tokens"] <= 32


@pytest.mark.parametrize("values", [[float("nan")], [float("inf")], [0, 0], [1e7]])
def test_reject_invalid_vectors(corpus, values):
    _, patch, _ = corpus
    with pytest.raises(ValidationError):
        VectorPatch.model_validate(patch("a", values))


@pytest.mark.parametrize("change", [{"end_seconds": 0}, {"start_seconds": float("inf")},
                                    {"kind": "invented"}, {"unexpected": True}])
def test_observation_boundary(corpus, change):
    obs, _, _ = corpus
    with pytest.raises(ValidationError):
        Observation.model_validate(obs("a") | change)


async def test_uri_foreign_database_and_scoped_artifact_paths(corpus, tmp_path, monkeypatch):
    obs, _, request = corpus
    value = request("index", expected_revision=0, observations=[obs("a")])
    assert "error" in await corpus_retrieve(value | {"index_path": "https://example.org/index.sqlite3"})
    foreign = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(foreign) as db:
        db.execute("CREATE TABLE preserved(x)")
    before = foreign.read_bytes()
    assert "Foreign database" in (await corpus_retrieve(value | {"index_path": str(foreign)}))["error"]
    assert foreign.read_bytes() == before
    from types import SimpleNamespace
    from video_research_mcp import local_path_policy
    monkeypatch.setattr(local_path_policy, "get_config",
                        lambda: SimpleNamespace(local_file_access_root=str(tmp_path)))
    outside = obs("a")
    outside["artifact_refs"][0]["path"] = "/outside/ref.json"
    assert "outside LOCAL_FILE_ACCESS_ROOT" in (await seed(corpus, [outside]))["error"]


@pytest.mark.parametrize("mode", ["local", "global", "hybrid", "mix"])
async def test_pinned_graph_contract_mock_and_reference_admission(corpus, monkeypatch, mode):
    obs, _, request = corpus
    record = obs("a")
    await seed(corpus, [record])
    calls = []
    def respond(req):
        calls.append(json.loads(req.content))
        assert req.method == "POST" and req.url.path == "/query/data"
        body = {"status": "success", "message": "ok", "metadata": {"query_mode": mode},
                "data": {"chunks": [{"chunk_id": "chunk-a", "content": record["text"],
                                     "reference_id": "1", "file_path": record["artifact_refs"][0]["path"]},
                                    {"chunk_id": "bad", "content": "fabrication", "reference_id": "2",
                                     "file_path": "/unregistered"}],
                         "references": [{"reference_id": "1", "file_path": record["artifact_refs"][0]["path"]},
                                        {"reference_id": "2", "file_path": "/unregistered"}],
                         "entities": [{"entity_name": "Copper", "description": "assertion", "source_id": "chunk-a"}]}}
        return httpx.Response(200, json=body)
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(respond), **kw))
    result = await corpus_retrieve(request(graph={"endpoint": "http://127.0.0.1:9621", "mode": mode,
                                                  "hl_keywords": ["metals"], "ll_keywords": ["copper"]}))
    assert ids(result) == ["a"] and result["retrieval"]["rejected_chunks"] == 1
    assert result["context"]["entities"][0]["basis"] == "external_graph_assertion"
    assert len(calls) == 1 and calls[0]["only_need_context"] is True
    assert calls[0]["max_total_tokens"] == result["total_token_budget"]
    assert calls[0]["hl_keywords"] and calls[0]["ll_keywords"] and calls[0]["enable_rerank"] is False


@pytest.mark.parametrize("url", ["https://127.0.0.1:9", "http://localhost:9", "http://8.8.8.8:9",
                               "http://user:secret@127.0.0.1:9", "http://127.0.0.1:9/other",
                               "http://127.0.0.1:9?x=1", "file:///tmp/service"])
async def test_network_boundary_before_contact(corpus, monkeypatch, url):
    _, _, request = corpus
    await seed(corpus)
    def refuse(**kwargs):
        raise AssertionError("network contact was attempted")
    monkeypatch.setattr(httpx, "AsyncClient", refuse)
    result = await corpus_retrieve(request(graph={"endpoint": url, "hl_keywords": ["a"], "ll_keywords": ["b"]}))
    assert "loopback origin" in result["error"]


async def test_disabled_graph_adds_no_service_call(corpus, monkeypatch):
    _, _, request = corpus
    await seed(corpus)
    def refuse(**kwargs):
        raise AssertionError("disabled graph contacted a service")
    monkeypatch.setattr(httpx, "AsyncClient", refuse)
    assert (await corpus_retrieve(request()))["status"] == "found"


async def test_missing_collection_and_required_revision_scope(corpus):
    _, _, request = corpus
    await seed(corpus)
    assert (await corpus_retrieve(request(collection="absent")))["status"] == "no_evidence"
    assert "error" in await corpus_retrieve(request(source_revisions={}))
    assert "error" in await corpus_retrieve(request(collection=""))
    with pytest.raises(ValidationError):
        QueryRequest.model_validate(request(query_vector=[1, 0]))


async def test_stale_revision_cannot_be_resurrected(corpus):
    obs, _, _ = corpus
    await seed(corpus, [obs("a")])
    await seed(corpus, [obs("a", "copper current", revision="r2")], revision=1)
    result = await seed(corpus, [obs("a")], revision=2)
    assert "Stale source revision" in result["error"]


async def test_observation_identity_cannot_move_between_videos(corpus):
    obs, _, _ = corpus
    await seed(corpus, [obs("a")])
    result = await seed(corpus, [obs("a", video="video-b", revision="r2")], revision=1)
    assert "different video" in result["error"]


async def test_fts_ties_use_source_identity_not_insertion_order(corpus):
    obs, _, request = corpus
    await seed(corpus, [obs("b", video="video-b"), obs("a")])
    result = await corpus_retrieve(request(mode="fts"))
    assert ids(result) == ["a", "b"]


async def test_missing_repair_database_does_not_create_an_index(corpus):
    _, patch, request = corpus
    result = await corpus_retrieve(request("repair", expected_revision=1, vectors=[patch("a", [1])]))
    assert "error" in result
    from pathlib import Path
    assert not Path(request()["index_path"]).exists()


async def test_vector_batch_failure_preserves_first_vector(corpus):
    _, patch, request = corpus
    await seed(corpus, vectors=[patch("one", [1, 0])])
    failed = await corpus_retrieve(request("repair", expected_revision=1,
        vectors=[patch("one", [0, 1]), patch("missing", [0, 1])]))
    assert "error" in failed
    with sqlite3.connect(request()["index_path"]) as db:
        assert json.loads(db.execute("SELECT values_json FROM vectors").fetchone()[0]) == [1, 0]
    assert (await corpus_retrieve(request()))["index_revision"] == 1


@pytest.mark.parametrize("case", ["redirect", "mode", "service", "size", "provenance"])
async def test_graph_failures_and_no_evidence_are_retained(corpus, monkeypatch, case):
    _, _, request = corpus
    await seed(corpus)
    from video_research_mcp import corpus_lightrag
    body = {"status": "success", "message": "ok", "metadata": {"query_mode": "mix"},
            "data": {"chunks": [{"content": "invented", "chunk_id": "foreign",
                                 "reference_id": "1", "file_path": "/other"}],
                     "entities": [], "references": [{"reference_id": "1", "file_path": "/other"}]}}
    status = 200
    if case == "redirect":
        status = 302
    elif case == "mode":
        body["metadata"]["query_mode"] = "local"
    elif case == "service":
        status = 503
    elif case == "size":
        monkeypatch.setattr(corpus_lightrag, "MAX_RESPONSE_BYTES", 16)
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(
        transport=httpx.MockTransport(lambda req: httpx.Response(status, json=body)), **kw))
    result = await corpus_retrieve(request(graph={"endpoint": "http://127.0.0.1:9621",
                                                  "hl_keywords": ["a"], "ll_keywords": ["b"]}))
    if case == "provenance":
        assert result["status"] == "no_evidence" and result["retrieval"]["rejected_chunks"] == 1
    else:
        assert "error" in result


async def test_symlink_database_is_refused_before_writing(corpus, tmp_path):
    _, _, request = corpus
    target = tmp_path / "original.sqlite3"
    target.write_bytes(b"preserve")
    link = tmp_path / "alias.sqlite3"
    link.symlink_to(target)
    result = await corpus_retrieve(request(index_path=str(link)))
    assert "symlink" in result["error"] and target.read_bytes() == b"preserve"
