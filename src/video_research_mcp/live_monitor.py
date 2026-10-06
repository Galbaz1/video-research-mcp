"""Finite replay monitoring with literal conditions and a single monotonic deadline."""

import time

from .live_replay import load, page
from .models.live import LiveResult, MonitorRequest, ReadRequest


def monitor(request: MonitorRequest) -> dict:
    """Consume bounded pages once and preserve unmet conditions and original cursors."""
    started = time.monotonic()
    deadline = started + request.deadline_seconds
    archive = load(request.pin)
    cursor, checks, matches = request.cursor, 0, []
    reason = "max_checks"
    while checks < request.max_checks:
        if time.monotonic() >= deadline:
            reason = "deadline"
            break
        result = page(ReadRequest(pin=request.pin, cursor=cursor, limit=request.limit), archive)
        if time.monotonic() >= deadline:
            reason = "deadline"
            break
        checks += 1
        cursor = result["next_cursor"]
        matches.extend(e for e in result["events"]
                       if e["kind"] == request.kind and request.contains in e["text"])
        if len(matches) >= request.min_matches:
            reason = "condition_met"
            break
        if not result["has_more"]:
            reason = "end_of_replay"
            break
    return LiveResult(operation="monitor", status="condition_met" if reason == "condition_met" else "condition_unmet",
                      data={"reason": reason, "checks": checks, "max_checks": request.max_checks,
                            "deadline_seconds": request.deadline_seconds, "next_cursor": cursor,
                            "matches": matches, "condition": {"kind": request.kind, "contains": request.contains,
                                                               "min_matches": request.min_matches},
                            "queue": archive["request"]["queue"]}).model_dump()
