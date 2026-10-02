"""Run the current analysis caller inside an explicit request budget."""

from __future__ import annotations

from ..errors import make_tool_error
from ..execution_budget import ExecutionBudget
from ..models.execution import ExecutionLimits
from .video_core import analyze_video
from .video_plan import bounded_contents


def cache_bypass_effects(uses_file_api: bool) -> dict:
    """Declare cache effects that can remain during ordinary source preparation."""
    return {
        "result": "bypassed",
        "identity_registry": "bypassed",
        "context_prewarm": "bypassed",
        "upload_cache": "checked_or_populated_by_file_api_preparation"
        if uses_file_api
        else "not_used",
    }


async def execute_bounded_video(
    plan: dict,
    limits: ExecutionLimits,
    instruction: str,
    output_schema: dict | None,
    thinking_level: str,
) -> dict:
    """Return full evidence plus reconciled usage, including failures and unknowns."""
    budget = ExecutionBudget(limits)
    try:
        contents = bounded_contents(plan, instruction, limits)
        source = plan["remote_payloads"][0]["source"]
        local = source["kind"] == "local_file"
        with budget.activate():
            result = await analyze_video(
                contents,
                instruction=instruction,
                content_id=source["sha256"] if local else source["uri"],
                source_label=source["path"] if local else source["uri"],
                output_schema=output_schema,
                thinking_level=thinking_level,
                use_cache=False,
                local_filepath=source["path"] if local else "",
            )
        if budget.violation:
            raise ValueError(
                "Provider exceeded reserved tokens; further budgeted execution is blocked"
            )
    except Exception as exc:
        result = make_tool_error(exc)
    result["execution_usage"] = budget.report()
    result["cache_effects"] = cache_bypass_effects(False)
    return result
