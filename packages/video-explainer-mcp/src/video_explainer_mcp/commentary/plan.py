"""Validate a source-linked commentary plan before any shard is frozen.

Checks run in one pass so every error is reported: plan/source binding, sequential
segment IDs, narration parity with the script, fenced evidence files, source-cut
ceilings and explicit audio decisions. Text quality and meaning are not judged.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from .store import PLAN_SCHEMA, inside, read_bytes, read_record, revision

NOTES = "plan/watch_notes"
AUDIO_MODES = {"ducked_bed", "muted"}
BGM_MODES = {"none", "licensed"}
MAX_SEGMENTS = 2000


def _interval(value, ceiling: float) -> str | None:
    if not (isinstance(value, list) and len(value) == 2
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in value)):
        return "visual_plan.rough_interval_sec must be [start, end]"
    if value[0] < 0 or value[1] <= value[0]:
        return "visual_plan.rough_interval_sec must be ordered and non-negative"
    if value[1] > ceiling:
        return "visual_plan.rough_interval_sec exceeds source_cut_max_sec"
    return None


def _evidence(root: Path, refs, evidence: dict) -> list[str]:
    if not isinstance(refs, list) or not 1 <= len(refs) <= 16:
        return ["visual_plan.movie_locator.evidence_refs needs 1-16 entries"]
    errors = []
    for ref in refs:
        path = inside(root, str(ref), NOTES) if isinstance(ref, str) else None
        if path is None:
            errors.append(f"unsafe evidence ref: {ref}")
        elif not path.is_file():
            errors.append(f"evidence does not exist: {ref}")
        else:
            evidence[ref] = revision(path)["sha256"]
    return errors


def _segment(index: int, segment, root: Path, facts: dict, evidence: dict) -> tuple[list[str], str | None]:
    expected = f"SEG_{index + 1:04d}"
    if not isinstance(segment, dict):
        return [f"segments[{index}] must be an object"], None
    errors = [] if segment.get("segment_id") == expected else [f"segment_id must be {expected}"]
    narration = segment.get("narration")
    text = narration.get("text") if isinstance(narration, dict) else None
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        errors.append("narration.text is required (1-4000 characters)")
        text = None
    visual = segment.get("visual_plan") if isinstance(segment.get("visual_plan"), dict) else {}
    if problem := _interval(visual.get("rough_interval_sec"), facts["source_cut_max_sec"]):
        errors.append(problem)
    locator = visual.get("movie_locator") if isinstance(visual.get("movie_locator"), dict) else {}
    errors += _evidence(root, locator.get("evidence_refs"), evidence)
    audio = segment.get("audio_plan") if isinstance(segment.get("audio_plan"), dict) else {}
    if audio.get("source_audio_mode") not in AUDIO_MODES:
        errors.append("audio_plan.source_audio_mode must be ducked_bed or muted")
    if audio.get("bgm_mode", "none") not in BGM_MODES:
        errors.append("audio_plan.bgm_mode must be none or licensed")
    elif audio.get("bgm_mode") == "licensed" and not facts.get("bgm_manifest"):
        errors.append("licensed BGM requires a bgm_manifest in execution facts")
    return [f"{expected}: {e}" for e in errors], text and text.strip()


def _script_errors(path: Path, narration: list[tuple[str, str]]) -> list[str]:
    """Match ordered script blocks to their own plan segment and verbatim narration."""
    try:
        script = read_bytes(path).decode("utf-8")
    except (OSError, ValueError) as error:
        return [f"plan/narration_script.md unreadable: {error}"]
    headers = list(re.finditer(r"(?m)^[ \t]*(?:#{1,6}[ \t]+)?(SEG_[0-9]{4})[ \t]*$", script))
    errors = []
    if [h[1] for h in headers] != [sid for sid, _ in narration]:
        errors.append("narration_script.md segment IDs must match the plan exactly and in order")
    blocks = [script[h.end():headers[i + 1].start() if i + 1 < len(headers) else len(script)].strip()
              for i, h in enumerate(headers)]
    errors += [f"{sid}: narration_script.md does not preserve the narration verbatim"
               for i, (sid, text) in enumerate(narration) if i >= len(blocks) or blocks[i] != text]
    return errors


def validate_plan(root: Path, manifest: dict) -> dict:
    """Return all plan errors and the digests a freeze would bind."""
    errors, evidence, narration = [], {}, []
    facts = read_record(root / "plan/execution_facts.json")
    if revision(root / "plan/execution_facts.json")["sha256"] != manifest["facts_sha256"]:
        errors.append("execution facts changed since project creation")
    plan_path, script_path = root / "plan/editing_plan.json", root / "plan/narration_script.md"
    try:
        plan = read_record(plan_path)
    except (OSError, ValueError) as error:
        return {"valid": False, "errors": [f"plan/editing_plan.json unreadable: {error}"], "segment_count": 0}
    if plan.get("schema") != PLAN_SCHEMA:
        errors.append(f"plan schema must be {PLAN_SCHEMA}")
    if plan.get("source_sha256") != manifest["source"]["sha256"]:
        errors.append("plan source_sha256 differs from the project source")
    segments = plan.get("segments")
    if not isinstance(segments, list) or not 1 <= len(segments) <= MAX_SEGMENTS:
        errors.append(f"segments must be a list of 1-{MAX_SEGMENTS} entries")
        segments = []
    for index, segment in enumerate(segments):
        problems, text = _segment(index, segment, root, facts, evidence)
        errors += problems
        if text:
            narration.append((f"SEG_{index + 1:04d}", text))
    errors += _script_errors(script_path, narration)
    result = {"valid": not errors, "errors": errors, "segment_count": len(segments)}
    if not errors:
        result.update(plan_sha256=revision(plan_path)["sha256"], script_sha256=revision(script_path)["sha256"],
                      facts_sha256=manifest["facts_sha256"], evidence=evidence)
    return result
