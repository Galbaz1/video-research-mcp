"""Tests for the evidence-only AV memory: fold, identity, facts, retrieval and costs."""

import hashlib
import json
import math
from pathlib import Path
import random
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pydantic import TypeAdapter
import pytest

from video_research_mcp.client import GeminiClient
from video_research_mcp.models.video_memory_av import (
    InducedFact, InducedFacts, InducedName, VideoMemoryRequest,
)
from video_research_mcp.tools import video_memory_av as tool
from video_research_mcp.video_memory import av_build, av_store

REQUEST = TypeAdapter(VideoMemoryRequest)
SEGMENTS = [
    ("seg-1", 1.0, 4.0, "SPEAKER_00", "Hi everyone, I'm Alice and I run the studio."),
    ("seg-2", 5.0, 8.0, "SPEAKER_00", "Thanks Bob, can you bring the umbrella tomorrow?"),
    ("seg-3", 9.0, 12.0, "SPEAKER_01", "Sure, I will bring the umbrella to the studio."),
    ("seg-4", 35.0, 40.0, "SPEAKER_01", "The budget meeting moves to Friday afternoon."),
    ("seg-5", 62.0, 70.0, "SPEAKER_00", "We agreed to ship the prototype next week."),
]
EVENTS = [
    (0, 2.0, 6.0, "visual", "A person holds a red umbrella near the door."),
    (1, 31.0, 33.0, "audio", "Rain patters against the window."),
    (1, 50.0, 55.0, "both", "A laptop chime plays as the slide changes."),
]
SETTING = [
    (0, 0.0, 30.0, "visual", "Bright studio room with a long wooden table and a whiteboard."),
    (2, 60.0, 75.0, "visual", "Same studio, evening light through tall windows."),
]


def _write(path, value) -> dict:
    data = json.dumps(value).encode()
    path.write_bytes(data)
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest()}


def _events(src, rows, **changes) -> dict:
    records = [{"record_id": "av_" + hashlib.sha256(text.encode()).hexdigest(), "source_sha256": src["sha256"],
                "window_index": window, "start_seconds": start, "end_seconds": end,
                "local_start_seconds": start, "local_end_seconds": end, "basis": basis,
                "description": text, "frame_indices": [] if basis == "audio" else [0],
                "visual_support": [], "audio_support": None} for window, start, end, basis, text in rows]
    return {"operation": "media_caption_events", "task": "caption", "status": "complete",
            "outcome": "events", "source": src["clock"], "backend": {}, "request_sha256": "a" * 64,
            "windows": [], "records": records, "matches": [], "grounding_population": None, "count": None,
            "count_so_far": None, "target": None, "query": None, "summaries": [], "abstentions": [],
            "execution": {"provider_calls": 2}, "provenance": {}} | changes


def _transcript(src, segments=SEGMENTS, **changes) -> dict:
    rows = [{"id": i, "start_seconds": a, "end_seconds": b, "speaker_id": who, "text": text}
            for i, a, b, who, text in segments]
    return {"operation": "audio_transcribe", "status": "complete", "outcome": "inferred",
            "source": src["clock"], "request_sha256": "b" * 64,
            "selection": {"start_seconds": 0.0, "end_seconds": 75.0}, "captions": [], "segments": rows,
            "untimed_text": [], "windows": [], "attempts": [], "exports": [], "artifacts": [],
            "provenance": {}, "warnings": [], "execution": {}} | changes


@pytest.fixture
def src(tmp_path) -> dict:
    """GIVEN a 75 s source identity whose artifacts share one presentation clock."""
    path = tmp_path / "talk.mp4"
    path.write_bytes(b"not-really-video" * 64)
    data = path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    clock = {"path": str(path), "sha256": sha, "bytes": len(data), "presentation_end_seconds": 75.0}
    return {"path": str(path), "sha256": sha, "clock": clock, "tmp": tmp_path}


def _artifacts(src) -> list[dict]:
    tmp = src["tmp"]
    return [_write(tmp / "transcript.json", _transcript(src)) | {"kind": "transcript"},
            _write(tmp / "events.json", _events(src, EVENTS)) | {"kind": "av_events"},
            _write(tmp / "setting.json", _events(src, SETTING)) | {"kind": "av_events", "role": "environment"}]


