"""Bounded nearby decoded-frame/crop observations for weakly supported claims.

Frames come from the existing native ``frame_at`` route, so every retained
observation carries its source snapshot identity, display-coordinate crop and an
actual time derived from the decoded PTS. Requested times are never reported as
observed. No model interprets the frames here.
"""

import asyncio
from pathlib import Path

from .config import get_config
from .errors import make_tool_error
from .media_frames import frame_at
from .native_media_results import _discard_views
from .models.grounding import EscalationAttempt, EscalationReport

EPSILON = 1e-9


def _plan(targets: list[tuple[str, dict]]) -> list[tuple[str, dict, float]]:
    """Cited start, midpoint and end per weak claim, in claim order without duplicates."""
    plan = []
    for claim_id, citation in targets:
        start, end = citation["start_seconds"], citation["end_seconds"]
        for point in dict.fromkeys((start, (start + end) / 2, end)):
            plan.append((claim_id, citation, point))
    return plan


def _observed(number: int, claim_id: str, citation: dict, point: float, metadata: dict) -> EscalationAttempt:
    frame = metadata["frames"][0]
    actual = frame["actual_seconds"]
    within = citation["start_seconds"] - EPSILON <= actual <= citation["end_seconds"] + EPSILON
    return EscalationAttempt(
        attempt=number, claim_id=claim_id, observation_id=citation["observation_id"],
        status="observed", requested_seconds=point, actual_seconds=actual,
        original_pts=frame["original_pts"], time_base=frame["time_base"], within_cited_span=within,
        crop_box=frame["crop_box"],
        source={k: metadata["source"][k] for k in ("path", "sha256", "bytes")},
        artifact={k: frame[k] for k in ("path", "sha256", "bytes", "width", "height")})


async def _run(spec, plan, report: EscalationReport, base: Path, inflight: list) -> None:
    budget = spec.budget
    reservation = 4 * spec.max_pixels + 65536
    for claim_id, citation, point in plan:
        if len(report.attempts) == budget.max_attempts:
            report.stop_reason = "attempt_limit"
            return
        if report.bytes_used + reservation > budget.max_bytes:
            report.stop_reason = "byte_budget"
            return
        number = len(report.attempts) + 1
        inflight[:] = [number, claim_id, citation["observation_id"], point]
        try:
            metadata = await frame_at(spec.file_path, time_seconds=point, max_pixels=spec.max_pixels,
                                      crop_box=spec.crop_box,
                                      expected_source_sha256=spec.expected_source_sha256)
        except Exception as exc:
            report.attempts.append(EscalationAttempt(
                attempt=number, claim_id=claim_id, observation_id=citation["observation_id"],
                status="failed", requested_seconds=point, error=make_tool_error(exc)))
            inflight.clear()
            continue
        inflight.clear()
        attempt = _observed(number, claim_id, citation, point, metadata)
        if report.bytes_used + attempt.artifact["bytes"] > budget.max_bytes:
            discarded = attempt.model_copy(update={"status": "discarded_byte_budget", "artifact": None})
            report.attempts.append(discarded)
            report.stop_reason = "byte_budget"
            try:
                _discard_views([metadata], base)
            except OSError as error:
                discarded.cleanup_error = make_tool_error(error) | {"artifact": attempt.artifact}
            return
        report.bytes_used += attempt.artifact["bytes"]
        report.attempts.append(attempt)


async def escalate(spec, targets: list[tuple[str, dict]]) -> EscalationReport:
    """Observe nearby frames only for citations bound to the declared source revision."""
    budget = spec.budget
    report = EscalationReport(status="complete", limits={
        **budget.model_dump(), "max_pixels": spec.max_pixels,
        "per_attempt_reservation_bytes": 4 * spec.max_pixels + 65536})
    bound = []
    for claim_id, citation in targets:
        if citation["media_digest"] != spec.expected_source_sha256:
            report.refusals.append({"claim_id": claim_id, "observation_id": citation["observation_id"],
                                    "reason": "source_digest_differs_from_cited_observation"})
        else:
            bound.append((claim_id, citation))
    if not bound:
        report.status = "refused"
        return report
    base = Path(get_config().cache_dir).expanduser().resolve() / "media" / "views"
    inflight = []
    try:
        async with asyncio.timeout(budget.deadline_seconds):
            await _run(spec, _plan(bound), report, base, inflight)
    except TimeoutError as exc:
        report.stop_reason = "deadline"
        if inflight:
            number, claim_id, observation_id, point = inflight
            report.attempts.append(EscalationAttempt(
                attempt=number, claim_id=claim_id, observation_id=observation_id, status="failed",
                requested_seconds=point, error=make_tool_error(exc)))
    if report.stop_reason:
        report.status = "stopped"
    return report
