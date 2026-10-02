"""Structural video checks; timestamps and text length do not verify facts."""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """Aggregated result of all validation checks."""

    passed: bool
    issues: list[str] = field(default_factory=list)


def validate_timestamps(
    timestamps: list[dict], *, duration_seconds: float | None = None
) -> list[str]:
    """Check timestamp ordering and format.

    Returns:
        List of issue strings (empty = all valid).
    """
    issues: list[str] = []
    prev_seconds = -1

    for i, ts in enumerate(timestamps):
        time_str = ts.get("time", "")
        if not isinstance(time_str, str) or not re.fullmatch(r"\d{1,2}:\d{2}(:\d{2})?", time_str):
            issues.append(f"Timestamp {i}: invalid format '{time_str}'")
            continue

        parts = time_str.split(":")
        if any(int(part) >= 60 for part in parts[1:]):
            issues.append(f"Timestamp {i}: invalid clock component '{time_str}'")
            continue
        seconds = sum(int(p) * (60 ** (len(parts) - 1 - j)) for j, p in enumerate(parts))

        if duration_seconds is not None and seconds > duration_seconds:
            issues.append(f"Timestamp {i}: '{time_str}' exceeds measured duration")

        if seconds < prev_seconds:
            issues.append(f"Timestamp {i}: '{time_str}' is out of order (before previous)")
        prev_seconds = seconds

    return issues


def validate_key_points(key_points: list[str], *, min_length: int = 20) -> list[str]:
    """Check that key points have minimum substance.

    Returns:
        List of issue strings for points that are too short.
    """
    issues: list[str] = []
    for i, point in enumerate(key_points):
        if len(point.strip()) < min_length:
            issues.append(
                f"Key point {i}: too short ({len(point.strip())} chars, min {min_length})"
            )
    return issues


def validate_concept_edges(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Check that all edge endpoints reference existing nodes.

    Returns:
        List of issue strings for dangling references.
    """
    node_ids = {n.get("id") for n in nodes}
    issues: list[str] = []

    for i, edge in enumerate(edges):
        if edge.get("source") not in node_ids:
            issues.append(f"Edge {i}: source '{edge.get('source')}' not in nodes")
        if edge.get("target") not in node_ids:
            issues.append(f"Edge {i}: target '{edge.get('target')}' not in nodes")

    return issues


def validate_analysis(
    result: dict,
    *,
    duration_seconds: float | None = None,
) -> ValidationResult:
    """Run structural validations on a video analysis result.

    Args:
        result: Dict with timestamps, key_points, etc.
        duration_seconds: Independently measured duration, when available.

    Returns:
        ValidationResult with passed flag and collected issues.
    """
    issues: list[str] = []

    timestamps = result.get("timestamps", [])
    if isinstance(timestamps, list):
        ts_dicts = [
            t if isinstance(t, dict) else t.model_dump() if hasattr(t, "model_dump") else {}
            for t in timestamps
        ]
        issues.extend(validate_timestamps(ts_dicts, duration_seconds=duration_seconds))

    key_points = result.get("key_points", [])
    if isinstance(key_points, list):
        issues.extend(validate_key_points(key_points))

    return ValidationResult(passed=len(issues) == 0, issues=issues)
