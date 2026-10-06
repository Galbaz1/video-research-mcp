"""C1/C2: explicit abstention and exact citation validation over a frozen corpus."""

import os

from jsonschema import validate

from tests.test_grounding_support import cite, claim, grounding_request
from tests.test_grounding_support import grounding_corpus as grounding_corpus
from video_research_mcp.tools.grounding import _SCHEMA, grounded_answer

ALL = "copper overheating light"


async def answer(request):
    result = await grounded_answer(request=request)
    validate(result, _SCHEMA)
    return result


async def test_unsupported_question_abstains_with_missing_evidence(grounding_corpus):
    """GIVEN a question with no retrieved evidence THEN abstain and name what is missing."""
    result = await answer(grounding_request(grounding_corpus, "unicorn galaxy"))
    assert result["status"] == "abstained" and result["retrieval_status"] == "no_evidence"
    assert result["missing_evidence"] == [{"scope": "question", "reason": "no_retrieved_evidence"}]
    assert result["evidence"] == [] and "answer" not in result
    assert result["synthesis"]["status"] == "unsupported"
    assert result["limits"]["provider_calls"] == 0 and result["limits"]["auxiliary_calls"] == 0


async def test_unsupported_claim_citing_unretrieved_evidence_is_rejected(grounding_corpus):
    """A real indexed observation outside this retrieval cannot be cited."""
    claims = [claim("c1", "The circuit is open", cite("speech-1", 0.2, 0.8))]
    result = await answer(grounding_request(grounding_corpus, "unicorn galaxy", claims))
    assert result["status"] == "abstained"
    assert result["claims"][0]["support"] == "unsupported"
    assert result["claims"][0]["rejected"] == [{"citation_index": 0, "reason": "observation_not_retrieved"}]
    assert {"scope": "claim", "claim_id": "c1", "reason": "no_valid_citation",
            "rejections": ["observation_not_retrieved"]} in result["missing_evidence"]
    assert result["trace"][0]["event"] == "citation_rejected"


async def test_verbatim_quote_grounds_claim_with_verified_artifacts(grounding_corpus):
    claims = [claim("c1", "copper circuit is open",
                    cite("speech-1", 0.2, 0.8, "copper circuit   is open"))]
    result = await answer(grounding_request(grounding_corpus, "copper circuit", claims))
    assert result["status"] == "grounded" and result["missing_evidence"] == []
    cited = result["claims"][0]["citations"][0]
    assert cited["quote_verified"] and cited["evidence_basis"] == "supplied_transcript_text"
    assert (cited["start_seconds"], cited["end_seconds"]) == (0.2, 0.8)
    assert cited["observation_span"] == [0.0, 1.0] and cited["source_id"] == "lab@r1"
    assert cited["artifacts"][0]["status"] == "available"
    assert cited["artifacts"][0]["bytes"] == os.path.getsize(grounding_corpus["paths"]["speech-1"])
    assert result["claims"][0]["claim_basis"] == "caller_asserted"
    assert result["citation_availability"] == "current_artifact_bytes_verified_not_factual_truth"


async def test_conflicting_quote_is_not_support_and_mixed_claims_are_partial(grounding_corpus):
    """A quote absent from the cited text is rejected; semantic conflict is not inferred."""
    claims = [claim("a", "The error is A", cite("ocr-1", 0.1, 0.9, "ERROR A")),
              claim("b", "ERROR B", cite("ocr-1", 0.1, 0.9, "ERROR B"))]
    result = await answer(grounding_request(grounding_corpus, ALL, claims))
    assert result["status"] == "partially_grounded"
    first, second = result["claims"]
    assert first["support"] == "unsupported"
    assert first["rejected"] == [{"citation_index": 0, "reason": "quote_not_in_observation"}]
    assert second["support"] == "verbatim_quote"


async def test_out_of_span_citation_is_repaired_to_known_span_with_trace(grounding_corpus):
    claims = [claim("c1", "copper circuit", cite("speech-1", 0.5, 1.5, "copper circuit"))]
    result = await answer(grounding_request(grounding_corpus, ALL, claims))
    cited = result["claims"][0]["citations"][0]
    assert (cited["observation_id"], cited["start_seconds"], cited["end_seconds"]) == ("speech-1", 0.0, 1.0)
    event = result["trace"][0]
    assert event["event"] == "citation_repaired" and event["reason"] == "span_outside_observation"
    assert event["citation"]["end_seconds"] == 1.5
    assert event["repaired_to"] == {"observation_id": "speech-1", "source_revision": "r1",
                                    "start_seconds": 0.0, "end_seconds": 1.0}
    assert result["status"] == "grounded"


