"""Reconcile source support and rendered text/audio/frame additions for one project.

Reuses the package evidence validator for original-source integrity, exact-quote support
and production lineage. Everything here is deterministic literal evidence (exact quote
equality and normalized token cover); no model, OCR, ASR, render or network call happens.
Rendered observations arrive as already-recovered text labelled with their method.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .evidence import validate_evidence_packet
from .file_io import open_regular
from .models.evidence import EvidencePacket
from .models.render_factcheck import (
    ClaimCheck, ClaimJudgment, Dimension, JudgmentRecord, ObservationCheck, QualityReport,
    RenderedObservation, RenderFactcheckRequest, RenderFactcheckResult, RenderReceipt, SourceReference,
)
from .planning_sources import project_directory, read_object

PACKET = "input/evidence-packet.json"
MAX_RENDER_BYTES = 512 * 1024 * 1024
TOKEN = re.compile(r"(?<!\w)\.\d+|\w+(?:[.,']\w+)*|!=|[+\-−<>≤≥=≠≈±/%*^×÷]")
VISUAL = {"caption", "overlay_text", "frame_ocr"}
FACTUAL_BASIS = ("exact original-quote support plus normalized literal token reconciliation of observed "
                 "rendered text; deterministic fixture-grade evidence, not general factual truth")


def tokens(text: str) -> list[str]:
    """Casefold words while retaining numeric signs, leading decimals and factual operators."""
    return TOKEN.findall(text.casefold())


def _references(packet: dict, failed: set[str]) -> dict:
    """Map every passage; a source that failed integrity contributes no quote or hash."""
    refs = {}
    for source in packet["sources"]:
        ok = source["id"] not in failed
        for passage in source["passages"]:
            refs[(source["id"], passage["id"])] = SourceReference(
                source_id=source["id"], passage_id=passage["id"], quote=passage["quote"] if ok else None,
                source_sha256=source["sha256"] if ok else None,
                start_ms=passage.get("start_ms"), end_ms=passage.get("end_ms"))
    return refs


def _resolve(refs: dict, references: list[dict]) -> list[SourceReference]:
    """Unknown passages stay visible as unresolved references rather than disappearing."""
    return [refs.get((r["source_id"], r["passage_id"])) or SourceReference(
        source_id=r["source_id"], passage_id=r["passage_id"], quote=None, source_sha256=None) for r in references]


def _judgment(judgment: ClaimJudgment, claim: dict, refs: dict) -> JudgmentRecord:
    """Record the asserted verdict; only its correction quotes are checked, never the verdict."""
    corrections = _resolve(refs, [r.model_dump() for r in judgment.correction_refs])
    record = JudgmentRecord(verdict=judgment.verdict, method=judgment.method, judge=judgment.judge,
                            corrections=corrections)
    if any(c.quote is None for c in corrections):
        record.issues.append("correction reference is not an integrity-checked original passage")
    if judgment.verdict == "false":
        usable = [c for c in corrections if c.quote is not None and tokens(c.quote) != tokens(claim["text"])]
        if not usable or len(usable) != len(corrections):
            record.issues.append("false verdict lacks a verified correction quote that differs from the claim")
    return record


def check_claim(claim: dict, support: str, refs: dict, failed: set[str], judgment: ClaimJudgment | None) -> ClaimCheck:
    """Verified support decides 'supported'; an asserted 'false' needs a verified correction quote."""
    references = _resolve(refs, claim["support"])
    if support == "abstained":
        verified = "abstained"
    elif any(r["source_id"] in failed for r in claim["support"]):
        verified = "source_unavailable"
    else:
        verified = "exact_source_text" if support == "exact_source_text" else "no_exact_source_text"
    record = _judgment(judgment, claim, refs) if judgment else None
    if verified in {"abstained", "source_unavailable"}:
        status, method = "unknown", f"verified_support:{verified}"
    elif verified == "exact_source_text":
        status, method = "supported", "deterministic_exact_quote"
    elif record and record.verdict == "false" and not record.issues:
        status, method = "false", f"asserted:{record.method}+verified_correction_quote"
    else:
        status, method = "unsupported", "no_exact_source_text"
    if record and record.verdict == "supported" and status != "supported":
        record.issues.append("asserted supported without exact original support; not promoted")
    if record and record.verdict != "supported" and status == "supported":
        record.issues.append("asserted verdict conflicts with exact original support")
    return ClaimCheck(claim_id=claim["id"], text=claim["text"], editorial_approved=claim["editorial_approved"],
                      verified_support=verified, support_references=references, judgment=record,
                      factual_status=status, status_method=method)


def _cover(words: list[str], claim_tokens: dict) -> tuple[list[str], list[str]]:
    """Greedy longest literal claim match at each position; unmatched runs are additions."""
    ordered = sorted(((cid, seq) for cid, seq in claim_tokens.items() if seq), key=lambda item: -len(item[1]))
    matched, additions, run, index = [], [], [], 0
    while index < len(words):
        hit = next((cid for cid, seq in ordered if words[index:index + len(seq)] == seq), None)
        if hit is None:
            run.append(words[index])
            index += 1
            continue
        if run:
            additions.append(" ".join(run))
            run = []
        matched.append(hit)
        index += len(claim_tokens[hit])
    if run:
        additions.append(" ".join(run))
    return list(dict.fromkeys(matched)), additions


def reconcile(observation: RenderedObservation, claim_tokens: dict, checks: dict, approved: set[str]) -> ObservationCheck:
    """Find claims in observed text independently; declared IDs are compared, never trusted."""
    found, additions = _cover(tokens(observation.text), claim_tokens)
    unapproved = [cid for cid in found if cid not in approved]
    declared = sorted(set(observation.claim_ids)) == sorted(found)
    return ObservationCheck(
        id=observation.id, channel=observation.channel, method=observation.method, matched_claim_ids=found,
        declared_claim_ids=list(observation.claim_ids), declared_matches=declared, additions=additions,
        unapproved_claim_ids=unapproved, false_claim_ids=[c for c in found if checks[c].factual_status == "false"],
        reconciled=not additions and not unapproved and declared)


def _factual(report: dict, checks: dict, observed: list[ObservationCheck]) -> Dimension:
    """Fail on any load, lineage or rendered discrepancy; no observations is UNKNOWN, never pass."""
    reasons = [] if checks else ["packet has no claims; empty input is never a factual pass"]
    reasons += [f"source load/integrity failed: {error}" for error in report["source_errors"]]
    reasons += [f"lineage: {error}" for error in report["lineage_errors"]]
    for item in observed:
        reasons += [f"{item.id}: unapproved addition {text!r}" for text in item.additions]
        reasons += [f"{item.id}: renders unapproved or unsupported claim {cid}" for cid in item.unapproved_claim_ids]
        if not item.declared_matches:
            reasons.append(f"{item.id}: declared claim IDs {item.declared_claim_ids} != observed {item.matched_claim_ids}")
    details = [{"claim_id": c.claim_id, "factual_status": c.factual_status, "method": c.status_method} for c in checks.values()]
    if reasons:
        return Dimension(status="fail", basis=FACTUAL_BASIS, reasons=reasons, details=details)
    if not observed:
        return Dimension(status="UNKNOWN", basis=FACTUAL_BASIS, reasons=["no rendered observations supplied"], details=details)
    return Dimension(status="pass", basis=FACTUAL_BASIS, details=details)


def _legibility(observed: list[ObservationCheck]) -> Dimension:
    """Frame OCR recovering approved text is a text-recovery proxy, not human legibility."""
    basis = "OCR text-recovery proxy: frame OCR reproduced claim text exactly after normalization; not human legibility"
    frames = [item for item in observed if item.channel == "frame_ocr"]
    if not frames:
        return Dimension(status="UNKNOWN", basis=basis, reasons=["no frame OCR observations"])
    failed = [f"{item.id}: OCR text not fully recovered as claim text" for item in frames
              if item.additions or not item.matched_claim_ids]
    return Dimension(status="fail" if failed else "pass", basis=basis, reasons=failed)


def _synchronization(raw: list[RenderedObservation], observed: list[ObservationCheck], tolerance: int) -> Dimension:
    """Same-claim start agreement between voiceover ASR and a visual text channel."""
    basis = f"same-claim start-time agreement within {tolerance} ms across voiceover ASR and visual text; recorded clocks"
    timed = [(o, c) for o, c in zip(raw, observed) if o.start_ms is not None]
    pairs = [{"claim_id": cid, "voiceover": a.id, "visual": b.id, "start_delta_ms": abs(a.start_ms - b.start_ms)}
             for a, ac in timed if a.channel == "voiceover_asr"
             for b, bc in timed if b.channel in VISUAL
             for cid in sorted(set(ac.matched_claim_ids) & set(bc.matched_claim_ids))]
    if not pairs:
        return Dimension(status="UNKNOWN", basis=basis, reasons=["no claim observed with intervals in both voiceover and visual text"])
    late = [f"{p['claim_id']}: {p['voiceover']}/{p['visual']} differ by {p['start_delta_ms']} ms" for p in pairs
            if p["start_delta_ms"] > tolerance]
    return Dimension(status="fail" if late else "pass", basis=basis, reasons=late, details=pairs)


def _output_sha256(path: Path) -> str:
    """Hash bounded current output bytes through the regular-file guard."""
    digest, consumed = hashlib.sha256(), 0
    with open_regular(path) as (stream, _):
        while chunk := stream.read(64 * 1024):
            consumed += len(chunk)
            if consumed > MAX_RENDER_BYTES:
                raise ValueError("Render output exceeds byte ceiling")
            digest.update(chunk)
    return digest.hexdigest()


def _completion(project: Path, receipt: RenderReceipt | None) -> Dimension:
    """Completed receipt plus matching current output bytes; decode/playback is checked elsewhere."""
    basis = "current output bytes match a completed render receipt; playback/decode verified separately"
    if receipt is None:
        return Dimension(status="UNKNOWN", basis=basis, reasons=["no render receipt supplied"])
    reasons = [] if receipt.status == "completed" else [f"renderer status {receipt.status}"]
    try:
        path = (project / receipt.output_path).resolve()
        path.relative_to(project)
        if _output_sha256(path) != receipt.expected_sha256:
            reasons.append("output bytes differ from the receipt sha256")
    except (OSError, ValueError) as error:
        reasons.append(f"output unavailable: {error}")
    return Dimension(status="fail" if reasons else "pass", basis=basis, reasons=reasons)


def render_factcheck(project_id: str, request: RenderFactcheckRequest) -> dict:
    """Check the project's packet claims and reconcile rendered observations; raise on load failure."""
    project = project_directory(project_id)
    value, packet_sha = read_object(project / PACKET, project)
    packet = EvidencePacket.model_validate(value).model_dump(mode="json")
    report = validate_evidence_packet(packet, project / "input")
    failed = {s["id"] for s in packet["sources"] if any(e.startswith(f"{s['id']}: ") for e in report["source_errors"])}
    judgments = {j.claim_id: j for j in request.judgments}
    unknown = set(judgments) - {claim["id"] for claim in packet["claims"]}
    if unknown or len(judgments) != len(request.judgments):
        raise ValueError(f"Judgments must name distinct packet claim IDs; unknown: {sorted(unknown)}")
    refs = _references(packet, failed)
    checks = {claim["id"]: check_claim(claim, report["claim_support"][claim["id"]], refs, failed,
                                       judgments.get(claim["id"])) for claim in packet["claims"]}
    approved = {cid for cid, c in checks.items() if c.editorial_approved and c.factual_status == "supported"}
    claim_tokens = {cid: tokens(c.text) for cid, c in checks.items()}
    observed = [reconcile(o, claim_tokens, checks, approved) for o in request.observations]
    quality = QualityReport(
        factual_support=_factual(report, checks, observed),
        narration_clarity=Dimension(status="UNKNOWN", basis="not observed: needs a listener or calibrated judgment; ASR text recovery is not clarity"),
        legibility=_legibility(observed),
        synchronization=_synchronization(request.observations, observed, request.sync_tolerance_ms),
        render_completion=_completion(project, request.render))
    seen = {cid for item in observed for cid in item.matched_claim_ids}
    return RenderFactcheckResult(
        project_id=project_id, packet_sha256=packet_sha, source_errors=report["source_errors"],
        lineage_errors=report["lineage_errors"], claims=list(checks.values()), observations=observed,
        unobserved_approved_claim_ids=sorted(approved - seen), quality=quality,
        factual_pass=quality.factual_support.status == "pass").model_dump()