async def run(src, action: str, memory: str = "memory", **fields) -> dict:
    payload = {"action": action, "memory_dir": str(src["tmp"] / memory),
               "expected_source_sha256": src["sha256"]} | fields
    return await tool.video_memory_av(REQUEST.validate_python(payload))


async def build(src, memory: str = "memory", **fields) -> dict:
    return await run(src, "build", memory, file_path=src["path"], artifacts=_artifacts(src), **fields)


def _ids(result: dict) -> list[str]:
    return [r["record_id"] for r in result["records"]]


async def _record(src, fragment: str) -> str:
    return next(r["record_id"] for r in (await run(src, "timeline"))["records"] if fragment in r["text"])


def _vector(text: str) -> list[float]:
    buckets = [1.0 / 3.0] * 8
    for word in text.lower().replace(",", " ").replace(".", " ").split():
        buckets[hashlib.sha256(word.encode()).digest()[0] % 8] += 1.0
    return buckets


@pytest.fixture
def embedder(monkeypatch):
    """GIVEN a patched google-genai client seam whose embed_content call is recorded."""
    calls: list[list[str]] = []
    state = {"fail": False, "values": None}

    async def embed_content(*, model, contents, config=None):
        texts = [c.parts[0].text for c in contents]
        calls.append(texts)
        if state["fail"]:
            raise RuntimeError("endpoint down")
        rows = [SimpleNamespace(values=_vector(t) if state["values"] is None else state["values"],
                                statistics=SimpleNamespace(token_count=float(len(t)))) for t in texts]
        return SimpleNamespace(embeddings=rows, metadata=SimpleNamespace(billable_character_count=7))

    client = SimpleNamespace(aio=SimpleNamespace(models=SimpleNamespace(embed_content=embed_content)))
    monkeypatch.setattr(GeminiClient, "get", classmethod(lambda cls, api_key=None: client))
    return SimpleNamespace(calls=calls, state=state)


EMBED = {"model": "gemini-embedding-001", "authorize_provider_calls": True}


async def test_build_fixture_records(src):
    """GIVEN exact-SHA transcript and AV results WHEN built THEN all record kinds, people,
    spans, retained artifacts and identical canonical IDs on rebuild."""
    first = await build(src)
    assert first["status"] == "complete" and first["store"]["revision"] == 1
    assert first["windows"] == 3
    assert first["counts"] == {"utterance": 5, "visual": 1, "acoustic": 1, "audiovisual": 1, "environment": 2}
    assert [(p["person_id"], p["name"], p["identity_status"]) for p in first["persons"]] == [
        ("P001", None, "unknown"), ("P002", None, "unknown")]
    for artifact in first["artifacts"]:
        retained = src["tmp"] / "memory" / artifact["retained"]
        assert hashlib.sha256(retained.read_bytes()).hexdigest() == artifact["sha256"]
    timeline = await run(src, "timeline")
    record = next(r for r in timeline["records"] if r["kind"] == "acoustic")
    assert record["record_id"] == f"acoustic:{src['sha256'][:12]}:0001:001"
    assert (record["start_seconds"], record["end_seconds"], record["window"]) == (31.0, 33.0, 1)
    assert record["basis"] == "inferred" and record["origin"]["operation"] == "media_caption_events"
    assert {r["kind"] for r in timeline["records"] if r["basis"] == "inferred"} >= {"visual", "environment"}
    await build(src, memory="rebuilt")
    assert _ids(await run(src, "timeline", "rebuilt")) == _ids(timeline)
    added = await run(src, "add_facts", expected_revision=1, mode="supplied", facts=[
        {"subject_id": "P002", "key": "brings", "value": "umbrella", "confidence": "high",
         "evidence_ids": [_ids(timeline)[2]]}])
    assert added["operations"] == ["create"] and added["store"]["revision"] == 2
    overview = await run(src, "overview")
    assert overview["fact_key_directory"] == ["P002/brings"] and overview["environment_available"]


