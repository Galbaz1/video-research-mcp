"""Report lexical markers without publishing Claude messages or tool output."""

from __future__ import annotations

import json
import math
import os
import stat
from pathlib import Path

MAX_BYTES = 16 * 1024 * 1024
SUBTYPES = {"success", "error_during_execution", "error_max_turns",
            "error_max_budget_usd", "error_max_structured_output_retries"}
API_ERRORS = {"authentication_failed", "billing_error", "rate_limit",
              "invalid_request", "server_error", "unknown"}


def summarize(messages: list) -> dict:
    """Select metadata and lexical error markers; never return text or certify causes."""
    results = [m for m in messages if isinstance(m, dict) and m.get("type") == "result"]
    if not results:
        return {"state": "no_result", "message_count": len(messages)}
    result = results[-1]
    errors = result.get("errors", [])
    text = " ".join(v for v in errors if isinstance(v, str)) if isinstance(errors, list) else ""
    if result.get("is_error") is True and isinstance(result.get("result"), str):
        text += " " + result["result"]
    text = text.casefold()
    categories = {label for label, phrases in {
        "authentication": ("invalid api key", "authentication failed", "oauth token", "please run /login"),
        "billing": ("credit balance", "billing error", "insufficient credits"),
        "rate_limit": ("rate limit", "usage limit", "hit your limit"),
        "model": ("model not found", "invalid model", "model is not available"),
        "plugin": ("plugin not found", "unknown slash command", "failed to load plugin"),
    }.items() if any(phrase in text for phrase in phrases)}
    api_errors = sorted({m["error"] for m in messages if isinstance(m, dict)
                         and m.get("type") == "assistant" and isinstance(m.get("error"), str)
                         and m["error"] in API_ERRORS})
    subtype = result.get("subtype")
    summary = {"state": "result", "message_count": len(messages), "result_count": len(results),
               "subtype": subtype if isinstance(subtype, str) and subtype in SUBTYPES else "unknown",
               "is_error": result.get("is_error") if type(result.get("is_error")) is bool else None,
               "lexical_markers": sorted(categories), "api_errors": api_errors,
               "error_count": len(errors) if isinstance(errors, list) else None}
    for name in ("duration_ms", "num_turns", "total_cost_usd"):
        value = result.get(name)
        if type(value) in (int, float) and 0 <= value <= 10**12 and math.isfinite(value):
            summary[name] = value
    return summary


def main() -> None:
    """Read only a bounded regular execution file inside the runner's temp folder."""
    value = os.environ.get("CLAUDE_EXECUTION_FILE", "")
    if not value:
        print(json.dumps({"state": "output_unavailable"}))
        return
    path = Path(value)
    try:
        temporary = Path(os.environ["RUNNER_TEMP"]).resolve()
        if path.is_symlink() or not path.resolve().is_relative_to(temporary):
            raise ValueError("unsafe output")
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as reader:
            metadata = os.fstat(reader.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError("nonregular output")
            body = reader.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            print(json.dumps({"state": "output_too_large"}))
            return
        messages = json.loads(body)
        if not isinstance(messages, list):
            raise ValueError("invalid output shape")
        summary = summarize(messages)
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        summary = {"state": "output_unreadable"}
    print(json.dumps(summary, allow_nan=False, sort_keys=True))


if __name__ == "__main__":
    main()
