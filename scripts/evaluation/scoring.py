"""Deterministic canonical-fact judge with independently checked citations."""

from pathlib import Path

from scripts.evaluation.models import Case, Label, Outcome, Usage
from scripts.evaluation.support import contained_path, frozen_sources, sha256, validate_labels


def normalized(text: str) -> str:
    """Normalize case and whitespace only; no semantic guess or model judge."""
    return " ".join(text.casefold().split())


def supported(claim, fact, sources, media_ids) -> tuple[int, bool]:
    """Count citations matching a labeled passage in the actual frozen source."""
    if fact is None or normalized(claim.text) != normalized(fact.text):
        return 0, False
    matches = [
        [citation_matches(citation, evidence, sources, media_ids) for evidence in fact.evidence]
        for citation in claim.citations
    ]
    count = sum(any(row) for row in matches)
    complete = all(any(row[i] for row in matches) for i in range(len(fact.evidence)))
    return count, complete


def citation_matches(citation, evidence, sources, media_ids) -> bool:
    """Match one required passage; media citations use asset/interval bindings."""
    if citation.source_id in media_ids:
        return (
            citation.quote is None
            and citation.source_id == evidence.source_id
            and citation.start_ms == evidence.start_ms
            and citation.end_ms == evidence.end_ms
        )
    return bool(
        citation.quote
        and citation.quote in sources.get(citation.source_id, "")
        and citation == evidence
    )


def score_case(case: Case, label: Label, raw: dict, root: Path, tolerance_ms: int) -> dict:
    """Score one attempted case, retaining invalid output in its denominator."""
    sources = frozen_sources(case, root)
    validate_labels(label, sources)
    try:
        outcome = Outcome.model_validate(raw)
    except ValueError:
        return {
            "case_id": case.id,
            "family": case.family,
            "workflow": case.workflow,
            "status": "invalid",
            "complete": False,
            "structural_valid": False,
            "facts_expected": len(label.facts),
            "facts_correct": 0,
            "facts_supported": 0,
            "claims": 0,
            "citations": 0,
            "citations_supported": 0,
            "temporal_expected": len(label.temporal),
            "temporal_correct": 0,
            "temporal_predicted": 0,
            "artifacts_valid": False,
            "abstention_correct": False,
            "usage": observed_usage(raw),
        }
    if outcome.case_id != case.id:
        raise ValueError("outcome case identity mismatch")
    result = _measures(case, label, outcome, sources, root, tolerance_ms)
    content = (
        not outcome.claims
        if label.expected_abstention
        else (
            result["facts_correct"] == len(label.facts)
            and result["facts_supported"] == len(label.facts)
            and result["claims"] == len(label.facts)
        )
    )
    result["complete"] = (
        outcome.status == label.expected_status
        and content
        and result["artifacts_valid"]
        and result["temporal_correct"] == len(label.temporal)
        and result["temporal_predicted"] == len(label.temporal)
        and result["citations_supported"] == result["citations"]
    )
    return result


def observed_usage(raw: dict) -> dict | None:
    """Retain parseable observations even when the answer body is malformed."""
    try:
        return Usage.model_validate({key: raw.get(key) for key in Usage.model_fields}).model_dump()
    except ValueError:
        return None


def _measures(case, label, outcome, sources, root, tolerance_ms):
    """Keep support, timestamps, artifact bytes and observed usage independent."""
    facts = {fact.id: fact for fact in label.facts}
    correct, grounded = set(), set()
    citations_supported = 0
    media_ids = {
        s.id
        for s in case.sources
        if not s.content_type.startswith("text/") and s.content_type != "application/json"
    }
    for claim in outcome.claims:
        fact = next((f for f in label.facts if normalized(claim.text) == normalized(f.text)), None)
        if fact and normalized(claim.text) == normalized(fact.text):
            correct.add(fact.id)
        count, complete = supported(claim, fact, sources, media_ids)
        citations_supported += count
        if complete:
            grounded.add(fact.id)
    times = {t.id: t for t in label.temporal}
    matched_times = {
        t.id
        for t in outcome.temporal
        if t.id in times
        and abs(t.start_ms - times[t.id].start_ms) <= tolerance_ms
        and abs(t.end_ms - times[t.id].end_ms) <= tolerance_ms
    }
    valid_artifacts = set()
    for artifact in outcome.artifacts:
        path = contained_path(root, artifact.path)
        if path.is_file() and path.stat().st_size and sha256(path) == artifact.sha256:
            valid_artifacts.add(artifact.id)
    artifacts_valid = set(label.required_artifacts) <= valid_artifacts
    temporal_valid = len({t.id for t in outcome.temporal}) == len(outcome.temporal)
    result = {
        "case_id": case.id,
        "family": case.family,
        "workflow": case.workflow,
        "status": outcome.status,
        "structural_valid": True,
        "facts_expected": len(facts),
        "facts_correct": len(correct),
        "facts_supported": len(grounded),
        "claims": len(outcome.claims),
        "citations": sum(len(c.citations) for c in outcome.claims),
        "citations_supported": citations_supported,
        "temporal_expected": len(times),
        "temporal_correct": len(matched_times) if temporal_valid else 0,
        "temporal_predicted": len(outcome.temporal),
        "artifacts_valid": artifacts_valid,
        "abstention_correct": label.expected_abstention
        and outcome.status == "abstained"
        and not outcome.claims,
        "usage": outcome.model_dump(
            include={
                "latency_ms",
                "calls",
                "auxiliary_calls",
                "cost_usd",
                "input_tokens",
                "output_tokens",
            }
        ),
    }
    return result
