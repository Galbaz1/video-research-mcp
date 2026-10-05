"""Persistent AV memory of people, dialogue, facts and audio-visual evidence.

Workflow parity with QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f skill
``qwen-mm-plugins-omni-memory`` (``skill/SKILL.md``) and its tools ``get_memory_status``,
``get_memory_overview``, ``get_people``, ``get_person_dialogue``, ``get_timeline``,
``get_moment``, ``search_memory``, ``search_dialogue``, ``search_facts`` and
``plan_and_search``, Apache-2.0. Changed: one discriminated tool over typed revisions;
``replay_and_answer``/``watch_and_answer`` are not reproduced because they return model
answers, so ``moment`` exports exact-source clips and answering stays with the caller.
"""

from datetime import datetime, timezone
import hashlib
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import Field

from ..errors import make_tool_error
from ..media_clip_export import export_selected_clip
from ..media_identity import identify_source
from ..models.scene_assets import ClipSelectionRequest
from ..models.video_memory_av import (
    WINDOW_SECONDS, ArtifactReceipt, BuildRequest, Fact, FactInput, MemoryState, SourceInfo,
    VideoMemoryRequest,
)
from ..tracing import trace
from ..video_memory import av_build, av_store, retrieval

video_memory_av_server = FastMCP("video-memory-av")
_MUTATIONS = {"add_facts", "align", "index"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _counts(state: MemoryState) -> dict:
    counts: dict[str, int] = {}
    for record in state.records:
        counts[record.kind] = counts.get(record.kind, 0) + 1
    return counts


def _receipt(kind: str, role: str, result, data: bytes, origin: str) -> ArtifactReceipt:
    digest = hashlib.sha256(data).hexdigest()
    return ArtifactReceipt(kind=kind, role=role, operation=result.operation, sha256=digest, bytes=len(data),
                           retained=f"artifacts/{digest}.json", origin=origin)


def _admit_supplied(request: BuildRequest, source: dict) -> tuple[list, dict, list]:
    admitted, retained, clocks = [], {}, []
    if sum(1 for ref in request.artifacts if ref.kind == "transcript") > 1:
        raise ValueError("One transcript per memory: speaker labels are not comparable across runs")
    for ref in request.artifacts:
        if ref.sha256 in retained:
            raise ValueError("The same artifact bytes were supplied twice")
        data, value = av_build.read_artifact(ref)
        retained[ref.sha256] = data
        if sum(map(len, retained.values())) > av_build.MAX_TOTAL_BYTES:
            raise ValueError("Supplied artifacts exceed 32 MiB in total")
        clock, result = av_build.admit(ref.kind, value, source)
        role = "utterances" if ref.kind == "transcript" else ref.role
        admitted.append((_receipt(ref.kind, role, result, data, "supplied"), result))
        clocks.append(clock)
    return admitted, retained, clocks


async def _route(request: BuildRequest, path: str, source: dict, admitted, retained, clocks) -> list:
    calls = av_build.route_calls(request.av_route, av_build.agreed_clock(clocks))
    responses = await av_build.run_route(request.av_route, path, source["sha256"], calls)
    costs = av_build.route_costs(responses)
    try:
        for role, value in responses:
            data = av_store.canonical(value)
            clock, result = av_build.admit("av_events", value, source)
            admitted.append((_receipt("av_events", role, result, data, "route"), result))
            retained[hashlib.sha256(data).hexdigest()] = data
            clocks.append(clock)
    except Exception as exc:
        raise av_build.ProviderFailure(f"AV route response was not admitted: {exc}",
                                       {"costs": {"route_calls": costs}}) from exc
    return costs


async def _build(request: BuildRequest) -> dict:
    root, sha = av_store.local_path(request.memory_dir), request.expected_source_sha256
    if av_store.load(root, sha) is not None:
        raise ValueError("A memory already exists in memory_dir; build into a new memory_dir")
    identity = identify_source(request.file_path, sha, persist=False)
    if identity.state != "fresh" or identity.digest != sha:
        raise ValueError("Source bytes differ from expected_source_sha256")
    path = av_store.local_path(request.file_path)
    source = {"sha256": sha, "bytes": path.stat().st_size}
    admitted, retained, clocks = _admit_supplied(request, source)
    costs = {"route_calls": [], "endpoint_calls": []}
    if request.av_route and not request.av_route.authorize_submission:
        return {"status": "planned", "action": "build", "written": False, "costs": costs,
                "planned_calls": av_build.route_calls(request.av_route, av_build.agreed_clock(clocks)),
                "admitted_artifacts": [r.model_dump(mode="json") for r, _ in admitted]}
    if request.av_route:
        costs["route_calls"] = await _route(request, str(path), source, admitted, retained, clocks)
    try:
        duration = av_build.agreed_clock(clocks)
        records, persons = av_build.fold(sha, duration, admitted)
        state = MemoryState(
            memory_id="avm:" + sha, revision=1, windows=av_build.window_count(duration),
            source=SourceInfo(sha256=sha, bytes=source["bytes"], path=str(path), duration_seconds=duration),
            artifacts=[r for r, _ in admitted], records=records, persons=persons,
            suggestions=av_build.suggest_names(records),
            history=[{"revision": 1, "action": "build", "at": _now(), "costs": costs}])
        stored = av_store.commit(root, state, retained)
    except Exception as exc:
        if costs["route_calls"]:
            raise av_build.ProviderFailure(str(exc), {"costs": costs}) from exc
        raise
    return {"status": "complete", "action": "build", "written": True, "memory_id": state.memory_id,
            "store": stored, "windows": state.windows, "counts": _counts(state),
            "persons": [p.model_dump(mode="json") for p in persons], "suggestions": len(state.suggestions),
            "artifacts": [r.model_dump(mode="json") for r in state.artifacts], "costs": costs}


def _next(state: MemoryState, request) -> MemoryState:
    if state.revision != request.expected_revision:
        raise ValueError(f"Memory revision conflict: current {state.revision}, "
                         f"expected {request.expected_revision}")
    following = state.model_copy(deep=True)
    following.revision += 1
    following.history.append({"revision": following.revision, "action": request.action, "at": _now()})
    return following


def _supplied_fact(state: MemoryState, item: FactInput) -> Fact:
    missing = set(item.evidence_ids) - {r.record_id for r in state.records}
    if missing:
        raise ValueError(f"Fact evidence is not stored: {sorted(missing)}")
    if item.subject_id.startswith("P") and item.subject_id not in {p.person_id for p in state.persons}:
        raise ValueError(f"Unknown fact subject {item.subject_id}")
    return Fact(fact_id=av_store.fact_id(item.subject_id, item.key, item.value), **item.model_dump(),
                basis="asserted", created_revision=state.revision, updated_revision=state.revision)


async def _facts(request, state: MemoryState) -> tuple[list, list, list, dict] | dict:
    if request.mode == "supplied":
        return [_supplied_fact(state, item) for item in request.facts], [], [], {}
    batches = av_build.induction_batches(state, request.induce.max_prompt_chars)
    plan = {"operation": "GeminiClient.generate_structured", "purpose": "fact_induction",
            "calls": len(batches), "prompt_chars": [len(p) for p, _ in batches], "model": request.induce.model}
    if not batches or len(batches) > request.induce.max_batches:
        raise ValueError(f"Induction needs {len(batches)} batches; induce.max_batches is "
                         f"{request.induce.max_batches} and at least one record is required")
    if not request.induce.authorize_provider_calls:
        return {"status": "planned", "action": "add_facts", "written": False, "planned_calls": [plan],
                "costs": {"endpoint_calls": []}}
    outputs, report = await av_build.induce(request.induce, batches)
    model = next((c["model"] for c in report["calls"] if c["kind"] == "generate_content"), None)
    facts, suggestions, rejected = av_build.admit_induced(state, outputs, state.revision, model)
    return facts, suggestions, rejected, {"induction": report}


def _merge_suggestions(state: MemoryState, suggestions: list) -> None:
    known = {s.suggestion_id: s for s in state.suggestions}
    for item in suggestions:
        if item.suggestion_id in known:
            existing = known[item.suggestion_id]
            existing.evidence_ids = sorted(set(existing.evidence_ids) | set(item.evidence_ids))[:32]
        else:
            state.suggestions.append(item)
            known[item.suggestion_id] = item


async def _mutate(request, root, state: MemoryState) -> dict:
    following, extra, costs = _next(state, request), {}, {}
    if request.action == "align":
        extra["identity_revision"] = av_store.align(following, request, following.revision).model_dump(mode="json")
    elif request.action == "index":
        costs = retrieval.new_costs()
        added = await retrieval.index_memory(following, request.embedding, costs)
        if not added:
            return {"status": "planned" if added is None else "unchanged", "action": "index",
                    "written": False, "embedded": added, "costs": costs}
        extra["embedded"] = added
    else:
        outcome = await _facts(request, following)
        if isinstance(outcome, dict):
            return outcome
        facts, suggestions, rejected, costs = outcome
        extra["operations"] = [av_store.merge_fact(following.facts, f, following.revision) for f in facts]
        extra["rejected"] = rejected
        _merge_suggestions(following, suggestions)
    following.history[-1]["costs"] = costs
    try:
        stored = av_store.commit(root, following, {})
    except Exception as exc:
        raise av_build.ProviderFailure(str(exc), {"costs": costs}) from exc
    return {"status": "complete", "action": request.action, "written": True, "store": stored,
            "costs": costs} | extra


def _gaps(covered: list[int], windows: int) -> dict:
    """Inclusive missing-window ranges sized by stored records, never by the source length."""
    ranges, start = [], 0
    for window in [*covered, windows]:
        if window > start:
            ranges.append([start, window - 1])
        start = window + 1
    return {"count": sum(end - begin + 1 for begin, end in ranges), "ranges": ranges}


def _status(state: MemoryState | None) -> dict:
    if state is None:
        return {"exists": False, "next_step": "build"}
    coverage: dict[int, set] = {}
    for record in state.records:
        coverage.setdefault(record.window, set()).add(record.kind)
    return {"exists": True, "atomic_revision": True, "memory_id": state.memory_id, "revision": state.revision,
            "source": state.source.model_dump(mode="json"), "windows": state.windows, "counts": _counts(state),
            "coverage": {str(w): sorted(k) for w, k in sorted(coverage.items())},
            "windows_without_records": _gaps(sorted(w for w in coverage if w < state.windows), state.windows),
            "people": len(state.persons), "named_people": sum(1 for p in state.persons if p.name),
            "active_facts": sum(1 for f in state.facts if f.status == "active"),
            "vectors": len(state.embeddings.vectors) if state.embeddings else 0}


def _overview(state: MemoryState) -> dict:
    people = [p.model_dump(mode="json") | {"also_heard_as": sorted(
        {s.name for s in state.suggestions if s.person_id == p.person_id} - {p.name})} for p in state.persons]
    index = state.embeddings
    return {"memory_id": state.memory_id, "revision": state.revision, "windows": state.windows,
            "people": people, "counts": _counts(state),
            "fact_key_directory": sorted({f"{f.subject_id}/{f.key}" for f in state.facts if f.status == "active"}),
            "environment_available": any(r.kind == "environment" for r in state.records),
            "dense_index": index.model_dump(mode="json", exclude={"vectors"}) | {"vectors": len(index.vectors)}
            if index else None}


def _people(state: MemoryState, person_id: str | None) -> dict:
    chosen = [p for p in state.persons if person_id in (None, p.person_id)]
    dossiers = []
    for person in chosen:
        spoken = [r for r in state.records if r.person_id == person.person_id]
        dossiers.append(person.model_dump(mode="json") | {
            "identity_revisions": [r.model_dump(mode="json") for r in state.identity_revisions
                                   if r.person_id == person.person_id],
            "suggestions": [s.model_dump(mode="json") for s in state.suggestions if s.person_id == person.person_id],
            "facts": [f.model_dump(mode="json") for f in state.facts if f.subject_id == person.person_id],
            "record_ids": [r.record_id for r in spoken], "windows": sorted({r.window for r in spoken})})
    return {"status": "found" if dossiers else "not_found", "people": dossiers}


def _span(state: MemoryState, request, kinds: set[str]) -> dict:
    end = state.source.duration_seconds if request.end_seconds is None else request.end_seconds
    chosen = sorted((r for r in state.records if r.kind in kinds and r.end_seconds >= request.start_seconds
                     and r.start_seconds <= end and getattr(request, "person_id", None) in (None, r.person_id)),
                    key=lambda r: (r.start_seconds, r.record_id))
    return {"status": "found" if chosen else "not_found", "total": len(chosen),
            "records": [retrieval.record_view(state, r) for r in chosen[: request.limit]]}


async def _moment(state: MemoryState, request) -> dict:
    if max(request.windows) >= state.windows:
        raise ValueError(f"Window index out of range; memory has {state.windows} windows")
    moments = []
    for window in dict.fromkeys(request.windows):
        start, end = window * WINDOW_SECONDS, min((window + 1) * WINDOW_SECONDS, state.source.duration_seconds)
        moment = {"window": window, "start_seconds": start, "end_seconds": end, "records": [
            retrieval.record_view(state, r) for r in state.records if r.window == window]}
        if request.export_clip:
            try:
                moment["clip"] = await export_selected_clip(ClipSelectionRequest(
                    file_path=request.file_path, expected_source_sha256=state.source.sha256,
                    start_seconds=start, end_seconds=end))
            except Exception as exc:
                moment["clip"] = {"status": "failed", "error": make_tool_error(exc)}
        moments.append(moment)
    return {"status": "found", "moments": moments}


async def _read(request, state: MemoryState, costs: dict) -> dict:
    if request.action == "overview":
        return _overview(state)
    if request.action == "people":
        return _people(state, request.person_id)
    if request.action == "person_dialogue":
        return _span(state, request, {"utterance"})
    if request.action == "timeline":
        return _span(state, request, set(request.kinds) or {r.kind for r in state.records})
    if request.action == "moment":
        return await _moment(state, request)
    if request.action == "search":
        return await retrieval.search(state, request, costs)
    return await retrieval.run_plan(state, request, costs)


async def run_action(request) -> dict:
    """Dispatch one validated request; reads never write and writes publish one revision."""
    if request.action == "build":
        return await _build(request)
    root = av_store.local_path(request.memory_dir)
    state = av_store.load(root, request.expected_source_sha256)
    if request.action == "status":
        return _status(state) | {"costs": retrieval.new_costs()}
    if state is None:
        raise ValueError("No memory exists in memory_dir; run action=build first")
    if request.action in _MUTATIONS:
        return await _mutate(request, root, state)
    costs = retrieval.new_costs()
    view = await _read(request, state, costs)
    return {"memory_id": state.memory_id, "revision": state.revision, "action": request.action} | view | {
        "costs": costs}


@video_memory_av_server.tool(annotations=ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True))
@trace(name="video_memory_av", span_type="TOOL")
async def video_memory_av(request: Annotated[VideoMemoryRequest, Field(
    description="One action: build, add_facts, align, index, status, overview, people, person_dialogue, "
                "timeline, moment, search or plan; provider calls require explicit authorization")]) -> dict:
    """Build and query a persistent AV memory that returns evidence, never answers.

    Start with ``status``; ``build`` folds exact-SHA transcript and AV-event results (and,
    when authorized, per-window ``media_caption_events`` calls) into canonical 30 s records,
    anonymous people and retained artifacts. Read ``overview`` before one explicit ``plan``,
    or use ``people``, ``person_dialogue``, ``timeline``, ``moment`` and ``search`` directly.
    Names stay unknown until ``align`` cites stored evidence; suggestions never bind.

    Args:
        request: Discriminated action request bound to a memory directory and source digest.

    Returns:
        Evidence records with retrieval mode and actual endpoint costs, or a tool error.
    """
    try:
        return await run_action(request)
    except Exception as exc:
        return make_tool_error(exc) | getattr(exc, "report", {})
