"""Local extractive synthesis with exact provenance and explicit evidence gaps."""

import re

from .corpus_index import canonical
from .evidence_export_records import select
from .models.synthesis import BugEvidence, Cause, Chapter, Response, Statement


def eligible(records) -> tuple[list, list]:
    """Require source moments and reject known missing, changed or refused records."""
    usable, issues = [], []
    refused = {"missing", "refused", "missing_observation", "observation_changed"}
    for record in records:
        reason = None
        if record.start_seconds is None:
            reason = "missing_moment"
        elif record.source_state in refused:
            reason = "source_unavailable"
        if reason:
            issues.append({"citation_id": record.citation_id, "source_id": record.source_id, "reason": reason})
        else:
            usable.append(record)
    return usable, issues


async def retrieve(request) -> tuple[list, dict]:
    """Use the instruction as the actual canonical query; never enable graph/models."""
    source = request.source
    if source.kind in {"corpus", "wiki"}:
        field = "query" if source.kind == "corpus" else "question"
        source = source.model_copy(update={"request": source.request.model_copy(update={field: request.instruction})})
    records, selection = await select(source)
    if len(records) > 50:
        raise ValueError("Synthesis exceeds 50 records; reduce canonical selection")
    if len(canonical([r.model_dump(mode="json") for r in records]).encode()) > request.max_output_bytes:
        raise ValueError("Selected evidence exceeds max_output_bytes")
    return records, selection


def cross_video(records, instruction) -> tuple[dict, list]:
    """Quote complete matched observations; retain opposing accounts without merging."""
    terms = set(re.findall(r"\w+", instruction.casefold()))
    statements, gaps = [], []
    for record in records:
        if not record.text:
            continue
        if record.stance != "conflicting" and not terms.intersection(re.findall(r"\w+", record.text.casefold())):
            continue
        statements.append(Statement(text=record.text, evidence=record))
    if not statements:
        gaps.append({"reason": "no_retrieved_statement_for_instruction"})
    return {"statements": statements}, gaps


def video_records(records, request) -> tuple[list, list]:
    """Select one exact video revision and sort by actual source endpoints."""
    selected, gaps = [], []
    for record in records:
        if (record.video_id, record.source_revision) != (request.video_id, request.source_revision):
            gaps.append({"citation_id": record.citation_id, "reason": "outside_requested_video_revision"})
        else:
            selected.append(record)
    selected.sort(key=lambda r: (r.start_seconds, r.end_seconds, r.citation_id))
    return selected, gaps


def chapters(records, request) -> tuple[dict, list]:
    """Group observations into labeled heuristic bins without fabricating word timing."""
    groups, gaps = {}, []
    for record in records:
        if record.end_seconds > request.duration_seconds or record.start_seconds >= request.duration_seconds:
            gaps.append({"citation_id": record.citation_id, "reason": "outside_declared_duration"})
            continue
        number = min(int(record.start_seconds / request.duration_seconds * request.max_chapters), request.max_chapters - 1)
        groups.setdefault(number, []).append(record)
    width = request.duration_seconds / request.max_chapters
    result = [Chapter(start_seconds=n * width, end_seconds=min((n + 1) * width, request.duration_seconds),
                      title=items[0].text[:120] or "Untitled source interval", evidence=items)
              for n, items in sorted(groups.items())]
    if not result:
        gaps.append({"reason": "no_timed_evidence_in_declared_duration"})
    return {"chapters": result}, gaps


def bug_report(records, request) -> tuple[dict, list]:
    """Separate source channels and explicit action selection from inferred causes."""
    report = BugEvidence(inferred_causes=[Cause(text=text) for text in request.inferred_causes])
    floor, gaps = max(0, request.at_seconds - request.lookback_seconds), []
    for record in records:
        if record.end_seconds < floor or record.start_seconds > request.at_seconds:
            continue
        if record.basis == "inferred":
            report.inferred_context.append(record)
            continue
        at_moment = record.start_seconds <= request.at_seconds <= record.end_seconds
        if at_moment and record.kind == "OCR":
            report.ocr.append(record)
        if at_moment and any(ref.kind == "frame" for ref in record.artifact_refs):
            report.frames.append(record)
        if record.kind == "speech" and record.end_seconds <= request.at_seconds:
            report.preceding_speech.append(record)
        if record.kind in {"description", "action"} and record.observation_id in request.action_observation_ids:
            report.actions.append(record)
    retained_actions = {r.observation_id for r in report.actions}
    gaps.extend({"observation_id": oid, "reason": "requested_action_not_in_reported_context"}
                for oid in request.action_observation_ids if oid not in retained_actions)
    gaps.extend({"channel": channel, "reason": "no_reported_evidence_in_selected_context"}
                for channel in ("ocr", "frames", "preceding_speech", "actions") if not getattr(report, channel))
    return {"bug_report": report}, gaps


async def synthesize(request) -> dict:
    """Build one bounded result over actual canonical retrieval or labeled fixtures."""
    records, selection = await retrieve(request)
    records, gaps = eligible(records)
    if request.action == "cross_video":
        result, missing = cross_video(records, request.instruction)
        present = bool(result["statements"])
    else:
        records, outside = video_records(records, request)
        gaps.extend(outside)
        if request.action == "chapters":
            result, missing = chapters(records, request)
            present = bool(result["chapters"])
        else:
            result, missing = bug_report(records, request)
            report = result["bug_report"]
            present = any((report.ocr, report.frames, report.preceding_speech, report.actions))
    gaps.extend(missing)
    response = Response(action=request.action, status="partial" if present and gaps else "complete" if present else "abstained",
                        instruction=request.instruction, selection=selection, abstentions=gaps, **result)
    value = response.model_dump(mode="json")
    if len(canonical(value).encode()) > request.max_output_bytes:
        raise ValueError("Synthesis result exceeds max_output_bytes")
    return value
