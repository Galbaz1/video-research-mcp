"""Validate caller claims against exactly retrieved evidence; abstain when unsupported.

Retrieval reuses the canonical corpus query. A citation counts only when it names a
retrieved observation, its revision, an interval inside that observation and, when
quoted, text present in the indexed observation; every referenced artifact must
still match its recorded SHA256 under a bounded read. Availability is not truth.
"""

import asyncio
import hashlib
import stat

from .corpus_retrieval import query
from .grounding_escalation import escalate
from .media_local_io import _open_regular
from .media_snapshot import checked_path
from .models.grounding import ClaimResult, EscalationReport, GroundingRequest, GroundingResult

EPSILON = 1e-9
BASIS = {"speech": "supplied_transcript_text", "OCR": "supplied_ocr_text",
         "description": "caller_asserted_description"}


def _normalized(text: str) -> str:
    return " ".join(text.split())


def contains_quote(text: str, quote: str) -> bool:
    """Case-sensitive verbatim match after collapsing whitespace runs only."""
    normalized = _normalized(quote)
    return bool(normalized) and normalized in _normalized(text)


def _bounded_digest(path, limit: int) -> tuple[str, int]:
    """Hash a verified regular file with a bounded read that rejects growth."""
    digest, total = hashlib.sha256(), 0
    with _open_regular(path) as handle:
        while chunk := handle.read(min(1 << 20, limit + 1 - total)):
            total += len(chunk)
            if total > limit:
                raise ValueError("Artifact grew beyond its verified size")
            digest.update(chunk)
    return digest.hexdigest(), total


async def _ref_status(ref: dict, state: dict) -> dict:
    record = {"artifact_id": ref["artifact_id"], "kind": ref["kind"], "sha256": ref["sha256"]}
    try:
        path = checked_path(ref["path"])
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            return {**record, "status": "unavailable", "reason": "not_regular_file"}
        if info.st_size > state["budget"] - state["read"]:
            return {**record, "status": "unverified", "reason": "verify_byte_budget"}
        state["read"] += info.st_size
        digest, size = await asyncio.to_thread(_bounded_digest, path, info.st_size)
    except FileNotFoundError:
        return {**record, "status": "unavailable", "reason": "missing"}
    except (OSError, ValueError) as exc:
        return {**record, "status": "unavailable", "reason": type(exc).__name__}
    if digest != ref["sha256"] or size != info.st_size:
        return {**record, "status": "unavailable", "reason": "sha256_mismatch"}
    return {**record, "status": "available", "bytes": size}


async def _artifacts(chunk: dict, state: dict) -> list[dict]:
    key = chunk["observation_id"]
    if key not in state["cache"]:
        state["cache"][key] = [await _ref_status(ref, state) for ref in chunk["artifact_refs"]]
    return state["cache"][key]


def _available(artifacts: list[dict]) -> bool:
    return all(item["status"] == "available" for item in artifacts)


def _problem(citation, chunk) -> str | None:
    if chunk is None:
        return "observation_not_retrieved"
    if chunk["source_revision"] != citation.source_revision:
        return "revision_mismatch"
    if (citation.start_seconds < chunk["start_seconds"] - EPSILON
            or citation.end_seconds > chunk["end_seconds"] + EPSILON):
        return "span_outside_observation"
    if citation.quote is not None and not contains_quote(chunk["text"], citation.quote):
        return "quote_not_in_observation"
    return None


def _cited(chunk: dict, start: float, end: float, quote, artifacts) -> dict:
    return {"observation_id": chunk["observation_id"], "source_id": chunk["source_id"],
            "video_id": chunk["video_id"], "source_revision": chunk["source_revision"],
            "media_digest": chunk["media_digest"], "kind": chunk["kind"],
            "evidence_basis": BASIS[chunk["kind"]], "start_seconds": start, "end_seconds": end,
            "observation_span": [chunk["start_seconds"], chunk["end_seconds"]],
            "quote": quote, "quote_verified": quote is not None, "artifacts": artifacts}


async def _repair(citation, chunks: list[dict], state: dict):
    """Re-anchor a quoted citation to the first retrieved observation containing it."""
    if citation.quote is None:
        return None
    for chunk in chunks:
        if contains_quote(chunk["text"], citation.quote):
            artifacts = await _artifacts(chunk, state)
            if _available(artifacts):
                return _cited(chunk, chunk["start_seconds"], chunk["end_seconds"], citation.quote, artifacts)
    return None


