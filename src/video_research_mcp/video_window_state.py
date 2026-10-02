"""Pure window usage reconciliation and ordered outcome/checkpoint projections."""

COUNTERS = (
    "provider_calls",
    "reserved_or_reconciled_tokens",
    "output_tokens",
    "requested_frames",
    "requested_windows",
)


def run_usage(items, job_id):
    """Sum actual reconciliations or conservative reservations within one run."""
    usage = dict.fromkeys(COUNTERS, 0)
    for item in items:
        report = item.get("execution_usage")
        if not report or item.get("run_job_id") != job_id:
            continue
        for key in COUNTERS:
            if key != "output_tokens":
                usage[key] += report[key]
        for call in report["calls"]:
            if call["kind"] == "generate_content":
                measured = call.get("usage") or {}
                output = measured.get("candidates_token_count")
                thoughts = measured.get("thoughts_token_count", 0)
                usage["output_tokens"] += (
                    output + thoughts
                    if type(output) is int
                    and output >= 0
                    and type(thoughts) is int
                    and thoughts >= 0
                    else report["limits"]["max_output_tokens"]
                )
    return usage


def response_status(result: dict, report: dict) -> str:
    """Keep refusal, truncation and missing generation telemetry nonterminal."""
    if (
        report["provider_exceeded_reservation"]
        or report["generation_truncated"]
        or "error" in result
    ):
        return "failed"
    generation = [call for call in report["calls"] if call["kind"] == "generate_content"]
    if any(
        reason not in {"STOP", None}
        for call in generation
        for reason in call.get("finish_reasons", [])
    ):
        return "refused"
    if not report["usage_complete"] or any(
        "STOP" not in call.get("finish_reasons", [])
        or type((call.get("usage") or {}).get("candidates_token_count")) is not int
        for call in generation
    ):
        return "unknown"
    return "completed"


def failure_status(error: Exception, calls: list[dict]) -> str:
    """Separate unsent budget stops from ambiguous dispatched generation failures."""
    generation = [call for call in calls if call["kind"] == "generate_content"]
    if not generation and str(error).startswith("Execution budget exhausted"):
        return "queued"
    return (
        "unknown"
        if any(call["status"] == "failed_usage_unknown" for call in generation)
        else "failed"
    )


def stopped_run(state: dict, job_id: str) -> dict:
    """Report this stopped caller's telemetry without replacing a newer owner's evidence."""
    items = [item for item in state["windows"] if item.get("run_job_id") == job_id]
    return {
        "reason": "ownership_lost",
        "telemetry_scope": "stopped_caller_only; canonical row retained unchanged",
        **run_usage(items, job_id),
        "window": items[-1] if items else None,
    }


def summarize_run(job, state, status, reason):
    """Retain every requested window, separating success from unknown or remaining work."""
    items, plan = state["windows"], job["request"]["plan"]
    usage = run_usage(items, job["job_id"])
    remaining = [i["index"] for i in items if i["status"] == "queued"]
    unresolved = [i["index"] for i in items if i["status"] not in {"completed", "queued"}]
    return {
        **state,
        "status": status,
        "stop_reason": reason,
        "source": plan["source"],
        "runtime": plan["runtime"],
        "schema_sha256": plan["schema_sha256"],
        "plan_sha256": plan["plan_sha256"],
        "fps": plan["fps"],
        "total_windows": len(items),
        "successful_windows": sum(i["status"] == "completed" for i in items),
        "covered_windows": [i["index"] for i in items if i["status"] == "completed"],
        "unknown_windows": [i["index"] for i in items if i["status"] == "unknown"],
        "remaining_windows": remaining,
        "unresolved_windows": unresolved,
        "continuation_token": job["job_id"]
        if status == "partial" and reason == "budget_exhausted" and remaining and not unresolved
        else None,
        "run_usage": usage,
        "execution_usage": {key: state["previous_usage"][key] + usage[key] for key in COUNTERS},
        "run_limits": job["request"]["limits"],
        "generation_budget_scope": plan["preparation"]["generation_budget_scope"],
        "unobserved_submissions": [
            i["index"] for i in items if i["status"] == "unknown" and not i.get("execution_usage")
        ],
        "usage_complete": not unresolved
        and all(
            i.get("execution_usage", {}).get("usage_complete", False)
            for i in items
            if i["status"] == "completed"
        ),
        "counter_method": "observed or conservatively reserved; unreported interrupted submissions make numeric counters lower bounds",
        "timestamp_origin": plan["timestamp_origin"],
        "observed_coverage": "unknown",
        "cost_usd": None,
        "charge_bound_verified": False,
    }