@pytest.mark.parametrize("mutate,message", [
    (lambda src, a: a[0].update(sha256="0" * 64), "expected SHA-256"),
    (lambda src, a: a.__setitem__(0, _write(src["tmp"] / "t2.json", _transcript(
        src, source=src["clock"] | {"sha256": "c" * 64})) | {"kind": "transcript"}), "source identity"),
    (lambda src, a: a.__setitem__(1, _write(src["tmp"] / "e2.json", _events(
        src, EVENTS, source=src["clock"] | {"presentation_end_seconds": 80.0})) | {"kind": "av_events"}),
     "presentation clock"),
    (lambda src, a: a.__setitem__(1, _write(src["tmp"] / "e3.json", _events(
        src, [(2, 70.0, 79.0, "audio", "Late noise")])) | {"kind": "av_events"}), "outside the source"),
    (lambda src, a: a.__setitem__(1, _write(src["tmp"] / "e4.json", _events(
        src, EVENTS, status="planned")) | {"kind": "av_events"}), "must be complete"),
    (lambda src, a: a.__setitem__(1, _write(src["tmp"] / "e5.json", ["not", "object"]) | {"kind": "av_events"}),
     "must be an object"),
])
async def test_build_rejects_unbound_artifacts(src, mutate, message):
    """GIVEN a wrong digest, source, clock, span, status or JSON type WHEN built THEN no revision."""
    artifacts = _artifacts(src)
    mutate(src, artifacts)
    result = await run(src, "build", file_path=src["path"], artifacts=artifacts)
    assert message in result["error"]
    assert not list((src["tmp"]).glob("memory/rev-*.json"))