async def _validate(claim, chunks: list[dict], repair: bool, state: dict, trace: list) -> ClaimResult:
    by_id = {chunk["observation_id"]: chunk for chunk in chunks}
    cited, rejected = [], []
    for index, citation in enumerate(claim.citations):
        chunk = by_id.get(citation.observation_id)
        reason = _problem(citation, chunk)
        if reason is None:
            artifacts = await _artifacts(chunk, state)
            if _available(artifacts):
                cited.append(_cited(chunk, citation.start_seconds, citation.end_seconds,
                                    citation.quote, artifacts))
                continue
            reason = "artifact_unavailable"
        event = {"claim_id": claim.claim_id, "citation_index": index, "reason": reason,
                 "citation": citation.model_dump(mode="json")}
        repaired = await _repair(citation, chunks, state) if repair else None
        if repaired is not None:
            cited.append(repaired)
            trace.append({**event, "event": "citation_repaired",
                          "basis": "verbatim_quote_in_retrieved_observation",
                          "repaired_to": {k: repaired[k] for k in ("observation_id", "source_revision",
                                                                   "start_seconds", "end_seconds")}})
        else:
            rejected.append({"citation_index": index, "reason": reason})
            trace.append({**event, "event": "citation_rejected"})
    verbatim = any(c["quote_verified"] and _normalized(claim.text) == _normalized(c["quote"])
                   for c in cited)
    support = ("verbatim_quote" if verbatim
               else "citation_available_semantics_unverified" if cited else "unsupported")
    return ClaimResult(claim_id=claim.claim_id, text=claim.text, support=support,
                       citations=cited, rejected=rejected)


def _missing(claims: list[ClaimResult], found: bool) -> list[dict]:
    missing = [] if found else [{"scope": "question", "reason": "no_retrieved_evidence"}]
    for claim in claims:
        if claim.support == "unsupported":
            missing.append({"scope": "claim", "claim_id": claim.claim_id, "reason": "no_valid_citation",
                            "rejections": [item["reason"] for item in claim.rejected]})
        elif claim.support != "verbatim_quote":
            missing.append({"scope": "claim", "claim_id": claim.claim_id, "reason": "no_verbatim_support"})
    return missing


def _status(claims: list[ClaimResult], found: bool) -> str:
    if not claims:
        return "evidence_only" if found else "abstained"
    supports = {claim.support for claim in claims}
    if supports == {"verbatim_quote"}:
        return "grounded"
    return "abstained" if supports == {"unsupported"} else "partially_grounded"


async def ground(request: GroundingRequest) -> dict:
    """Retrieve, validate citations, abstain explicitly and optionally escalate weak claims."""
    request = GroundingRequest.model_validate(request.model_dump(mode="json"))
    retrieved = await query(request.retrieval)
    chunks = retrieved["context"].get("chunks", [])
    found = retrieved["status"] == "found"
    state, trace = {"budget": request.verify_byte_budget, "read": 0, "cache": {}}, []
    claims = [await _validate(claim, chunks, request.repair_citations, state, trace)
              for claim in request.claims]
    weak = [(claim.claim_id, claim.citations[0]) for claim in claims
            if claim.support == "citation_available_semantics_unverified"]
    if request.escalation is None:
        report = EscalationReport(status="not_requested")
    elif not weak:
        report = EscalationReport(status="not_needed")
    else:
        report = await escalate(request.escalation, weak)
    evidence = [{**{k: chunk[k] for k in ("observation_id", "source_id", "source_revision", "kind",
                                          "start_seconds", "end_seconds", "text")},
                 "evidence_basis": BASIS[chunk["kind"]],
                 "artifacts": state["cache"].get(chunk["observation_id"], "not_checked")}
                for chunk in chunks]
    return GroundingResult(
        status=_status(claims, found), query=request.retrieval.query,
        retrieval_status=retrieved["status"], collection=retrieved["collection"],
        index_revision=retrieved["index_revision"], claims=claims,
        missing_evidence=_missing(claims, found), evidence=evidence, trace=trace, escalation=report,
        limits={"provider_calls": 0, "auxiliary_calls": len(report.attempts),
                "verify_byte_budget": request.verify_byte_budget, "verified_bytes": state["read"],
                "retrieval_active_mode": retrieved["retrieval"].get("active_mode"),
                "estimated_context_tokens": retrieved["estimated_tokens"]},
    ).model_dump(mode="json")
