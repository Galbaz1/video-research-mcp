"""Paired materiality gates; offline examples never establish live superiority."""

import random

from scripts.evaluation.replay import summarize


def paired_interval(differences: list[int], seed: int, resamples: int) -> list[float]:
    """Deterministic paired bootstrap interval over all attempted cases."""
    rng = random.Random(seed)
    n = len(differences)
    means = sorted(sum(rng.choices(differences, k=n)) / n for _ in range(resamples))
    return [means[int(resamples * 0.025)], means[min(resamples - 1, int(resamples * 0.975))]]


def compare(candidate: dict, baseline: dict, protocol: dict) -> dict:
    """Compare matched run receipts, refusing control drift or exposed labels."""
    for key in (
        "split",
        "inputs_sha256",
        "labels_sha256",
        "protocol_sha256",
        "evaluator_sha256",
        "case_ids",
        "budget",
        "prompt_sha256",
        "source_snapshots_sha256",
        "experiment_sha256",
        "candidate_revision",
        "baseline_revision",
    ):
        if candidate["receipt"][key] != baseline["receipt"][key]:
            raise ValueError(f"unmatched comparison control: {key}")
    base = {row["case_id"]: row for row in baseline["cases"]}
    families = sorted({row["family"] for row in candidate["cases"]})
    results = {}
    for family in families:
        rows = [r for r in candidate["cases"] if r["family"] == family]
        baselines = [base[r["case_id"]] for r in rows]
        results[family] = _family_gate(rows, baselines, protocol)
    coverage = set(families) == set(protocol["families"])
    workflows = sorted({row["workflow"] for row in candidate["cases"]})
    workflow_gates = {
        workflow: _family_gate(
            [r for r in candidate["cases"] if r["workflow"] == workflow],
            [base[r["case_id"]] for r in candidate["cases"] if r["workflow"] == workflow],
            protocol,
        )
        for workflow in workflows
    }
    return {
        "families": results,
        "workflows": workflow_gates,
        "full_family_coverage": coverage,
        "numerical_criteria_passed": coverage and all(r["passed"] for r in workflow_gates.values()),
        "material_advantage": False,
        "independent_acceptance_required": [
            "sealed cohort and candidate identity",
            "strongest capable baseline receipts",
            "all adopted workflow coverage",
            "live resource authority and complete-job usage",
            "source/media human audit",
            "artifact-specific decode/quality validators",
        ],
    }


def _family_gate(rows: list[dict], baseline: list[dict], protocol: dict) -> dict:
    """Require quality, gain, uncertainty and resource bounds independently."""
    candidate_metrics, baseline_metrics = summarize(rows), summarize(baseline)
    differences = [int(c["complete"]) - int(b["complete"]) for c, b in zip(rows, baseline)]
    delta = sum(differences) / len(rows)
    interval = paired_interval(
        differences, protocol["bootstrap_seed"], protocol["bootstrap_resamples"]
    )
    gates = {
        "sample_size": len(rows) >= protocol["minimum_cases_per_family"],
        "completion_gain": delta >= protocol["completion_gain_pp"] / 100,
        "gain_interval": interval[0] > 0,
    }
    for metric in protocol["quality_metrics"]:
        value, reference = candidate_metrics[metric], baseline_metrics[metric]
        gates[metric] = (not sum(r["facts_expected"] for r in rows)) or (
            value is not None
            and reference is not None
            and value >= protocol["quality_floor"]
            and value >= reference - protocol["nonregression_pp"] / 100
        )
    gates["zero_fabricated_support"] = all(r["citations_supported"] == r["citations"] for r in rows)
    if sum(r["temporal_expected"] for r in rows):
        gates["timestamps"] = candidate_metrics["timestamp_recall"] == 1 and (
            candidate_metrics["timestamp_precision"] == 1
        )
    for metric in ("cost_usd", "latency_ms"):
        value, reference = candidate_metrics[metric], baseline_metrics[metric]
        gates[metric] = (
            value is not None
            and reference is not None
            and (value <= reference * protocol["resource_ratio_max"])
        )
    return {
        "candidate": candidate_metrics,
        "baseline": baseline_metrics,
        "completion_delta": delta,
        "completion_delta_ci95": interval,
        "gates": gates,
        "passed": all(gates.values()),
    }
