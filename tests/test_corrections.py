"""Public correction boundaries on a genuine canonical SQLite corpus."""

import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys

import pytest

from video_research_mcp import cache, context_cache
from video_research_mcp.corpus_index import APPLICATION_ID, connect, mutate, revision
from video_research_mcp.media_identity import identify_source
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.tools.collections import collections_manage
from video_research_mcp.tools.corrections import correction_manage


def current(scope):
    """Read the actual shared optimistic collection revision."""
    with connect(scope["index_path"]) as db:
        return revision(db, scope["collection"])


@pytest.fixture
async def corpus(tmp_path, monkeypatch, clean_config):
    """GIVEN two exact source revisions in an enrolled private workspace."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    for name, value in (("_registry", {}), ("_pending", {}), ("_suppressed", set()), ("_last_failure", {}), ("_loaded", False)):
        monkeypatch.setattr(context_cache, name, value)
    scope = {"index_path": str(tmp_path / "canonical.sqlite3"), "workspace": "editor", "collection": "lessons"}
    configured = await collections_manage({"action": "configure", "index_path": scope["index_path"], "workspace": scope["workspace"],
                                          "owned_root": str(tmp_path / "owned"), "quota_bytes": 10000})
    assert configured["status"] == "configured"
    assert (tmp_path / "owned").stat().st_mode & 0o777 == 0o700
    created = await collections_manage({"action": "create", **scope, "expected_revision": 0, "kind": "mixed", "label": "Corrections"})
    assert created["status"] == "created"
    refs, observations = [], []
    for number, text in ((1, "Original quote: 41 α"), (2, "Corrected quote: 42 α")):
        path = tmp_path / f"evidence-{number}.txt"
        path.write_text(text)
        obs = {"video_id": "video", "observation_id": "speech", "source_revision": f"r{number}",
               "media_digest": str(number) * 64, "kind": "speech", "start_seconds": 1.125,
               "end_seconds": 2.875, "text": text, "artifact_refs": [{"artifact_id": f"transcript-{number}",
               "kind": "transcript", "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]}
        mutate(IndexRequest(action="index", index_path=scope["index_path"], collection=scope["collection"],
                            expected_revision=current(scope), observations=[obs]))
        observations.append(obs)
        refs.append({key: obs[key] for key in ("video_id", "observation_id", "source_revision", "media_digest")})
    lesson = {"case_id": "case-1", "question": "Exact reported count? α", "original": {
        "status": "answer", "basis": "model_generated", "source_revisions": {"video": "r1"},
        "answer": "41 α", "error": None, "evidence_refs": [refs[0]]}, "corrected_answer": "42 α",
        "correction_note": "Reported count correction; no verified truth claim", "corrected_evidence_refs": [refs[1]],
        "reporter": {"actor": "reviewer", "authority": "reviewer_reported"}, "reported_at": "2026-10-06T00:00:00Z"}
    return scope, lesson, refs, observations


async def record(corpus, **extra):
    """Record through the directly callable public service."""
    scope, lesson, _, _ = corpus
    return await correction_manage({"action": "record", **scope, "expected_revision": current(scope), "lesson": lesson, **extra})


async def replay(corpus, replay_id, status="answer", answer="42 α", refs=None, **extra):
    """Supply a declared attempt without executing a provider."""
    scope, _, pointers, _ = corpus
    outcome = {"status": status, "basis": "model_generated", "source_revisions": {"video": "r2"},
               "evidence_refs": [pointers[1]] if refs is None else refs}
    if status == "answer":
        outcome["answer"] = answer
    if status in {"error", "provider_error"}:
        outcome["error"] = "exact failure: quota/timeout α"
    return await correction_manage({"action": "replay", **scope, "case_id": "case-1", "replay_id": replay_id,
                                   "change_revision": "code-r2", "expected_revision": current(scope), "outcome": outcome, **extra})


async def test_original_and_corrected_provenance_no_provider_or_cache_claim(corpus, tmp_path, mock_gemini_client):
    """WHEN a correction is recorded THEN exact historical provenance and reported authority survive."""
    scope, lesson, refs, observations = corpus
    result = await record(corpus)
    assert result["status"] == "recorded"
    saved = result["cases"][0]
    assert saved["lesson"]["original"] == lesson["original"]
    assert saved["lesson"]["corrected_evidence_refs"] == [refs[1]]
    for key, obs in zip(("original_evidence", "corrected_evidence"), observations, strict=True):
        assert saved[key][0]["observation"] == {**obs, "entities": []}
        assert saved[key][0]["source_id"] == "video@" + obs["source_revision"]
    assert saved["verified"] is False and saved["authority_authenticated"] is False
    assert result["cache_invalidation"] == {"state": "absent", "invalidated_entries": 0,
        "scope": "persisted_semantic_answer_cache", "grounding_cache": "per_request_artifact_status_only"}
    assert result["provider_calls"] == 0
    for mock in mock_gemini_client.values():
        if hasattr(mock, "assert_not_called"):
            mock.assert_not_called()
    assert list(tmp_path.glob("*.sqlite3")) == [tmp_path / "canonical.sqlite3"]
    with connect(scope["index_path"]) as db:
        assert db.execute("PRAGMA application_id").fetchone()[0] == APPLICATION_ID


async def test_fixed_rule_all_denominators_and_original_not_overwritten(corpus):
    """WHEN replay includes every unsuccessful state THEN the complete denominator is retained."""
    scope, _, refs, _ = corpus
    original = (await record(corpus))["cases"][0]
    attempts = [("pass", "answer", "42 α"), ("fail", "answer", "43 α"),
                ("provider_error", "provider_error", None), ("abstained", "abstained", None), ("error", "error", None)]
    for expected, status, answer in attempts:
        result = await replay(corpus, expected, status, answer)
        assert result["replays"][0]["status"] == expected
        assert result["replays"][0]["verified"] is False
    missing = await replay(corpus, "missing-ref", refs=[])
    assert missing["replays"][0]["status"] == "fail"
    bad = {**refs[1], "observation_id": "absent"}
    error = await replay(corpus, "evidence-error", refs=[bad])
    assert error["replays"][0]["status"] == "error"
    assert error["replays"][0]["evaluator_error"]
    result = await correction_manage({"action": "export", **scope, "case_id": "case-1"})
    assert result["cases"] == [original]
    assert result["denominator"] == {"pass": 1, "fail": 2, "error": 2, "provider_error": 1, "abstained": 1, "total": 7}
    assert [r["ordinal"] for r in result["replays"]] == list(range(1, 8))
    assert len({r["lesson_sha256"] for r in result["replays"]}) == 1
    assert result["replays"][2]["outcome"]["error"] == "exact failure: quota/timeout α"


async def test_exact_rule_does_not_normalize_symbols_whitespace_or_numeric_claims(corpus):
    """WHEN an answer changes exact text THEN a matching reference cannot conceal it."""
    await record(corpus)
    for index, answer in enumerate(("42 a", "42 α ", "042 α", "42 α > 41")):
        result = await replay(corpus, f"changed-{index}", answer=answer)
        assert result["replays"][0]["status"] == "fail"


async def test_idempotent_identity_conflict_and_stale_revision_rollback(corpus):
    """WHEN caller identities are reused THEN only byte-equivalent lessons/attempts are repeatable."""
    scope, lesson, _, _ = corpus
    saved = await record(corpus)
    again = await record(corpus)
    assert again["status"] == "unchanged" and again["index_revision"] == saved["index_revision"]
    changed = copy.deepcopy(lesson)
    changed["original"]["answer"] = "overwritten"
    refused = await record(corpus, lesson=changed)
    assert "Immutable correction case conflict" in refused["error"]
    first = await replay(corpus, "stable")
    assert (await replay(corpus, "stable"))["index_revision"] == first["index_revision"]
    assert "Immutable replay conflict" in (await replay(corpus, "stable", answer="changed"))["error"]
    stale = await replay(corpus, "stale", expected_revision=0)
    assert "revision conflict" in stale["error"]
    assert current(scope) == first["index_revision"]


async def test_restart_paginated_history_and_explicit_change_revision(corpus, tmp_path):
    """WHEN a fresh interpreter exports fixed history THEN no original or attempt evidence disappears."""
    scope, _, _, _ = corpus
    await record(corpus)
    await replay(corpus, "one")
    await replay(corpus, "two", status="provider_error", change_revision="config-r3")
    script = """import json,sys
