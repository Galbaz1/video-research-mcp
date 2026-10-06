"""Source-only synthesis checks over real dummy canonical stores, never media."""

import hashlib
import json

import pytest
from pydantic import TypeAdapter

from video_research_mcp.corpus_index import canonical, connect, mutate
from video_research_mcp.models.corpus import IndexRequest
from video_research_mcp.models.synthesis import Response
from video_research_mcp.models.wiki import Write
from video_research_mcp.tools.synthesis import synthesis_manage
from video_research_mcp.wiki_store import write


def record(oid="o", **values):
    """Caller-authored source metadata; the referenced artifact is deliberately absent."""
    return {"video_id": "v", "source_revision": "r1", "media_digest": "a" * 64,
            "observation_id": oid, "start_seconds": 1, "end_seconds": 2,
            "kind": "speech", "text": "valve opens", "citation_id": oid,
            "artifact_refs": [{"artifact_id": oid, "kind": "transcript", "path": "/absent/fixture.json", "sha256": "b" * 64}],
            **values}


def fixture(records, action="cross_video", **values):
    """One bounded public request without a provider or file ingestion."""
    return {"source": {"kind": "fixture", "records": records}, "instruction": "valve",
            "action": action, **values}


@pytest.fixture
def corpus(tmp_path, monkeypatch, clean_config):
    """Write two opposing dummy observations into the existing corpus SQLite schema."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    observations = []
    for oid, video, text, start in (("one", "v", "valve opens", 1.25), ("two", "w", "valve does not open", 8.5)):
        value = record(oid, video_id=video, text=text, start_seconds=start, end_seconds=start + 1)
        value.pop("citation_id")
        value["artifact_refs"][0]["path"] = str(tmp_path / f"{oid}.json")
        observations.append(value)
    path = tmp_path / "corpus.sqlite3"
    mutate(IndexRequest(action="index", index_path=str(path), collection="c", expected_revision=0, observations=observations))
    source = {"kind": "corpus", "request": {"action": "query", "index_path": str(path), "collection": "c",
              "query": "intentionally_unrelated", "source_revisions": {"v": "r1", "w": "r1"}, "mode": "fts"}}
    return path, observations, source


async def test_public_canonical_cross_video_preserves_conflicts_and_exact_moments(corpus, mock_gemini_client, monkeypatch):
    """C1/C2: actual local retrieval, independent citations and no conflict arbitration."""
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: pytest.fail("network attempted"))
    path, observations, source = corpus
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    result = await synthesis_manage({"action": "cross_video", "instruction": "valve", "source": source})
    assert result["status"] == "complete" and result["provider_calls"] == 0
    assert result["selection"]["route"] == "corpus_retrieve.query"
    assert {s["text"] for s in result["statements"]} == {o["text"] for o in observations}
    for statement in result["statements"]:
        evidence = statement["evidence"]
        original = next(o for o in observations if o["video_id"] == evidence["video_id"])
        for field in ("observation_id", "source_revision", "media_digest", "start_seconds", "end_seconds"):
            assert evidence[field] == original[field]
        assert evidence["source_id"] == f"{original['video_id']}@r1"
        assert len(evidence["citation_id"]) == 64
        assert evidence["basis"] == "unknown" and evidence["origin"] == "canonical_corpus"
        assert statement["method"] == "retrieved_exact_quotation"
    assert result["conflict_policy"] == "retain_all_retrieved_sources_without_arbitration"
    assert before == hashlib.sha256(path.read_bytes()).hexdigest()
    TypeAdapter(Response).validate_python(result, extra="ignore")
    mock_gemini_client["get"].assert_not_called()
    mock_gemini_client["generate_structured"].assert_not_called()


async def test_canonical_wrong_revision_and_unmatched_instruction_abstain(corpus):
    _, _, source = corpus
    source["request"]["source_revisions"] = {"v": "r2", "w": "r2"}
    result = await synthesis_manage({"action": "cross_video", "instruction": "valve", "source": source})
    assert result["status"] == "abstained" and result["statements"] == []
    absent = await synthesis_manage(fixture([record()], instruction="nonexistent"))
    assert absent["status"] == "abstained"
    assert absent["abstentions"] == [{"reason": "no_retrieved_statement_for_instruction"}]


async def test_wiki_route_retains_attribution_and_conflicting_claim(corpus, mock_gemini_client):
    path, observations, _ = corpus
    links = [{"evidence_id": f"e{i}", "collection": "c", **{k: o[k] for k in
              ("video_id", "observation_id", "source_revision", "media_digest")},
              "attribution": f"source {i}", "claim": o["text"], "stance": "conflicting"}
             for i, o in enumerate(observations)]
    page = write(Write(action="write", index_path=str(path), concept_id="valve", expected_revision=0,
                       kind="concept", title="Valve", evidence=links))["pages"][0]
    source = {"kind": "wiki", "request": {"action": "ask", "index_path": str(path),
              "question": "unrelated", "concept_ids": ["valve"]}}
    result = await synthesis_manage({"action": "cross_video", "instruction": "valve", "source": source})
    assert result["selection"]["route"] == "wiki_manage.ask.context" and len(result["statements"]) == 2
    for s in result["statements"]:
        evidence = s["evidence"]
        assert evidence["stance"] == "conflicting" and evidence["claim"] == s["text"]
        assert evidence["page_sha256"] == page["page_sha256"]
        assert evidence["page_revision"] == 1 and evidence["attribution"].startswith("source ")
    mock_gemini_client["generate_structured"].assert_not_called()


async def test_conflicting_wiki_quotation_without_query_token_is_retained(corpus):
    """Selected opposing evidence stays attributed even when it uses a pronoun."""
    path, observations, _ = corpus
    observations = [observations[0], observations[1] | {"text": "It stays shut"}]
    mutate(IndexRequest(action="index", index_path=str(path), collection="pronouns",
                        expected_revision=0, observations=observations))
    links = [{"evidence_id": f"e{i}", "collection": "pronouns", **{k: o[k] for k in
              ("video_id", "observation_id", "source_revision", "media_digest")},
              "attribution": f"source {i}", "claim": o["text"], "stance": "conflicting"}
             for i, o in enumerate(observations)]
    write(Write(action="write", index_path=str(path), concept_id="valve-pronouns", expected_revision=0,
                kind="concept", title="Valve", evidence=links))
    source = {"kind": "wiki", "request": {"action": "ask", "index_path": str(path),
              "question": "valve", "concept_ids": ["valve-pronouns"]}}
    result = await synthesis_manage({"action": "cross_video", "instruction": "valve", "source": source})
    assert {s["text"] for s in result["statements"]} == {o["text"] for o in observations}
    assert {s["evidence"]["video_id"] for s in result["statements"]} == {"v", "w"}


@pytest.mark.parametrize("field", ["observation_id", "source_revision", "video_id", "media_digest"])
async def test_corrupted_canonical_identity_refuses_synthesis(corpus, field):
    """A valid payload cannot bypass the exact row identity admitted by retrieval."""
    path, _, source = corpus
    with connect(str(path), mode="rw") as db:
        row = db.execute("SELECT id,payload FROM observations WHERE collection='c' AND observation='one'").fetchone()
        value = json.loads(row["payload"])
        value[field] = "0" * 64 if field == "media_digest" else "other"
        db.execute("UPDATE observations SET payload=? WHERE id=?", (canonical(value), row["id"]))
        db.commit()
    result = await synthesis_manage({"action": "cross_video", "instruction": "valve", "source": source})
    assert "error" in result


@pytest.mark.parametrize("state", ["missing", "refused", "missing_observation", "observation_changed"])
async def test_unavailable_record_never_becomes_statement(state):
    result = await synthesis_manage(fixture([record(source_state=state)]))
    assert result["status"] == "abstained" and not result["statements"]
    assert result["abstentions"][0]["reason"] == "source_unavailable"


async def test_untimed_fixture_abstains_and_canonical_origin_cannot_be_forged():
    result = await synthesis_manage(fixture([record(start_seconds=None, end_seconds=None)]))
    assert result["status"] == "abstained" and result["abstentions"][0]["reason"] == "missing_moment"
    result = await synthesis_manage(fixture([record(origin="canonical_corpus", basis="inferred", method="caller_method")]))
    evidence = result["statements"][0]["evidence"]
    assert evidence["origin"] == "caller_fixture" and evidence["basis"] == "inferred"
    assert evidence["method"] == "caller_method" and result["selection"]["canonical_retrieval"] is False


async def test_chapters_order_duration_and_heuristic_method():
    """C3: unsorted exact moments yield bounded ordered bins with source excerpts."""
    records = [record("late", start_seconds=8, end_seconds=9), record("early", start_seconds=1, end_seconds=2),
               record("middle", start_seconds=4, end_seconds=5), record("outside", start_seconds=9, end_seconds=11),
               record("wrong_video", video_id="w"), record("wrong_revision", source_revision="r2")]
    result = await synthesis_manage(fixture(records, "chapters", video_id="v", source_revision="r1",
                                           duration_seconds=10, max_chapters=3))
    assert result["status"] == "partial" and len(result["chapters"]) == 3
    previous = 0
    for chapter in result["chapters"]:
        assert previous <= chapter["start_seconds"] < chapter["end_seconds"] <= 10
        previous = chapter["end_seconds"]
        assert chapter["method"] == "equal_duration_bins_source_excerpt_v1"
        assert chapter["title"] == chapter["evidence"][0]["text"]
    assert [c["evidence"][0]["observation_id"] for c in result["chapters"]] == ["early", "middle", "late"]
    assert {g["reason"] for g in result["abstentions"]} == {"outside_declared_duration", "outside_requested_video_revision"}


async def test_chapters_with_no_admitted_moments_abstain():
    result = await synthesis_manage(fixture([record(start_seconds=11, end_seconds=12)], "chapters",
                                           video_id="v", source_revision="r1", duration_seconds=10))
    assert result["status"] == "abstained" and result["chapters"] == []


async def test_bug_report_separates_channels_and_caller_inference():
    """C4: preserve reported channels without turning a reference into frame proof."""
    ocr = record("ocr", kind="OCR", start_seconds=10, end_seconds=10, text="Error 42", basis="observed")
    ocr["artifact_refs"][0]["kind"] = "frame"
    records = [ocr, record("speech", start_seconds=7, end_seconds=9),
               record("click", kind="description", text="clicked valve", start_seconds=8, end_seconds=8, basis="observed"),
               record("hypothesis", kind="description", basis="inferred", text="possible valve fault", start_seconds=9, end_seconds=10),
               record("unselected", kind="description", start_seconds=8, end_seconds=8),
               record("future_speech", start_seconds=11, end_seconds=12)]
    result = await synthesis_manage(fixture(records, "bug_report", video_id="v", source_revision="r1", at_seconds=10,
                                           action_observation_ids=["click"], inferred_causes=["valve fault"] ))
    assert result["status"] == "complete"
    report = result["bug_report"]
    for channel, oid in (("ocr", "ocr"), ("frames", "ocr"), ("preceding_speech", "speech"), ("actions", "click"), ("inferred_context", "hypothesis")):
        assert [r["observation_id"] for r in report[channel]] == [oid]
    assert report["preceding_speech"][0]["basis"] == "unknown"
    assert report["inferred_causes"] == [{"text": "valve fault", "basis": "inferred", "method": "caller_supplied_unverified"}]
    assert report["frame_verification"] == "artifact_references_only_not_opened"


async def test_bug_missing_channels_and_actions_named_without_causal_success():
    result = await synthesis_manage(fixture([record("old", start_seconds=1, end_seconds=2)], "bug_report",
                                           video_id="v", source_revision="r1", at_seconds=100, lookback_seconds=1,
                                           action_observation_ids=["missing"], inferred_causes=["unproved fault"]))
    assert result["status"] == "abstained"
    assert {g.get("channel") for g in result["abstentions"] if "channel" in g} == {"ocr", "frames", "preceding_speech", "actions"}
    assert result["abstentions"][0]["observation_id"] == "missing"


@pytest.mark.parametrize("duration", [0, float("nan"), float("inf")])
async def test_invalid_duration_is_typed_error(duration):
    result = await synthesis_manage(fixture([record()], "chapters", video_id="v", source_revision="r1", duration_seconds=duration))
    assert "error" in result and "chapters" not in result


async def test_bounds_extra_fields_and_disallowed_routes_fail_closed(corpus):
    result = await synthesis_manage(fixture([record(text="valve " * 900)], max_output_bytes=1024))
    assert "error" in result and "max_output_bytes" in str(result)
    result = await synthesis_manage(fixture([record()], imaginary_option=True))
    assert "error" in result
    _, _, source = corpus
    source["request"]["graph"] = {"endpoint": "http://localhost:1", "hl_keywords": ["valve"], "ll_keywords": ["valve"]}
    result = await synthesis_manage({"action": "cross_video", "instruction": "valve", "source": source})
    assert "error" in result
    source = {"kind": "wiki", "request": {"action": "ask", "index_path": str(corpus[0]), "question": "valve", "mode": "gemini"}}
    assert "error" in await synthesis_manage({"action": "cross_video", "instruction": "valve", "source": source})


async def test_canonical_path_outside_allowed_root_refused(corpus):
    _, _, source = corpus
    source["request"]["index_path"] = "/outside-owned-root/not-created.sqlite3"
    result = await synthesis_manage({"action": "cross_video", "instruction": "valve", "source": source})
    assert "error" in result and "statements" not in result


def test_public_output_schema_contains_serialized_source_identity():
    """Wire results include computed source_id; output schema must admit that field."""
    from video_research_mcp.tools.synthesis import _SCHEMA

    assert "source_id" in _SCHEMA["$defs"]["Record"]["properties"]
