"""Replay frozen system outputs without provider access or hidden retries."""

from collections import Counter
from pathlib import Path

from scripts.evaluation.models import Case, Label, Receipt
from scripts.evaluation.scoring import score_case
from scripts.evaluation.support import evaluator_hash, read_json, sha256


def replay(bundle: Path, outputs: Path, receipt_path: Path, protocol_path: Path) -> dict:
    """Verify run controls, then score every frozen case exactly once."""
    receipt = Receipt.model_validate(read_json(receipt_path))
    protocol = read_json(protocol_path)
    experiment = read_json(bundle / "experiment.json")
    commitments = {
        "prompt_sha256": sha256(bundle / "prompt.txt"),
        "inputs_sha256": sha256(bundle / "inputs.json"),
        "labels_sha256": sha256(bundle / "labels.json"),
        "outputs_sha256": sha256(outputs),
        "protocol_sha256": sha256(protocol_path),
        "evaluator_sha256": evaluator_hash(),
        "experiment_sha256": sha256(bundle / "experiment.json"),
        "source_snapshots_sha256": sha256(bundle / "source-snapshots.json")
        if (bundle / "source-snapshots.json").exists()
        else None,
    }
    for key, actual in commitments.items():
        if getattr(receipt, key) != actual:
            raise ValueError(f"run commitment changed: {key}")
    for key in ("candidate_revision", "baseline_revision"):
        if getattr(receipt, key) != experiment[key]:
            raise ValueError(f"source revision differs from experiment: {key}")
    arm = experiment["systems"].get(receipt.system)
    if arm is None or arm["provider_settings"] != receipt.provider_settings:
        raise ValueError("system settings differ from frozen experiment")
    cases = [Case.model_validate(c) for c in read_json(bundle / "inputs.json")]
    case_ids = [case.id for case in cases]
    if len(set(case_ids)) != len(case_ids) or receipt.case_ids != case_ids:
        raise ValueError("case denominator changed or duplicated")
    labels = read_json(bundle / "labels.json")
    if set(labels) != set(case_ids):
        raise ValueError("label denominator differs from cases")
    rows = read_json(outputs)
    if not isinstance(rows, list):
        raise ValueError("outputs must be a list of attempted case results")
    mapped = _outcome_map(rows, set(case_ids))
    results = [
        score_case(
            c,
            Label.model_validate(labels[c.id]),
            mapped.get(c.id, {}),
            bundle,
            protocol["timestamp_tolerance_ms"],
        )
        for c in cases
    ]
    for row in results:
        if row["case_id"] not in mapped:
            row["status"] = "missing"
    return {
        "receipt": receipt.model_dump(),
        "commitments": commitments,
        "scope": "offline_contract" if receipt.mode == "offline_contract" else "live_replay",
        "system_revision": arm["revision"],
        "cases": results,
        "summary": summarize(results),
    }


def _outcome_map(rows: list, case_ids: set[str]) -> dict:
    """Reject extra attempts; retries require their own retained run receipt."""
    mapped = {}
    for row in rows:
        if not isinstance(row, dict) or row.get("case_id") not in case_ids:
            raise ValueError("unassigned outcome outside frozen denominator")
        case_id = row["case_id"]
        if case_id in mapped:
            raise ValueError("duplicate attempt; retain retries in separate run")
        mapped[case_id] = row
    return mapped


def ratio(numerator: int, denominator: int) -> float | None:
    """An undefined measure is unknown, never a perfect score."""
    return numerator / denominator if denominator else None


def summarize(rows: list[dict]) -> dict:
    """Expose separate quality and complete-job resource denominators."""
    counts = Counter(row["status"] for row in rows)

    def total(key):
        return sum(row[key] for row in rows)

    usage = [row["usage"] for row in rows]
    metrics = {
        "cases": len(rows),
        "statuses": dict(sorted(counts.items())),
        "completion": ratio(sum(row["complete"] for row in rows), len(rows)),
        "structural_validity": ratio(total("structural_valid"), len(rows)),
        "fact_recall": ratio(total("facts_correct"), total("facts_expected")),
        "supported_claim_precision": ratio(total("facts_supported"), total("claims")),
        "citation_precision": ratio(total("citations_supported"), total("citations")),
        "citation_recall": ratio(total("facts_supported"), total("facts_expected")),
        "timestamp_recall": ratio(total("temporal_correct"), total("temporal_expected")),
        "timestamp_precision": ratio(total("temporal_correct"), total("temporal_predicted")),
    }
    for key in (
        "latency_ms",
        "calls",
        "auxiliary_calls",
        "cost_usd",
        "input_tokens",
        "output_tokens",
    ):
        observations = [u[key] for u in usage if u is not None and u[key] is not None]
        metrics[key] = sum(observations) if len(observations) == len(rows) else None
        metrics[f"{key}_observed_cases"] = len(observations)
        metrics[f"{key}_observed_total"] = sum(observations) if observations else None
    return metrics
