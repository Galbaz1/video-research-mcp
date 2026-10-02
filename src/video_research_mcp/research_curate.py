"""Bind research proposals to exact original passages without certifying truth."""

import hashlib

from .models.evidence import EvidenceClaim, EvidenceReference, SourcePassage
from .research_execution_provider import protect


def _passage(citation, sources):
    """Admit an exact text quote or an existing original media observation."""
    source = next((s for s in sources if s.id == citation.source_id), None)
    if source is None:
        return None, None, "unknown_source_id"
    if citation.passage_id is not None:
        passage = next((p for p in source.passages if p.id == citation.passage_id), None)
        if passage is None or passage.quote != citation.quote:
            return source, None, "missing_or_changed_passage"
        return source, passage, None
    if source.modality not in {"text", "geometry", "tabular"}:
        return source, None, "media_requires_original_passage_id"
    if citation.quote not in source.snapshot.text:
        return source, None, "quote_absent_from_original_snapshot"
    existing = next((p for p in source.passages if p.quote == citation.quote), None)
    if existing is not None:
        return source, existing, None
    identifier = "quote-" + hashlib.sha256(citation.quote.encode()).hexdigest()
    if len(source.passages) >= 256 or any(p.id == identifier for p in source.passages):
        return source, None, "passage_identity_or_population_limit"
    passage = SourcePassage(id=identifier, quote=citation.quote)
    source.passages.append(passage)
    return source, passage, None


def _references(citations, sources):
    """Retain rejected references and page/time metadata alongside admitted IDs."""
    references, records, rejected = [], [], []
    for citation in citations:
        source, passage, error = _passage(citation, sources)
        record = citation.model_dump(mode="json")
        if error:
            rejected.append({**record, "reason": error})
            continue
        reference = EvidenceReference(source_id=source.id, passage_id=passage.id)
        if reference not in references:
            references.append(reference)
        records.append({**reference.model_dump(mode="json"), "quote": passage.quote,
                        "source_sha256": source.sha256, "revision": source.revision,
                        "snapshot_sha256": source.snapshot.sha256, "page": getattr(passage, "page", None),
                        "start_ms": passage.start_ms, "end_ms": passage.end_ms,
                        "integrity": "bound_to_frozen_original", "semantic_support": "not_verified"})
    return references, records, rejected


def curate(answer, context: dict, branch: int, revision: int) -> dict:
    """Keep model tiers as proposals and preserve every unsupported addition."""
    rows, claims = [], []
    for index, finding in enumerate(answer.findings):
        refs, support, rejected = _references(finding.citations, context["sources"])
        _, contradicting, contradicted_rejections = _references(finding.contradicting_citations, context["sources"])
        flags = [r["reason"] for r in rejected + contradicted_rejections]
        exact = bool(refs) and all(item["quote"] == finding.text for item in support)
        if not finding.abstained and not exact:
            flags.append("new_fact_or_paraphrase_has_no_exact_source_text")
        claim_id = f"research-{context['run_id']}-{branch}-{revision}-{index}"
        claim = EvidenceClaim(id=claim_id, text=finding.text, support=refs,
                              editorial_approved=False, abstained=finding.abstained,
                              confidence=finding.confidence,
                              contradicting_support=contradicting)
        row = {**finding.model_dump(mode="json"), "claim_id": claim_id,
               "evidence_tier": "UNKNOWN", "tier_authority": "model_proposal",
               "support": support, "contradicting_support": contradicting,
               "rejected_citations": rejected + contradicted_rejections,
               "unsupported_additions": flags,
               "source_support": "exact_source_text" if exact else "unknown",
               "semantic_support": "not_verified", "factual_success": False}
        rows.append(protect(row, context["selected"][1]))
        claims.append(claim)
    unresolved = bool(answer.missing_evidence or answer.contradictions or answer.needs_revision
                      or any(f.contradicting_citations for f in answer.findings))
    if context["request"].mode != "model_only":
        unresolved = unresolved or any(row["unsupported_additions"] for row in rows)
    return {"summary": protect(answer.summary, context["selected"][1]), "findings": rows,
            "missing_evidence": protect(answer.missing_evidence, context["selected"][1]),
            "contradictions": protect(answer.contradictions, context["selected"][1]),
            "unresolved": unresolved, "claims": claims}
