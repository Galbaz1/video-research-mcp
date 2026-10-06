"""C4: frozen development cohort with a fixed denominator; nothing is relabelled."""

import pytest

from tests.test_grounding_support import cite, claim, grounding_request
from tests.test_grounding_support import grounding_corpus as grounding_corpus
from video_research_mcp.grounding_quality import cohort_sha256, evaluate, outcome
from video_research_mcp.tools.grounding import grounded_answer

# Frozen before any case was executed; expected outcomes are declarations, not results.
CASES = [
    {"case_id": "supported-quote", "query": "copper circuit", "expected_outcome": "grounded",
     "claims": [claim("c1", "The circuit is open", cite("speech-1", 0.2, 0.8, "copper circuit is open"))]},
    {"case_id": "unsupported-question", "query": "unicorn galaxy", "expected_outcome": "abstained",
     "claims": []},
    {"case_id": "conflicting-quote", "query": "overheating", "expected_outcome": "abstained",
     "claims": [claim("c1", "The error is A", cite("ocr-1", 0.1, 0.9, "ERROR A"))]},
    {"case_id": "out-of-span-repair", "query": "copper overheating", "expected_outcome": "grounded",
     "claims": [claim("c1", "Circuit", cite("speech-1", 0.5, 1.5, "copper circuit"))]},
    {"case_id": "weak-citation", "query": "overheating", "expected_outcome": "partially_grounded",
     "claims": [claim("c1", "Something overheats", cite("ocr-1", 0.1, 0.9))]},
    {"case_id": "evidence-only", "query": "light", "expected_outcome": "evidence_only", "claims": []},
    {"case_id": "duplicate-claims", "query": "light", "expected_outcome": "refused",
     "claims": [claim("c1", "x"), claim("c1", "y")]},
    {"case_id": "missing-index", "query": "light", "expected_outcome": "failed", "claims": [],
     "index": "absent.sqlite3"},
    {"case_id": "budget-not-run", "query": "light", "expected_outcome": "evidence_only", "claims": []},
]
FROZEN_SHA256 = "a395d460ec21e9c9c65f2110fa8526e47eb58ea48690ae4f9233514f3d6ba43c"
SKIPPED = {"budget-not-run"}


async def run_cohort(corpus, tmp_path) -> dict:
    results = {}
    for case in CASES:
        if case["case_id"] in SKIPPED:
            continue
        target = {**corpus, "index_path": str(tmp_path / case["index"])} if "index" in case else corpus
        results[case["case_id"]] = await grounded_answer(
            request=grounding_request(target, case["query"], case["claims"]))
    return results


async def test_frozen_cohort_retains_every_outcome_in_fixed_denominator(grounding_corpus, tmp_path):
    """GIVEN frozen cases WHEN evaluated THEN failures, refusals, abstentions and unrun stay counted."""
    assert cohort_sha256(CASES) == FROZEN_SHA256
    report = evaluate(CASES, FROZEN_SHA256, await run_cohort(grounding_corpus, tmp_path))
    assert report["denominator"] == len(CASES) == 9
    actual = {row["case_id"]: row["actual"] for row in report["cases"]}
    assert actual["budget-not-run"] == "unrun"
    assert report["outcomes"]["unrun"] == 1 and sum(report["outcomes"].values()) == 9
    assert report["outcomes"]["abstained"] >= 2 and report["outcomes"]["refused"] + report["outcomes"]["failed"] >= 2
    assert report["expected_outcome_agreement"] == report["expected_outcome_matches"] / 9
    assert report["auxiliary_calls"] == 0
    assert "not semantic accuracy" in report["interpretation"]


def test_evaluation_refuses_changed_cohort_unknown_results_and_shapes():
    changed = [{**CASES[0], "expected_outcome": "abstained"}, *CASES[1:]]
    with pytest.raises(ValueError, match="frozen digest"):
        evaluate(changed, FROZEN_SHA256, {})
    with pytest.raises(ValueError, match="outside the frozen cohort"):
        evaluate(CASES, FROZEN_SHA256, {"extra": {"status": "grounded"}})
    with pytest.raises(ValueError, match="Unrecognized"):
        outcome({"answer": "fabricated"})
    empty = evaluate(CASES, FROZEN_SHA256, {})
    assert empty["outcomes"]["unrun"] == 9 and empty["expected_outcome_matches"] == 0