from pathlib import Path
import video_research_mcp.dotenv as dotenv
dotenv.DEFAULT_ENV_PATH = Path(sys.argv[2])
from video_research_mcp.corrections import execute
from video_research_mcp.models.corrections import Read
print(json.dumps(execute(Read.model_validate(json.loads(sys.argv[1])))))
"""
    request = {"action": "export", **scope, "case_id": "case-1", "limit": 1}
    restarted = subprocess.run([sys.executable, "-B", "-c", script, json.dumps(request), str(tmp_path / "absent.env")],
                               capture_output=True, text=True, timeout=20, check=True, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    result = json.loads(restarted.stdout)
    assert result["next_offset"] == 1 and result["denominator"]["total"] == 2
    second = await correction_manage({**request, "offset": result["next_offset"]})
    assert second["replays"][0]["change_revision"] == "config-r3"
    assert second["replays"][0]["status"] == "provider_error" and second["next_offset"] is None
    assert second["cases"] == result["cases"]


async def test_scope_retirement_and_preserved_metadata(corpus, tmp_path):
    """WHEN context is foreign or retired THEN reads/imports refuse while retained metadata survives."""
    scope, _, _, _ = corpus
    await record(corpus)
    denied = await correction_manage({"action": "list", **scope, "workspace": "other"})
    assert "error" in denied
    with connect(scope["index_path"]) as db:
        retained = db.execute("SELECT digest,payload FROM correction_cases").fetchone()
        before = tuple(retained)
    deleted = await collections_manage({"action": "delete", **scope, "expected_revision": current(scope)})
    assert deleted["status"] == "deleted"
    assert (await correction_manage({"action": "list", **scope}))["category"] == "PERMISSION_DENIED"
    assert "error" in await record(corpus)
    with connect(scope["index_path"]) as db:
        assert tuple(db.execute("SELECT digest,payload FROM correction_cases").fetchone()) == before
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 0


async def test_output_refusal_and_canonical_quota_rollback(corpus, monkeypatch):
    """WHEN output or canonical quota rejects admission THEN schema/data/revision changes roll back."""
    scope, _, _, _ = corpus
    before = current(scope)
    refused = await record(corpus, output_bytes=1024)
    assert "output_bytes" in refused["error"] and current(scope) == before
    with connect(scope["index_path"]) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='correction_cases'").fetchone()
    monkeypatch.setattr("video_research_mcp.collections_store.MAX_INDEX_BYTES", 1)
    refused = await record(corpus)
    assert "Canonical index exceeds" in refused["error"] and current(scope) == before
    with connect(scope["index_path"]) as db:
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='correction_cases'").fetchone()


async def test_absent_schema_read_is_nonmutating_and_tampered_history_refuses(corpus):
    """WHEN schema is absent or a retained digest is damaged THEN reads do not invent records."""
    scope, _, _, _ = corpus
    empty = await correction_manage({"action": "list", **scope})
    assert empty["cases"] == [] and empty["denominator"]["total"] == 0
    await record(corpus)
    await replay(corpus, "one")
    with connect(scope["index_path"], mode="rw") as db:
        db.execute("UPDATE correction_replays SET digest=?", ("0" * 64,))
        db.commit()
    error = await correction_manage({"action": "export", **scope, "case_id": "case-1"})
    assert "digest mismatch" in error["error"]


async def test_model_report_cannot_set_verified_or_inject_evaluator_code(corpus):
    """WHEN model-labelled corrections pass a fixed rule THEN they still cannot become verified truth."""
    scope, lesson, _, _ = corpus
    model_lesson = copy.deepcopy(lesson)
    model_lesson["reporter"]["authority"] = "model_reported"
    recorded = await record(corpus, lesson=model_lesson)
    assert recorded["cases"][0]["verified"] is False
    assert (await replay(corpus, "pass"))["replays"][0]["verified"] is False
    for extra in ({"verified": True}, {"evaluator": "__import__('os').system('exit 0')"}):
        bad = {**model_lesson, "case_id": "new", **extra}
        result = await record(corpus, lesson=bad)
        assert "error" in result
    listed = await correction_manage({"action": "list", **scope})
    assert len(listed["cases"]) == 1


async def test_oversized_retained_case_is_refused_before_decoding(corpus):
    """WHEN SQLite retains an oversized payload THEN export refuses without a decoder error."""
    scope, _, _, _ = corpus
    await record(corpus)
    before = current(scope)
    with connect(scope["index_path"], mode="rw") as db:
        db.execute("UPDATE correction_cases SET payload=?", ("x" * (256 * 1024 + 1),))
        db.commit()
    refused = await correction_manage({"action": "export", **scope, "case_id": "case-1"})
    assert "exceeds byte bound" in refused["error"] and current(scope) == before


async def test_finite_case_and_attempt_admission_keeps_prior_history(corpus, monkeypatch):
    """WHEN finite retained limits are reached THEN rejected admissions do not alter prior history."""
    scope, lesson, _, _ = corpus
    monkeypatch.setattr("video_research_mcp.corrections.MAX_CASES", 1)
    monkeypatch.setattr("video_research_mcp.corrections.MAX_REPLAYS", 2)
    await record(corpus)
    second = {**lesson, "case_id": "case-2"}
    assert "retained correction cases" in (await record(corpus, lesson=second))["error"]
    await replay(corpus, "one")
    await replay(corpus, "two", status="provider_error")
    before = current(scope)
    assert "retained replay attempts" in (await replay(corpus, "three", status="abstained"))["error"]
    assert current(scope) == before
    exported = await correction_manage({"action": "export", **scope, "case_id": "case-1"})
    assert [r["replay_id"] for r in exported["replays"]] == ["one", "two"]
    assert exported["denominator"]["total"] == 2 and exported["denominator"]["provider_error"] == 1


async def test_foreign_database_and_symlink_unchanged(tmp_path, monkeypatch, clean_config):
    """WHEN a foreign/symlink database is supplied THEN no correction schema is installed."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    path = tmp_path / "foreign.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE private(value TEXT)")
    before = path.read_bytes()
    scope = {"action": "list", "index_path": str(path), "workspace": "w", "collection": "c"}
    assert "error" in await correction_manage(scope)
    assert path.read_bytes() == before
    link = tmp_path / "link.sqlite3"
    link.symlink_to(path)
    assert "error" in await correction_manage({**scope, "index_path": str(link)})


