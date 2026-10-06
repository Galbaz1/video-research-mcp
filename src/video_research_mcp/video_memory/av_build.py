"""Deterministic AV-memory fold over admitted artifacts plus explicit optional model routes.

Adapted from QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f
``src/capabilities/omni-memory/skill/script/build_memory/pipeline.py`` (``build_memory``),
``stages.py`` (``update_state``, ``extract_clip``, ``_classify_mention``,
``ledger_accumulate``, ``stage2_rollup``) and ``qwen_mm_plugins_omni_memory/omni_core.py``
(``normalize_acoustic_events``), Apache-2.0. Changed: per-window omni extraction is the
existing source-bound ``media_caption_events`` route; utterances come from
``audio_transcribe`` results; names are only suggested, never applied; induced facts must
cite stored records; artifacts pass byte, schema, source and parent-clock admission.
"""

import hashlib
import json
import math
import re

from ..av_events import caption_events
from ..client import GeminiClient
from ..execution_budget import ExecutionBudget
from ..models.av_events import AVEventsResponse, CaptionEventsRequest
from ..models.transcript import TranscriptResult
from ..models.video_memory_av import (
    WINDOW_SECONDS, ArtifactRef, AVRoute, Fact, FactInput, InducedFact, InducedFacts, InduceOptions,
    MemoryRecord, MemoryState, Origin, Person, Suggestion,
)
from ..models.vision import VisionLimits
from .av_store import fact_id, local_path

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_RECORDS = 5000
CLOCK_TOLERANCE_SECONDS = 0.05
ROUTE_SPAN_SECONDS = 4 * WINDOW_SECONDS
ENVIRONMENT_INSTRUCTION = (
    "Describe the durable physical setting: place, layout, fixed objects and background"
    " conditions, each supported by the submitted frames or audio."
)
INDUCE_INSTRUCTION = (
    "Induce durable semantic facts and person-name candidates only from the memory records"
    " below. Cite the bracketed record IDs that support each item. Subjects are person IDs"
    " (P001) or event:/topic:/place:/object: slugs; keys are short predicate slugs. Name"
    " candidates are nonbinding suggestions; do not decide anyone's identity.\n\n"
)
_KIND = {"audio": "acoustic", "visual": "visual", "both": "audiovisual"}
_NAME = re.compile(r"\b([A-Z][a-z]{2,})\b")
_NAME_STOP = frozenset(
    "the and but yes yeah okay thanks thank hello hey well also then there this that what when"
    " where who why how not just maybe sure sorry please right good great monday tuesday"
    " wednesday thursday friday saturday sunday god".split()
)
_GREETING = r"(?:hi|hello|hey|thanks|thank you)"
_LEAD = r"(?:^|[,.!?]|\b(?:well|oh|so|okay|ok|yes|yeah|no|listen|look|sorry|please)\b)"


class ProviderFailure(ValueError):
    """A failed optional route that still reports every attempted provider call."""

    def __init__(self, message: str, report: dict):
        super().__init__(message)
        self.report = report


def _reject_constant(value):
    raise ValueError(f"Artifact JSON contains nonfinite constant {value}")


