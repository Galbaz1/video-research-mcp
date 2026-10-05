"""Fixed-denominator outcome evaluation over frozen grounding cases.

Expected outcomes come only from the frozen cohort; results never relabel a case.
Missing results stay in the denominator as ``unrun`` and typed tool errors are kept
as refusals or failures. Agreement is not semantic accuracy or calibrated confidence.
"""

import hashlib

from .corpus_index import canonical

ANSWERS = ("grounded", "partially_grounded", "abstained", "evidence_only")
OUTCOMES = (*ANSWERS, "refused", "failed", "unrun")
REFUSALS = {"SCHEMA_VALIDATION_FAILED", "PERMISSION_DENIED", "URL_POLICY_BLOCKED",
            "API_INVALID_ARGUMENT", "FILE_UNSUPPORTED", "FILE_TOO_LARGE"}


def cohort_sha256(cases: list[dict]) -> str:
    """Digest of the canonical frozen cohort, including expected outcomes."""
    return hashlib.sha256(canonical(cases).encode("utf-8")).hexdigest()


def outcome(result: dict | None) -> str:
    """Map one grounding result or typed tool error onto a retained outcome."""
    if result is None:
        return "unrun"
    if result.get("status") in ANSWERS:
        return result["status"]
    if isinstance(result.get("error"), str) and "category" in result:
        return "refused" if result["category"] in REFUSALS else "failed"
    raise ValueError("Unrecognized grounding result shape")


def evaluate(cases: list[dict], expected_sha256: str, results: dict[str, dict]) -> dict:
    """Score every frozen case against its declared outcome with a fixed denominator."""
    if not cases or cohort_sha256(cases) != expected_sha256:
        raise ValueError("Cohort is empty or differs from its frozen digest")
    ids = [case["case_id"] for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("Frozen cohort case_id values must be unique")
    if any(case["expected_outcome"] not in OUTCOMES for case in cases):
        raise ValueError("Frozen cohort names an unknown expected outcome")
    if extra := sorted(set(results) - set(ids)):
        raise ValueError(f"Results name cases outside the frozen cohort: {extra}")
    counts, rows, auxiliary = dict.fromkeys(OUTCOMES, 0), [], 0
    for case in cases:
        result = results.get(case["case_id"])
        actual = outcome(result)
        counts[actual] += 1
        limits = (result or {}).get("limits", {})
        auxiliary += limits.get("auxiliary_calls", 0) + limits.get("provider_calls", 0)
        rows.append({"case_id": case["case_id"], "expected": case["expected_outcome"],
                     "actual": actual, "match": actual == case["expected_outcome"]})
    matches = sum(row["match"] for row in rows)
    return {"cohort_sha256": expected_sha256, "denominator": len(cases), "outcomes": counts,
            "expected_outcome_matches": matches, "expected_outcome_agreement": matches / len(cases),
            "auxiliary_calls": auxiliary, "cases": rows,
            "interpretation": "outcome agreement on frozen fixtures; not semantic accuracy or calibrated confidence"}