@pytest.fixture
async def cached_corpus(corpus, tmp_path):
    """Seed real result contracts for both correction sources and an unrelated original."""
    scope, lesson, _, _ = corpus
    lesson = copy.deepcopy(lesson)
    sources, paths = [], []
    for number in (1, 2, 3):
        path = tmp_path / f"cache-source-{number}.txt"
        path.write_text(f"Exact cache source {number}")
        source = identify_source(str(path))
        sources.append(source)
        obs = {"video_id": "cached-video", "observation_id": "cached-speech", "source_revision": f"cache-r{number}",
               "media_digest": source.digest, "kind": "speech", "start_seconds": 1.125, "end_seconds": 2.875,
               "text": f"Quote {number}", "artifact_refs": [{"artifact_id": f"cache-transcript-{number}",
               "kind": "transcript", "path": str(path), "sha256": source.digest}]}
        mutate(IndexRequest(action="index", index_path=scope["index_path"], collection=scope["collection"],
                            expected_revision=current(scope), observations=[obs]))
        ref = {key: obs[key] for key in ("video_id", "observation_id", "source_revision", "media_digest")}
        if number == 1:
            lesson["original"]["source_revisions"] = {"cached-video": "cache-r1"}
            lesson["original"]["evidence_refs"] = [ref]
        elif number == 2:
            lesson["corrected_evidence_refs"] = [ref]
        for prompt in ("one", "two") if number < 3 else ("unrelated",):
            contract = {"source_digest": source.digest, "source_revision": source.revision,
                        "provider": "fixture", "account_scope": "private", "model": "mock-model", "tool_name": "answer",
                        "output_schema": {"type": "object"}, "thinking_level": "high", "prompt": prompt,
                        "metadata": None, "preprocessing": [], "window": [], "sampling": {}, "retrieval_revision": None}
            alias = sources[0].digest if number == 3 else str(path)
            assert cache.save(alias, "answer", "mock-model", {"answer": prompt}, contract=contract, source=source)
            paths.append(cache.cache_path(alias, "answer", "mock-model", contract=contract))
    registry = {source.digest: {"mock-model": f"cachedContents/fixture-{number}"}
                for number, source in enumerate(sources, 1)}
    (tmp_path / "cache/context_cache_registry.json").write_text(json.dumps(registry))
    return (scope, lesson, corpus[2], corpus[3]), paths, sources