async def test_unknown_observation_repairs_only_through_retrieved_verbatim_text(grounding_corpus):
    claims = [claim("c1", "Overheating", cite("ocr-9", 0.1, 0.2, "overheating")),
              claim("c2", "Overheating", cite("ocr-9", 0.1, 0.2))]
    result = await answer(grounding_request(grounding_corpus, ALL, claims))
    assert result["claims"][0]["citations"][0]["observation_id"] == "ocr-1"
    assert result["trace"][0]["basis"] == "verbatim_quote_in_retrieved_observation"
    assert result["claims"][1]["support"] == "unsupported"
    assert result["status"] == "partially_grounded"


async def test_repair_disabled_and_revision_mismatch_reject(grounding_corpus):
    claims = [claim("c1", "Circuit", cite("speech-1", 0.5, 1.5, "copper circuit")),
              claim("c2", "Circuit", cite("speech-1", 0.2, 0.4, "copper circuit", revision="r0"))]
    result = await answer(grounding_request(grounding_corpus, ALL, claims, repair_citations=False))
    assert [c["rejected"][0]["reason"] for c in result["claims"]] == [
        "span_outside_observation", "revision_mismatch"]
    assert result["status"] == "abstained"
    assert all(event["event"] == "citation_rejected" for event in result["trace"])


async def test_changed_symlinked_or_unbudgeted_artifacts_are_unavailable(grounding_corpus):
    """Availability needs current exact bytes; no repair may bypass it."""
    paths = grounding_corpus["paths"]
    paths["speech-1"].write_text("changed transcript bytes")
    target = paths["ocr-1"].with_name("moved.png")
    paths["ocr-1"].rename(target)
    paths["ocr-1"].symlink_to(target)
    claims = [claim("c1", "Circuit", cite("speech-1", 0.2, 0.8, "copper circuit")),
              claim("c2", "Error", cite("ocr-1", 0.1, 0.9, "ERROR B")),
              claim("c3", "red warning light", cite("desc-1", 1.0, 2.0, "red warning light"))]
    result = await answer(grounding_request(grounding_corpus, ALL, claims))
    assert [c["support"] for c in result["claims"]] == ["unsupported", "unsupported", "verbatim_quote"]
    assert all(c["rejected"][0]["reason"] == "artifact_unavailable" for c in result["claims"][:2])
    statuses = {e["observation_id"]: e["artifacts"][0] for e in result["evidence"]}
    assert statuses["speech-1"]["reason"] == "sha256_mismatch"
    assert statuses["ocr-1"]["reason"] == "PermissionError"
    assert statuses["desc-1"]["status"] == "available"
    budgeted = await answer(grounding_request(grounding_corpus, ALL, claims[2:], verify_byte_budget=1))
    assert budgeted["claims"][0]["rejected"] == [{"citation_index": 0, "reason": "artifact_unavailable"}]
    statuses = {e["observation_id"]: e["artifacts"] for e in budgeted["evidence"]}
    assert statuses["desc-1"][0]["reason"] == "verify_byte_budget"
    assert budgeted["limits"]["verified_bytes"] == 0 and budgeted["status"] == "abstained"


async def test_retrieved_evidence_without_claims_is_evidence_only(grounding_corpus):
    result = await answer(grounding_request(grounding_corpus, ALL))
    assert result["status"] == "evidence_only" and result["claims"] == []
    kinds = {e["observation_id"]: e["evidence_basis"] for e in result["evidence"]}
    assert kinds == {"speech-1": "supplied_transcript_text", "ocr-1": "supplied_ocr_text",
                     "desc-1": "caller_asserted_description"}
    assert all(e["artifacts"] == "not_checked" for e in result["evidence"])


async def test_weak_unquoted_citation_is_available_but_semantically_unverified(grounding_corpus):
    claims = [claim("c1", "Something is overheating", cite("ocr-1", 0.1, 0.9))]
    result = await answer(grounding_request(grounding_corpus, ALL, claims))
    assert result["claims"][0]["support"] == "citation_available_semantics_unverified"
    assert result["status"] == "partially_grounded"
    assert result["missing_evidence"] == [{"scope": "claim", "claim_id": "c1", "reason": "no_verbatim_support"}]
    assert result["escalation"]["status"] == "not_requested"


async def test_invalid_request_returns_typed_error(grounding_corpus):
    claims = [claim("c1", "x"), claim("c1", "y")]
    result = await grounded_answer(request=grounding_request(grounding_corpus, ALL, claims))
    validate(result, _SCHEMA)
    assert result["category"] == "SCHEMA_VALIDATION_FAILED" and "unique" in result["error"]