async def test_build_rejects_nan_and_existing_memory(src):
    """GIVEN a nonfinite JSON constant or an existing memory WHEN built THEN tool errors."""
    path = src["tmp"] / "nan.json"
    path.write_bytes(json.dumps(_transcript(src)).replace("75.0", "NaN", 1).encode())
    bad = {"kind": "transcript", "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    assert "nonfinite" in (await run(src, "build", file_path=src["path"], artifacts=[bad]))["error"]
    twice = [_artifacts(src)[0], _write(src["tmp"] / "t9.json", _transcript(src, SEGMENTS[:1])) | {
        "kind": "transcript"}]
    assert "One transcript" in (await run(src, "build", file_path=src["path"], artifacts=twice))["error"]
    await build(src)
    assert "already exists" in (await build(src))["error"]


async def test_people_dialogue_timeline_and_moment(src, monkeypatch):
    """GIVEN a built memory WHEN direct views are read THEN they return stored records only."""
    await build(src)
    people = await run(src, "people", person_id="P001")
    assert people["people"][0]["windows"] == [0, 2] and people["people"][0]["name"] is None
    dialogue = await run(src, "person_dialogue", person_id="P002")
    assert dialogue["total"] == 2 and [r["person_id"] for r in dialogue["records"]] == ["P002", "P002"]
    assert (await run(src, "person_dialogue", start_seconds=60.0))["total"] == 1
    timeline = await run(src, "timeline", start_seconds=30.0, end_seconds=45.0, kinds=["utterance", "acoustic"])
    assert [r["kind"] for r in timeline["records"]] == ["acoustic", "utterance"]
    exported = AsyncMock(return_value={"path": "clip.mp4", "sha256": "d" * 64})
    monkeypatch.setattr(tool, "export_selected_clip", exported)
    moment = await run(src, "moment", windows=[2], export_clip=True, file_path=src["path"])
    clip_request = exported.await_args.args[0]
    assert (clip_request.start_seconds, clip_request.end_seconds) == (60.0, 75.0)
    assert clip_request.expected_source_sha256 == src["sha256"]
    assert moment["moments"][0]["clip"]["sha256"] == "d" * 64
    assert {r["kind"] for r in moment["moments"][0]["records"]} == {"utterance", "environment"}
    assert "out of range" in (await run(src, "moment", windows=[3]))["error"]


async def test_keyword_search_scopes_without_fallback(src):
    """GIVEN no embedding options WHEN searching THEN keyword-only evidence and no fallback."""
    await build(src)
    memory = await run(src, "search", query="red umbrella door")
    assert memory["results"][0]["kind"] == "visual" and memory["costs"]["endpoint_calls"] == []
    assert memory["retrieval"] == {"mode": "keyword_only", "dense_unavailable_reason": "no_embedding_model"}
    dialogue = await run(src, "search", scope="dialogue", query="umbrella")
    assert {r["kind"] for r in dialogue["results"]} == {"utterance"} and len(dialogue["results"]) == 2
    missing = await run(src, "search", query="volcano eruption")
    assert missing["status"] == "not_found" and missing["results"] == [] and "answer" not in missing


async def test_fact_search_supersession_and_filters(src):
    """GIVEN conflicting supplied facts WHEN merged THEN the loser stays superseded and searchable."""
    await build(src)
    ids = _ids(await run(src, "timeline"))
    facts = [{"subject_id": "P001", "key": "role", "value": "studio owner", "confidence": "medium",
              "evidence_ids": [ids[0]]},
             {"subject_id": "P001", "key": "role", "value": "intern", "confidence": "high", "evidence_ids": [ids[1]]},
             {"subject_id": "event:launch", "key": "date", "value": "next week", "confidence": "low",
              "evidence_ids": [ids[-1]]}]
    added = await run(src, "add_facts", expected_revision=1, mode="supplied", facts=facts)
    assert added["operations"] == ["create", "conflict", "create"]
    active = await run(src, "search", scope="facts", subject_id="P001")
    assert [f["value"] for f in active["results"]] == ["intern"]
    every = await run(src, "search", scope="facts", key_prefix="P001/", include_superseded=True)
    loser = next(f for f in every["results"] if f["value"] == "studio owner")
    assert loser["status"] == "superseded" and loser["superseded_by"].startswith("F:")
    found = await run(src, "search", scope="facts", query="launch next week")
    assert found["results"][0]["subject_id"] == "event:launch"
    unknown = await run(src, "add_facts", expected_revision=2, mode="supplied", facts=[facts[0] | {
        "evidence_ids": [f"utterance:{'f' * 12}:0000:001"]}])
    assert "not stored" in unknown["error"]


async def test_dense_hybrid_search(src, embedder):
    """GIVEN authorized indexing WHEN a dense query runs THEN hybrid ranks and one query call."""
    await build(src)
    indexed = await run(src, "index", expected_revision=1, embedding=EMBED)
    assert indexed["embedded"] == 10 and len(indexed["costs"]["endpoint_calls"]) == 1
    unchanged = await run(src, "index", expected_revision=2, embedding=EMBED)
    assert (unchanged["status"], unchanged["written"], unchanged["costs"]["endpoint_calls"]) == (
        "unchanged", False, [])
    result = await run(src, "search", query="umbrella", embedding=EMBED)
    assert result["retrieval"] == {"mode": "hybrid", "dense_unavailable_reason": None}
    assert all(r["rank"]["dense_rank"] is not None for r in result["results"])
    calls = result["costs"]["endpoint_calls"]
    assert [(c["purpose"], c["input_count"], c["status"]) for c in calls] == [("query", 1, "completed")]
    assert calls[0]["usage"] == {"billable_character_count": 7, "token_counts": [8.0]}


async def test_plan_not_found_has_no_answer(src, monkeypatch):
    """GIVEN missing people, keys, text and times WHEN planned THEN not_found steps, no answer."""
    await build(src)
    generate = AsyncMock()
    monkeypatch.setattr(GeminiClient, "generate_structured", generate)
    result = await run(src, "plan", question="Who flew the drone?", people=["P009"], fact_keys=["P001/role"],
                       queries=["drone flight"], time_ranges=[[200.0, 210.0]])
    assert [s["status"] for s in result["steps"]] == ["not_found"] * 5
    assert result["question"] == "Who flew the drone?" and result["evidence_record_ids"] == []
    assert "answer" not in json.dumps(result) and generate.await_count == 0


async def test_plan_returns_evidence_steps(src):
    """GIVEN a caller plan WHEN executed THEN each step returns its own stored evidence."""
    await build(src)
    ids = _ids(await run(src, "timeline"))
    await run(src, "add_facts", expected_revision=1, mode="supplied", facts=[
        {"subject_id": "P002", "key": "brings", "value": "umbrella", "confidence": "high", "evidence_ids": [ids[2]]}])
    result = await run(src, "plan", people=["P002"], fact_keys=["P002/brings"], queries=["umbrella studio"],
                       time_ranges=[[60.0, 75.0]], include_environment=True, top_k=3)
    assert [s["step"] for s in result["steps"]] == ["person", "fact_key", "query", "time_range", "environment"]
    assert all(s["status"] == "found" for s in result["steps"])
    assert result["steps"][-1]["match"] == "keyword" and result["suggested_windows"][0] == 0
    assert set(result["evidence_record_ids"]) <= set(ids)


def test_embedding_round_trip_bit_exact():
    """GIVEN endpoint floats including extremes WHEN encoded THEN bytes and values are identical."""
    rng = random.Random(7)
    values = [rng.uniform(-1, 1) for _ in range(64)] + [-0.0, 5e-324, 1.7976931348623157e308, 1 / 3]
    decoded = av_store.decode_vector(av_store.encode_vector(values))
    assert struct.pack("<68d", *decoded) == struct.pack("<68d", *values)
    for bad in ([], [0.0, 0.0], [math.nan], [math.inf]):
        with pytest.raises(ValueError):
            av_store.encode_vector(bad)
    with pytest.raises(ValueError):
        av_store.decode_vector("f32:AAAA")


async def test_stored_vectors_round_trip(src, embedder):
    """GIVEN an authorized index WHEN reloaded from disk THEN vectors equal endpoint values."""
    await build(src)
    await run(src, "index", expected_revision=1, embedding=EMBED)
    state = av_store.load(src["tmp"] / "memory", src["sha256"])
    record = state.records[0]
    assert av_store.decode_vector(state.embeddings.vectors[record.record_id]) == _vector(record.text)
    assert state.embeddings.endpoint == "google-genai:aio.models.embed_content"


async def test_keyword_only_reasons(src, embedder):
    """GIVEN each missing dense precondition WHEN searching THEN the exact keyword-only reason."""
    await build(src)
    no_vectors = await run(src, "search", query="umbrella", embedding=EMBED)
    assert no_vectors["retrieval"]["dense_unavailable_reason"] == "no_vectors"
    await run(src, "index", expected_revision=1, embedding=EMBED)
    cases = {"model_mismatch": EMBED | {"model": "other-model"},
             "not_authorized": EMBED | {"authorize_provider_calls": False}}
    for reason, options in cases.items():
        result = await run(src, "search", query="umbrella", embedding=options)
        assert result["retrieval"] == {"mode": "keyword_only", "dense_unavailable_reason": reason}
        assert result["results"] and result["costs"]["endpoint_calls"] == []
    embedder.state["fail"] = True
    failed = await run(src, "search", query="umbrella", embedding=EMBED)
    assert failed["retrieval"]["dense_unavailable_reason"] == "endpoint_failed:RuntimeError"
    assert [c["status"] for c in failed["costs"]["endpoint_calls"]] == ["failed:RuntimeError"]


async def test_costs_only_actual_calls(src, embedder):
    """GIVEN planned, keyword and dense requests THEN costs list only actually attempted calls."""
    await build(src)
    planned = await run(src, "index", expected_revision=1, embedding=EMBED | {"authorize_provider_calls": False})
    assert planned["status"] == "planned" and planned["costs"]["endpoint_calls"] == []
    assert planned["costs"]["planned_calls"][0]["inputs"] == 10 and embedder.calls == []
    assert (await run(src, "status"))["revision"] == 1
    await run(src, "index", expected_revision=1, embedding=EMBED)
    keyword = await run(src, "plan", queries=["umbrella"])
    dense = await run(src, "plan", queries=["umbrella", "budget"], embedding=EMBED)
    assert keyword["costs"]["endpoint_calls"] == [] and len(dense["costs"]["endpoint_calls"]) == 2
    assert len(embedder.calls) == 3
    await run(src, "add_facts", expected_revision=2, mode="supplied", facts=[
        {"subject_id": "event:launch", "key": "date", "value": "next week", "confidence": "low",
         "evidence_ids": [await _record(src, "prototype")]}])
    embedder.state["fail"] = True
    failed = await run(src, "index", expected_revision=3, embedding=EMBED)
    assert "Embedding indexing failed" in failed["error"]
    assert [c["status"] for c in failed["costs"]["endpoint_calls"]] == ["failed:RuntimeError"]
    assert (await run(src, "status"))["revision"] == 3


async def test_names_stay_unknown_with_suggestions(src, monkeypatch):
    """GIVEN self-introductions, address and model name candidates THEN names stay unknown."""
    await build(src)
    overview = await run(src, "overview")
    heard = {p["person_id"]: (p["name"], p["also_heard_as"]) for p in overview["people"]}
    assert heard == {"P001": (None, ["Alice"]), "P002": (None, ["Bob"])}
    phonetic = await run(src, "search", scope="dialogue", query="What did Alise say?")
    assert phonetic["matched_people"] == [{"person_id": "P001", "heard_as": "Alice", "via": "suggestion"}]
    alice, bob = await _record(src, "I'm Alice"), await _record(src, "Sure, I will")
    planned = await run(src, "add_facts", expected_revision=1, mode="induce")
    assert planned["status"] == "planned" and planned["planned_calls"][0]["calls"] == 1
    answer = InducedFacts(facts=[
        InducedFact(subject_id="P001", key="role", value="runs the studio", confidence="High", evidence_ids=[alice]),
        InducedFact(subject_id="P001", key="pet", value="cat", confidence="low", evidence_ids=["utterance:x"])],
        name_suggestions=[InducedName(person_id="P002", name="Robert", evidence_ids=[bob])])
    monkeypatch.setattr(GeminiClient, "generate_structured", AsyncMock(return_value=answer))
    induced = await run(src, "add_facts", expected_revision=1, mode="induce",
                        induce={"authorize_provider_calls": True})
    assert induced["operations"] == ["create"] and len(induced["rejected"]) == 1
    people = (await run(src, "people"))["people"]
    assert [p["name"] for p in people] == [None, None]
    assert {s["name"] for s in people[1]["suggestions"]} == {"Bob", "Robert"}
    assert people[0]["facts"][0]["basis"] == "inferred"


async def test_align_requires_existing_evidence(src):
    """GIVEN missing, unrelated, unnamed or stale evidence WHEN aligning THEN nothing changes."""
    await build(src)
    alice, other = await _record(src, "I'm Alice"), await _record(src, "Sure, I will")
    base = {"expected_revision": 1, "person_id": "P001", "name": "Alice", "basis": "evidence_aligned"}
    failures = {"not stored": base | {"evidence_ids": ["utterance:missing"]},
                "this person's": base | {"evidence_ids": [other]},
                "occur in the cited": base | {"name": "Carol", "evidence_ids": [alice]},
                "revision conflict": base | {"expected_revision": 5, "evidence_ids": [alice]}}
    for message, fields in failures.items():
        assert message in (await run(src, "align", **fields))["error"]
    assert (await run(src, "status"))["revision"] == 1


async def test_identity_revisions_retain_provenance(src):
    """GIVEN evidence then user alignment WHEN revised THEN history and old revisions remain."""
    await build(src)
    suggestion = (await run(src, "people", person_id="P001"))["people"][0]["suggestions"][0]
    first = await run(src, "align", expected_revision=1, person_id="P001", name="Alice",
                      basis="evidence_aligned", evidence_ids=[suggestion["suggestion_id"]])
    assert first["identity_revision"]["revision_id"] == "P001@r1"
    second = await run(src, "align", expected_revision=2, person_id="P001", name="Alicia",
                       basis="user_asserted", evidence_ids=suggestion["evidence_ids"], note="user correction")
    assert second["identity_revision"]["previous_name"] == "Alice"
    dossier = (await run(src, "people", person_id="P001"))["people"][0]
    assert (dossier["name"], dossier["identity_status"]) == ("Alicia", "user_asserted")
    assert [r["basis"] for r in dossier["identity_revisions"]] == ["evidence_aligned", "user_asserted"]
    original = av_store.MemoryState.model_validate_json((src["tmp"] / "memory/rev-000001.json").read_bytes())
    assert original.persons[0].name is None
    records = (await run(src, "person_dialogue", person_id="P001"))["records"]
    assert {r["person_name"] for r in records} == {"Alicia"} and {r["person_id"] for r in records} == {"P001"}
    await run(src, "add_facts", expected_revision=3, mode="supplied", facts=[
        {"subject_id": "P001", "key": "role", "value": "studio owner", "confidence": "high",
         "evidence_ids": suggestion["evidence_ids"]}])
    aliased = await run(src, "plan", fact_keys=["Alicia/role", "Alice/role"])
    assert [s["status"] for s in aliased["steps"]] == ["found", "not_found"]
    reset = await run(src, "align", expected_revision=4, person_id="P001", name=None,
                      basis="user_asserted", evidence_ids=[suggestion["suggestion_id"]])
    assert reset["store"]["revision"] == 5
    assert (await run(src, "people", person_id="P001"))["people"][0]["identity_status"] == "unknown"


async def test_build_route_plans_then_executes(src, monkeypatch):
    """GIVEN an AV route WHEN unauthorized THEN planned; WHEN authorized THEN per-window calls."""
    transcript = _artifacts(src)[:1]
    calls = AsyncMock(side_effect=lambda request: _events(src, EVENTS if request.instruction.startswith(
        "Describe supported") else SETTING))
    monkeypatch.setattr(av_build, "caption_events", calls)
    route = {"roles": ["occurrences", "environment"]}
    planned = await run(src, "build", file_path=src["path"], artifacts=transcript, av_route=route)
    assert planned["status"] == "planned" and len(planned["planned_calls"]) == 2 and calls.await_count == 0
    assert not (src["tmp"] / "memory").exists()
    built = await run(src, "build", file_path=src["path"], artifacts=transcript,
                      av_route=route | {"authorize_submission": True})
    sent = calls.await_args_list[0].args[0]
    assert (sent.start_seconds, sent.end_seconds, sent.window_seconds) == (0.0, 75.0, 30.0)
    assert sent.authorize_submission and not sent.dry_run
    assert built["counts"]["environment"] == 2 and len(built["costs"]["route_calls"]) == 2
    assert {a["origin"] for a in built["artifacts"]} == {"supplied", "route"}
    limited = await run(src, "build", "other", file_path=src["path"], artifacts=transcript,
                        av_route=route | {"max_calls": 1})
    assert "max_calls" in limited["error"]


async def test_route_failure_reports_costs_without_writing(src, monkeypatch):
    """GIVEN a failed route call WHEN building THEN its accounting is returned and nothing written."""
    failure = {"error": "quota", "category": "API_QUOTA_EXCEEDED", "execution": {"provider_calls": 1}}
    monkeypatch.setattr(av_build, "caption_events", AsyncMock(return_value=failure))
    result = await run(src, "build", file_path=src["path"], artifacts=_artifacts(src)[:1],
                       av_route={"authorize_submission": True})
    assert result["costs"]["route_calls"][0]["execution"] == {"provider_calls": 1}
    assert not list(src["tmp"].glob("memory/rev-*.json"))


def test_publish_never_overwrites(tmp_path):
    """GIVEN an existing revision file WHEN another writer publishes it THEN it is refused."""
    target = tmp_path / "rev-000001.json"
    assert av_store.publish(target, b"first") and not av_store.publish(target, b"second")
    assert target.read_bytes() == b"first" and not list(tmp_path.glob(".*pending"))


async def test_load_bounds_bytes_that_grow_after_stat(src, monkeypatch):
    """GIVEN a saved revision that grows after its stat WHEN loaded THEN read bytes stay bounded."""
    await build(src)
    root, sha = src["tmp"] / "memory", src["sha256"]
    path = root / "rev-000001.json"
    with pytest.raises(ValueError, match="source SHA-256"):
        av_store.load(root, "0" * 64)
    monkeypatch.setattr(av_store, "MAX_SNAPSHOT_BYTES", path.stat().st_size + 8)
    seen = []

    def grow_after(real):
        def stat(self, *args, **kwargs):
            if self == path and not seen:
                seen.append(real(self, *args, **kwargs))
                with path.open("ab") as stream:
                    stream.write(b" " * 64)
            return seen[0] if self == path else real(self, *args, **kwargs)
        return stat

    monkeypatch.setattr(Path, "stat", grow_after(Path.stat))
    monkeypatch.setattr(Path, "lstat", grow_after(Path.lstat))
    with pytest.raises(ValueError, match="exceeds"):
        av_store.load(root, sha)
    assert seen
    monkeypatch.undo()
    assert av_store.load(root, sha).revision == 1


async def test_load_refuses_symlinked_revision(src):
    """GIVEN the newest revision is a symlink to valid bytes WHEN loaded THEN it is refused."""
    await build(src)
    root = src["tmp"] / "memory"
    (root / "rev-000001.json").rename(root / "target.json")
    (root / "rev-000001.json").symlink_to(root / "target.json")
    with pytest.raises(ValueError, match="symlink"):
        av_store.load(root, src["sha256"])


async def test_status_reports_compact_missing_windows(src, monkeypatch):
    """GIVEN sparse and empty 1e12 s memories WHEN status runs THEN gaps are ranges, clock unchanged."""
    await build(src)
    state = av_store.load(src["tmp"] / "memory", src["sha256"])
    sparse = state.model_copy(update={"records": [r for r in state.records if r.window == 1]})
    monkeypatch.setattr(av_store, "load", lambda root, sha: sparse)
    assert (await run(src, "status"))["windows_without_records"] == {"count": 2, "ranges": [[0, 0], [2, 2]]}
    empty = state.model_copy(update={"records": [], "windows": av_build.window_count(1e12),
                                     "source": state.source.model_copy(update={"duration_seconds": 1e12})})
    monkeypatch.setattr(av_store, "load", lambda root, sha: empty)
    status = await run(src, "status")
    assert (status["windows"], status["source"]["duration_seconds"]) == (33333333334, 1e12)
    assert status["windows_without_records"] == {"count": 33333333334, "ranges": [[0, 33333333333]]}


async def test_index_invalid_reply_keeps_costs_and_revision(src, embedder):
    """GIVEN completed index calls whose vectors cannot be stored THEN costs survive and nothing is written."""
    await build(src)
    for values in ([0.5] * 4097, [0.0] * 8, [math.nan] * 8):
        embedder.state["values"] = values
        failed = await run(src, "index", expected_revision=1, embedding=EMBED)
        assert "not admitted" in failed["error"]
        assert [c["status"] for c in failed["costs"]["endpoint_calls"]] == ["completed"]
    assert (await run(src, "status"))["revision"] == 1 and len(embedder.calls) == 3


async def test_invalid_query_vector_stays_keyword_only(src, embedder):
    """GIVEN zero or nonfinite query vectors WHEN an unmatched query runs THEN no dense hit, costs kept."""
    await build(src)
    await run(src, "index", expected_revision=1, embedding=EMBED)
    for values in ([0.0] * 8, [math.nan] * 8, [math.inf] + [1.0] * 7):
        embedder.state["values"] = values
        result = await run(src, "search", query="volcano eruption", embedding=EMBED)
        assert (result["status"], result["results"]) == ("not_found", [])
        assert result["retrieval"] == {"mode": "keyword_only", "dense_unavailable_reason": "invalid_query_vector"}
        assert [(c["purpose"], c["status"]) for c in result["costs"]["endpoint_calls"]] == [("query", "completed")]


@pytest.mark.parametrize("action", ["timeline", "person_dialogue"])
def test_reversed_intervals_rejected(action):
    """GIVEN start 10 and end 5 WHEN validated THEN rejected like plan time ranges; equal ends are a point."""
    payload = {"action": action, "memory_dir": "m", "expected_source_sha256": "a" * 64, "start_seconds": 10.0}
    with pytest.raises(ValueError, match="must not precede"):
        REQUEST.validate_python(payload | {"end_seconds": 5.0})
    assert REQUEST.validate_python(payload | {"end_seconds": 10.0}).end_seconds == 10.0