def read_artifact(ref: ArtifactRef) -> tuple[bytes, dict]:
    """Read bounded exact bytes once, then hash and strictly parse those same bytes."""
    path = local_path(ref.path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Artifact must be a regular local file")
    if not 0 < path.stat().st_size <= MAX_ARTIFACT_BYTES:
        raise ValueError("Artifact is empty or exceeds 8 MiB")
    with path.open("rb") as stream:
        data = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(data) > MAX_ARTIFACT_BYTES or hashlib.sha256(data).hexdigest() != ref.sha256:
        raise ValueError("Artifact bytes differ from the expected SHA-256")
    value = json.loads(data, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Artifact JSON must be an object")
    return data, value


def admit(kind: str, value: dict, source: dict) -> tuple[float, TranscriptResult | AVEventsResponse]:
    """Validate the full typed schema, completion, exact source and its presentation clock."""
    if kind == "transcript":
        result = TranscriptResult.model_validate(value)
        if result.status != "complete" or result.outcome not in {"captions", "inferred", "empty"}:
            raise ValueError("Transcript artifact must be complete captions, inferred or empty")
    else:
        result = AVEventsResponse.model_validate(value)
        if result.status != "complete":
            raise ValueError("AV events artifact must be complete")
        if any(r.source_sha256 != source["sha256"] for r in result.records):
            raise ValueError("AV event records cite a different source SHA-256")
    origin = result.source or {}
    if origin.get("sha256") != source["sha256"] or origin.get("bytes") != source["bytes"]:
        raise ValueError("Artifact source identity differs from the memory source")
    end = origin.get("presentation_end_seconds")
    if type(end) not in (int, float) or not math.isfinite(end) or end <= 0:
        raise ValueError("Artifact lacks a finite source presentation clock")
    return float(end), result


def agreed_clock(clocks: list[float]) -> float:
    """One parent clock: every artifact must report the same presentation extent."""
    if not clocks:
        raise ValueError("No admitted artifact establishes the source presentation clock")
    if max(clocks) - min(clocks) > CLOCK_TOLERANCE_SECONDS:
        raise ValueError("Artifacts disagree on the source presentation clock")
    return clocks[0]


def window_count(duration: float) -> int:
    """Fixed 30 s windows covering the whole parent clock."""
    return max(1, math.ceil(duration / WINDOW_SECONDS))


def _drafts(admitted: list) -> list[tuple]:
    drafts = []
    for receipt, result in admitted:
        if receipt.kind == "transcript":
            basis = "asserted" if result.outcome == "captions" else "inferred"
            for seg in result.segments:
                origin = Origin(operation=receipt.operation, artifact_sha256=receipt.sha256, item=seg.id)
                drafts.append(("utterance", seg.start_seconds, seg.end_seconds, basis, seg.text,
                               seg.speaker_id, origin))
            continue
        for rec in result.records:
            kind = "environment" if receipt.role == "environment" else _KIND[rec.basis]
            origin = Origin(operation=receipt.operation, artifact_sha256=receipt.sha256, item=rec.record_id)
            drafts.append((kind, rec.start_seconds, rec.end_seconds, "inferred", rec.description, None, origin))
    return drafts


def fold(source_sha256: str, duration: float, admitted: list) -> tuple[list[MemoryRecord], list[Person]]:
    """Canonical records and first-appearance anonymous persons from admitted artifacts."""
    drafts = sorted(_drafts(admitted), key=lambda d: (d[0], d[1], d[2], d[6].artifact_sha256, d[6].item, d[4]))
    if len(drafts) > MAX_RECORDS:
        raise ValueError(f"Memory exceeds {MAX_RECORDS} records")
    labels: dict[str, str] = {}
    for draft in sorted((d for d in drafts if d[5]), key=lambda d: (d[1], d[5])):
        labels.setdefault(draft[5], draft[3])
    persons = [Person(person_id=f"P{i:03d}", source_label=label, label_basis=basis)
               for i, (label, basis) in enumerate(labels.items(), 1)]
    by_label = {p.source_label: p.person_id for p in persons}
    windows, seq, records = window_count(duration), {}, []
    for kind, start, end, basis, text, label, origin in drafts:
        if end < start or end > duration + CLOCK_TOLERANCE_SECONDS:
            raise ValueError("A record span lies outside the source presentation clock")
        window = min(int(start // WINDOW_SECONDS), windows - 1)
        n = seq[(kind, window)] = seq.get((kind, window), 0) + 1
        if n > 999:
            raise ValueError("More than 999 records of one kind in one window")
        records.append(MemoryRecord(
            record_id=f"{kind}:{source_sha256[:12]}:{window:04d}:{n:03d}", kind=kind, window=window,
            start_seconds=start, end_seconds=end, basis=basis, text=text,
            person_id=by_label.get(label) if label else None, origin=origin))
    return records, persons


def _mention(text: str, name: str) -> str | None:
    """Classify a spoken name as a self introduction or as addressing the next speaker."""
    low, n = text.lower(), re.escape(name.lower())
    if re.search(rf"\b(?:i'?m|i am|my name is)\s+{n}\b(?!'s)", low):
        return "self_intro"
    if (re.search(rf"\b{_GREETING}\s+{n}\b(?!'s)", low) or re.search(rf"^\s*{n}\s*[,:]", low)
            or re.search(rf",\s*{n}\s*[?.!]*\s*$", low) or re.search(rf"{_LEAD}[\s,]+{n}\s*[,?.!:]", low)):
        return "addressed"
    return None


def suggest_names(records: list[MemoryRecord]) -> list[Suggestion]:
    """Nonbinding name candidates from self introductions and turn-taking address."""
    turns = sorted((r for r in records if r.kind == "utterance" and r.person_id),
                   key=lambda r: (r.start_seconds, r.record_id))
    found: dict[tuple[str, str, str], list[str]] = {}
    for i, record in enumerate(turns):
        following = turns[i + 1].person_id if i + 1 < len(turns) else None
        for name in dict.fromkeys(_NAME.findall(record.text)):
            method = None if name.lower() in _NAME_STOP else _mention(record.text, name)
            target = record.person_id if method == "self_intro" else following
            if method and target and not (method == "addressed" and target == record.person_id):
                found.setdefault((target, name, method), []).append(record.record_id)
    return [Suggestion(suggestion_id="S:" + hashlib.sha256(f"{p}|{n}|{m}".encode()).hexdigest()[:12],
                       person_id=p, name=n, method=m, evidence_ids=ids[:32])
            for (p, n, m), ids in sorted(found.items())]


def route_calls(route: AVRoute, duration: float) -> list[dict]:
    """Planned media_caption_events calls: up to four 30 s windows per call and role."""
    edges = [(float(s), min(float(s) + ROUTE_SPAN_SECONDS, duration))
             for s in range(0, math.ceil(duration), int(ROUTE_SPAN_SECONDS))]
    calls = [{"operation": "media_caption_events", "role": role, "start_seconds": a,
              "end_seconds": b, "window_seconds": WINDOW_SECONDS} for a, b in edges for role in route.roles]
    if len(calls) > route.max_calls:
        raise ValueError(f"AV route needs {len(calls)} calls; av_route.max_calls is {route.max_calls}")
    return calls


async def run_route(route: AVRoute, file_path: str, sha256: str, calls: list[dict]) -> list[tuple[str, dict]]:
    """Execute authorized per-window AV calls through the existing caption-events workflow."""
    responses: list[tuple[str, dict]] = []
    for call in calls:
        extra = {"instruction": ENVIRONMENT_INSTRUCTION} if call["role"] == "environment" else {}
        request = CaptionEventsRequest(
            file_path=file_path, expected_source_sha256=sha256, start_seconds=call["start_seconds"],
            end_seconds=call["end_seconds"], window_seconds=WINDOW_SECONDS, dry_run=False,
            authorize_submission=True, thinking_level=route.thinking_level, **extra)
        result = await caption_events(request)
        responses.append((call["role"], result))
        if result.get("status") != "complete":
            raise ProviderFailure("AV route call did not complete; nothing was written",
                                  {"costs": {"route_calls": route_costs(responses)}})
    return responses


def route_costs(responses: list[tuple[str, dict]]) -> list[dict]:
    """Per-call execution accounting exactly as the route reported it."""
    return [{"operation": "media_caption_events", "role": role, "status": r.get("status", "failed"),
             "error": r.get("error"), "execution": r.get("execution")} for role, r in responses]


def induction_batches(state: MemoryState, max_chars: int) -> list[tuple[str, set[str]]]:
    """Bounded prompts listing records by ID; each batch cites only its own IDs."""
    batches, lines, ids = [], [], set()
    for record in sorted(state.records, key=lambda r: (r.start_seconds, r.record_id)):
        who = f" {record.person_id}" if record.person_id else ""
        line = f"[{record.record_id}] {record.start_seconds:.1f}s {record.kind}{who}: {record.text}"
        line = line[: max_chars - len(INDUCE_INSTRUCTION) - 1]
        if lines and len(INDUCE_INSTRUCTION) + sum(map(len, lines)) + len(lines) + len(line) > max_chars:
            batches.append((INDUCE_INSTRUCTION + "\n".join(lines), ids))
            lines, ids = [], set()
        lines.append(line)
        ids.add(record.record_id)
    if lines:
        batches.append((INDUCE_INSTRUCTION + "\n".join(lines), ids))
    return batches


async def induce(options: InduceOptions, batches: list[tuple[str, set[str]]]) -> tuple[list, dict]:
    """One bounded generate_structured call per batch under an execution budget."""
    budget = ExecutionBudget(VisionLimits(max_calls=min(9, 2 * len(batches) + 1), max_tokens=400000,
                                          max_output_tokens=8192))
    outputs = []
    try:
        with budget.activate():
            for prompt, ids in batches:
                answer = await GeminiClient.generate_structured(
                    prompt, schema=InducedFacts, model=options.model, thinking_level=options.thinking_level)
                outputs.append((answer, ids))
    except Exception as exc:
        raise ProviderFailure(f"Fact induction failed: {type(exc).__name__}",
                              {"costs": {"induction": budget.report()}}) from exc
    return outputs, budget.report()


def _induced_fact(item, ids: set[str], persons: set[str], revision: int, model: str | None) -> Fact:
    fact = FactInput.model_validate({**item.model_dump(), "confidence": item.confidence.strip().lower()})
    if not set(fact.evidence_ids) <= ids:
        raise ValueError("cites records outside its batch")
    if fact.subject_id.startswith("P") and fact.subject_id not in persons:
        raise ValueError("names an unknown person")
    return Fact(fact_id=fact_id(fact.subject_id, fact.key, fact.value), **fact.model_dump(),
                basis="inferred", created_revision=revision, updated_revision=revision, model=model)


def _induced_name(item, utterances: set[str], persons: set[str]) -> Suggestion:
    evidence = sorted(set(item.evidence_ids))
    if item.person_id not in persons or not evidence or not set(evidence) <= utterances:
        raise ValueError("needs a known person and utterance evidence from its batch")
    digest = hashlib.sha256(f"{item.person_id}|{item.name}|model".encode()).hexdigest()[:12]
    return Suggestion(suggestion_id="S:" + digest, person_id=item.person_id, name=item.name,
                      method="model_inference", evidence_ids=evidence)


def admit_induced(state: MemoryState, outputs: list, revision: int, model: str | None) -> tuple:
    """Keep only valid items citing their own batch; others are returned as rejected."""
    persons = {p.person_id for p in state.persons}
    utterances = {r.record_id for r in state.records if r.kind == "utterance"}
    facts, suggestions, rejected = [], [], []
    for answer, ids in outputs:
        for item in [*answer.facts, *answer.name_suggestions]:
            try:
                if isinstance(item, InducedFact):
                    facts.append(_induced_fact(item, ids, persons, revision, model))
                else:
                    suggestions.append(_induced_name(item, ids & utterances, persons))
            except ValueError as exc:
                rejected.append({"item": item.model_dump(), "reason": str(exc)[:300]})
    return facts, suggestions, rejected