async def test_cache_correction_invalidates_exact_source_contracts_and_is_idempotent(cached_corpus, mock_gemini_client):
    """Real original/corrected variants disappear; unrelated digest and alias collision survive."""
    data, paths, sources = cached_corpus
    unrelated = paths[-1].read_bytes()
    result = await record(data)
    assert result["cache_invalidation"]["state"] == "complete"
    assert result["cache_invalidation"]["invalidated_entries"] == 4
    assert result["context_invalidated_entries"] == 2
    assert not any(path.exists() for path in paths[:-1]) and paths[-1].read_bytes() == unrelated
    registry = json.loads((paths[-1].parent / "context_cache_registry.json").read_text())
    assert registry == {sources[2].digest: {"mock-model": "cachedContents/fixture-3"}}
    again = await record(data)
    assert again["status"] == "unchanged" and again["index_revision"] == result["index_revision"]
    assert again["cache_invalidation"]["invalidated_entries"] == 0
    assert again["cases"] == result["cases"] and result["cases"][0]["verified"] is False
    assert result["provider_calls"] == 0
    for mock in mock_gemini_client.values():
        if hasattr(mock, "assert_not_called"):
            mock.assert_not_called()


async def test_cache_correction_reports_partial_unlink_failure_and_retries_same_case(cached_corpus, monkeypatch):
    """An OS deletion failure preserves the lesson and reports actual removals, then can reconcile."""
    data, paths, _ = cached_corpus
    original = os.unlink
    blocked = paths[1].name
    def refuse(path, *args, **kwargs):
        with connect(data[0]["index_path"]) as db:
            assert db.execute("SELECT case_id FROM correction_cases").fetchone()[0] == "case-1"
        if str(path).endswith(blocked):
            raise PermissionError("fixture denied cache deletion")
        return original(path, *args, **kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(os, "unlink", refuse)
        result = await record(data)
    assert result["cache_invalidation"]["state"] in {"partial", "failed"}
    assert result["cache_errors"] and paths[1].exists() and paths[-1].exists()
    assert result["cache_invalidation"]["invalidated_entries"] == sum(not p.exists() for p in paths[:-1])
    again = await record(data)
    assert again["status"] == "unchanged" and again["index_revision"] == result["index_revision"]
    assert not any(p.exists() for p in paths[:-1]) and paths[-1].exists()
    assert again["cache_invalidation"]["state"] == "complete"


async def test_cache_correction_detects_swallowed_context_publication_failure(cached_corpus, monkeypatch):
    """Best-effort context writes cannot turn retained stale disk dependencies into completion."""
    data, paths, sources = cached_corpus
    original = type(paths[0]).replace
    def refuse(path, target):
        if str(target).endswith("context_cache_registry.json"):
            raise OSError("fixture context publication refused")
        return original(path, target)
    with monkeypatch.context() as patch:
        patch.setattr(type(paths[0]), "replace", refuse)
        result = await record(data)
    assert result["cache_invalidation"]["state"] == "partial"
    assert result["cache_invalidation"]["invalidated_entries"] == 4 and result["cache_errors"]
    assert sources[0].digest in json.loads((paths[-1].parent / "context_cache_registry.json").read_text())
    again = await record(data)
    assert again["status"] == "unchanged" and again["cache_invalidation"]["state"] == "complete"
    assert again["index_revision"] == result["index_revision"] and paths[-1].exists()


@pytest.mark.parametrize("bad_entry", ["oversized", "symlink"])
async def test_cache_correction_refuses_unbounded_or_external_envelope_reads(cached_corpus, bad_entry, tmp_path):
    """Uninspectable cache custody is explicit failure, with no unrelated deletion or truth promotion."""
    data, paths, _ = cached_corpus
    bad = paths[0].parent / "v2-bad.json"
    if bad_entry == "oversized":
        bad.write_bytes(b" " * (1024 * 1024 + 1))
    else:
        outside = tmp_path / "outside.json"
        outside.write_text('{"private":"must survive"}')
        bad.symlink_to(outside)
    result = await record(data)
    assert result["cache_invalidation"]["state"] == "failed"
    assert result["cache_invalidation"]["invalidated_entries"] == 0 and result["cache_errors"]
    assert all(path.exists() for path in paths) and result["cases"][0]["verified"] is False
    exported = await correction_manage({"action": "export", **data[0], "case_id": "case-1"})
    assert exported["cases"] == result["cases"]
    assert exported["cache_invalidation"]["state"] == "not_checked"


async def test_cache_correction_admission_refusal_does_not_invalidate(cached_corpus):
    """Output admission failure rolls back the lesson before any independent cache effect."""
    data, paths, _ = cached_corpus
    before = current(data[0])
    snapshots = [p.read_bytes() for p in paths]
    result = await record(data, output_bytes=1024)
    assert "error" in result and current(data[0]) == before
    assert [p.read_bytes() for p in paths] == snapshots


async def test_cache_correction_counts_memory_only_local_contexts(corpus):
    """A local registry dependency without a sidecar still counts when it is actually removed."""
    source = corpus[2][0]["media_digest"]
    context_cache._loaded = True
    context_cache._registry[(source, "memory-only-model")] = "cachedContents/memory-only"
    result = await record(corpus)
    assert result["context_invalidated_entries"] == 1
    assert result["cache_invalidation"] == {"state": "complete", "invalidated_entries": 0,
        "scope": "persisted_semantic_answer_cache", "grounding_cache": "per_request_artifact_status_only"}
    assert not context_cache._registry


async def test_cache_correction_preserves_legacy_absent_receipt_payload(corpus):
    """A pre-integration case with the old four-field receipt remains canonical and immutable."""
    scope = corpus[0]
    initial = await record(corpus)
    historical = initial["cases"][0]
    historical["cache_invalidation"]["state"] = "absent"
    payload = json.dumps(historical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    digest = hashlib.sha256(payload.encode()).hexdigest()
    with connect(scope["index_path"], mode="rw") as db:
        db.execute("UPDATE correction_cases SET payload=?,digest=?", (payload, digest))
        db.commit()
    exported = await correction_manage({"action": "export", **scope, "case_id": "case-1"})
    assert exported["cases"] == [historical]
    again = await record(corpus)
    assert again["status"] == "unchanged" and again["index_revision"] == initial["index_revision"]
    with connect(scope["index_path"]) as db:
        assert tuple(db.execute("SELECT payload,digest FROM correction_cases").fetchone()) == (payload, digest)


@pytest.mark.parametrize("refusal", ["none", "unlink", "publication"])
async def test_cache_correction_reconciles_stale_unrelated_context_before_effects(cached_corpus, monkeypatch, refusal):
    """GIVEN stale memory B WHEN A is invalidated/refused/retried THEN disk B and memory-only C survive."""
    data, paths, sources = cached_corpus
    sidecar = paths[-1].parent / "context_cache_registry.json"
    unrelated = paths[-1].read_bytes()
    context_cache._loaded = True
    context_cache._registry[(sources[2].digest, "mock-model")] = "cachedContents/old"
    context_cache._registry[("memory-only", "local-model")] = "cachedContents/local"
    original_unlink, original_replace = os.unlink, type(sidecar).replace
    def refuse_unlink(path, *args, **kwargs):
        if str(path) == paths[0].name:
            raise PermissionError("fixture context conflict deletion refused")
        return original_unlink(path, *args, **kwargs)
    def refuse_publication(path, target):
        if str(target).endswith("context_cache_registry.json"):
            raise OSError("fixture context conflict publication refused")
        return original_replace(path, target)
    with monkeypatch.context() as patch:
        if refusal == "unlink":
            patch.setattr(os, "unlink", refuse_unlink)
        elif refusal == "publication":
            patch.setattr(type(sidecar), "replace", refuse_publication)
        result = await record(data)
    assert json.loads(sidecar.read_text())[sources[2].digest] == {"mock-model": "cachedContents/fixture-3"}
    assert context_cache._registry[(sources[2].digest, "mock-model")] == "cachedContents/fixture-3"
    assert context_cache._registry[("memory-only", "local-model")] == "cachedContents/local"
    assert paths[-1].read_bytes() == unrelated
    assert result["cache_invalidation"]["state"] == ("complete" if refusal == "none" else "partial")
    assert bool(result["cache_errors"]) == (refusal != "none")
    again = await record(data)
    assert again["status"] == "unchanged" and again["index_revision"] == result["index_revision"]
    assert again["cases"] == result["cases"]
    assert again["cache_invalidation"]["state"] == ("absent" if refusal == "none" else "complete")
    assert json.loads(sidecar.read_text()) == {sources[2].digest: {"mock-model": "cachedContents/fixture-3"},
                                             "memory-only": {"local-model": "cachedContents/local"}}
    assert not any(path.exists() for path in paths[:-1]) and paths[-1].read_bytes() == unrelated


async def test_cache_correction_refuses_context_union_over_limit_before_effects(cached_corpus):
    """GIVEN over 200 distinct local/disk entries WHEN recording THEN cache effects are refused."""
    data, paths, _ = cached_corpus
    sidecar = paths[-1].parent / "context_cache_registry.json"
    before = sidecar.read_bytes()
    snapshots = [path.read_bytes() for path in paths]
    context_cache._loaded = True
    context_cache._registry.update({(f"memory-only-{number}", "local-model"): "cachedContents/local"
                                    for number in range(200)})
    result = await record(data)
    assert result["cache_invalidation"]["state"] == "failed" and result["cache_errors"]
    assert result["cache_invalidation"]["invalidated_entries"] == 0
    assert sidecar.read_bytes() == before and [path.read_bytes() for path in paths] == snapshots
