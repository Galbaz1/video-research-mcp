"""Durable revision-bound feedback lifecycle and probe-gated refinement.

Feedback rows live in the project's existing ``planning.sqlite3`` and are written inside
the same fail-fast plan transaction as plan revisions. Processing is either a local typed
scene patch that creates the next plan revision through the existing plan validation, or
a CLI refine phase that the configured CLI's own help output actually lists.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from .config import get_config
from .file_io import open_regular
from .models.planning import VideoPlan
from .models.refinement import FeedbackRequest, FeedbackResult, FrameRef
from .planning import plan_transaction, save_plan
from .planning_production import produce, production_transaction
from .planning_sources import canonical, digest, packet_inputs, project_directory, selected_evidence, validate_plan
from .runner import run_cli

MAX_FEEDBACK = 200
MAX_RENDER_BYTES = 2 * 1024 * 1024 * 1024
PHASE_CHOICES = re.compile(r"--phase\s+\{([^}]*)\}")
FLAG = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def probe_capabilities() -> dict:
    """Read the configured CLI's refine help; unavailable or unparsed output supports nothing."""
    try:
        result = await run_cli("refine", "--help", timeout=30)
    except Exception as error:
        return {"status": "unavailable", "error": f"{type(error).__name__}: {error}", "phases": [], "flags": []}
    choices = PHASE_CHOICES.search(result.stdout)
    phases = sorted({p.strip() for p in choices.group(1).split(",") if p.strip()}) if choices else []
    return {"status": "probed" if phases else "unparsed", "command": result.command, "exit": result.returncode,
            "help_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(), "phases": phases,
            "flags": sorted(set(FLAG.findall(result.stdout)))}


def require_phase(phase: str | None, capabilities: dict) -> None:
    """Refuse before any refinement call unless the probe listed the exact phase."""
    if capabilities["status"] != "probed" or phase not in capabilities["phases"]:
        raise ValueError(f"Refinement phase {phase!r} is not supported by the probed CLI "
                         f"(probe {capabilities['status']}, phases {capabilities['phases']}); refused before spend")


def _rows(connection) -> dict:
    connection.execute("CREATE TABLE IF NOT EXISTS refinement_feedback (id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
    return {row[0]: json.loads(row[1]) for row in connection.execute("SELECT id, payload FROM refinement_feedback ORDER BY id")}


def _save(connection, record: dict) -> None:
    connection.execute("INSERT INTO refinement_feedback(id,payload) VALUES(?,?) "
                       "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (record["id"], canonical(record)))


def _file_sha256(path: Path) -> str:
    digest_, consumed = hashlib.sha256(), 0
    with open_regular(path) as (stream, _):
        while chunk := stream.read(1024 * 1024):
            consumed += len(chunk)
            if consumed > MAX_RENDER_BYTES:
                raise ValueError("Referenced render exceeds byte ceiling")
            digest_.update(chunk)
    return digest_.hexdigest()


def _frame(project: Path, frame: FrameRef) -> dict:
    """Bind a visual finding to exact current render bytes; unseen or changed output is refused."""
    path = (project / frame.render_path).resolve()
    path.relative_to(project)
    if _file_sha256(path) != frame.render_sha256:
        raise ValueError("Referenced render bytes differ from render_sha256; no finding binds to unseen output")
    return {**frame.model_dump(), "frame_time_within_duration": "UNKNOWN (no media probe here)"}


def _target(project: Path, state: dict, scene_index: int, frame: FrameRef | None) -> dict:
    """Exact plan revision, scene digest, bound artifacts and optional frame the feedback addresses."""
    scenes = state["plan"]["scenes"]
    if scene_index >= len(scenes):
        raise ValueError("scene_index is outside the current plan")
    target = {"plan_revision": state["revision"], "plan_sha256": state["plan_sha256"],
              "approval_revision": state["approval_revision"], "scene_index": scene_index,
              "scene_sha256": digest(scenes[scene_index]),
              "bindings": {kind: binding["sha256"] for kind, binding in state["bindings"].items()}}
    if frame is not None:
        target["frame"] = _frame(project, frame)
    return target


def _require_revision(state: dict, expected: int) -> None:
    if expected != state["revision"]:
        raise ValueError(f"Plan revision conflict: expected {expected}, current {state['revision']}")


def add(project: Path, connection, state: dict, request: FeedbackRequest, probe: dict | None) -> dict:
    """Store open feedback bound to the current revision; findings stay asserted, unverified."""
    _require_revision(state, request.expected_revision)
    rows = _rows(connection)
    if len(rows) >= MAX_FEEDBACK:
        raise ValueError("Feedback store reached its 200-item ceiling")
    record = {"id": f"fb-{len(rows) + 1:04d}", "kind": request.kind, "text": request.text,
              "findings": [finding.model_dump() | {"verified": False} for finding in request.findings],
              "processor": request.processor, "phase": request.phase,
              "patch": request.patch.model_dump() if request.patch else None,
              "capability_probe_sha256": probe["help_sha256"] if probe else None,
              "target": _target(project, state, request.scene_index, request.frame),
              "status": "open", "max_rounds": request.max_rounds, "attempts": [], "rebinds": [], "created_at": _now()}
    _save(connection, record)
    return record


def _claim(project: Path, rows: dict, state: dict, request: FeedbackRequest) -> dict:
    """Check status and round cap before any processing; retry rebinds to the current revision."""
    record = rows.get(request.feedback_id)
    if record is None:
        raise FileNotFoundError(f"Feedback not found: {request.feedback_id}")
    if record["processor"] != request.processor:
        raise ValueError(f"Feedback uses processor {record['processor']}")
    if len(record["attempts"]) >= record["max_rounds"]:
        raise ValueError("Refinement round cap reached; nothing processed")
    if request.action == "retry":
        if record["status"] not in {"failed", "stale"}:
            raise ValueError("Only failed or stale feedback can be retried")
        _require_revision(state, request.expected_revision)
        frame = record["target"].get("frame")
        frame = FrameRef.model_validate({k: frame[k] for k in FrameRef.model_fields}) if frame else None
        record["rebinds"].append(record["target"])
        record["target"] = _target(project, state, record["target"]["scene_index"], frame)
    elif record["status"] != "open":
        raise ValueError(f"Feedback is {record['status']}; use retry")
    return record


def _record(connection, record: dict, processor: str, outcome: dict) -> dict:
    """Every processed round is durable, including stale and failed outcomes."""
    record["attempts"].append({"round": len(record["attempts"]) + 1, "processor": processor, "at": _now(), **outcome})
    record["status"] = {"applied": "applied", "stale_target": "stale"}.get(outcome["status"], "failed")
    _save(connection, record)
    return record


def _stale(project: Path, record: dict, state: dict) -> dict | None:
    target = record["target"]
    stale = {"status": "stale_target", "target_revision": target["plan_revision"], "current_revision": state["revision"]}
    current = {"plan_revision": state["revision"], "plan_sha256": state["plan_sha256"],
               "approval_revision": state["approval_revision"],
               "bindings": {kind: binding["sha256"] for kind, binding in state["bindings"].items()}}
    if any(target[key] != value for key, value in current.items()):
        return stale
    if frame := target.get("frame"):
        try:
            _frame(project, FrameRef.model_validate({key: frame[key] for key in FrameRef.model_fields}))
        except (OSError, ValueError) as error:
            return {**stale, "error": str(error)}
    return None


def _patch(project: Path, connection, state: dict, record: dict) -> dict:
    """Apply one typed scene edit as the next draft revision; sources and other scenes stay intact."""
    packet, report, commitment = packet_inputs(project)
    if commitment != state["source_commitment_sha256"]:
        raise ValueError("Original sources or claims changed; refinement never rewrites sources")
    plan, patch, index = json.loads(json.dumps(state["plan"])), record["patch"], record["target"]["scene_index"]
    if plan["scenes"][index][patch["field"]] != patch["expected"]:
        raise ValueError("Scene field differs from the patch's expected value")
    plan["scenes"][index][patch["field"]] = patch["value"]
    revised = VideoPlan.model_validate(plan)
    validate_plan(revised, packet, report, approving=False)
    before = [digest(scene) for scene in state["plan"]["scenes"]]
    after = [digest(scene.model_dump()) for scene in revised.scenes]
    changed = [i for i, (old, new) in enumerate(zip(before, after, strict=True)) if old != new]
    save_plan(connection, {**state, "revision": state["revision"] + 1, "approval_revision": None, "approved_at": None,
                           "plan": revised.model_dump(), "plan_sha256": digest(revised.model_dump()), "bindings": {},
                           "evidence_refs": selected_evidence(revised, packet)})
    return {"status": "applied", "from_revision": state["revision"], "to_revision": state["revision"] + 1,
            "plan_sha256": digest(revised.model_dump()), "affected_scene_indices": changed,
            "unaffected_scene_indices": [i for i in range(len(after)) if i not in changed],
            "recheck": [{"scene_index": i, "sha256_before": before[i], "sha256_after": after[i]} for i in changed],
            "bindings_to_rebind": sorted(state["bindings"]), "source_commitment_sha256": commitment,
            "sources_preserved": True, "approval": "cleared; approve the new revision before production"}


def apply_local(project: Path, connection, state: dict, request: FeedbackRequest) -> dict:
    """Process one round of a typed local patch under the existing plan revision guard."""
    record = _claim(project, _rows(connection), state, request)
    outcome = _stale(project, record, state)
    if outcome is None:
        try:
            outcome = _patch(project, connection, state, record)
        except (OSError, ValueError) as error:
            outcome = {"status": "failed", "error": str(error)}
    return _record(connection, record, "local_patch", outcome)


async def apply_cli(project_id: str, request: FeedbackRequest, capabilities: dict) -> tuple[dict, int]:
    """Run only a probed 'script' phase through the existing approved-plan producer."""
    with production_transaction(project_id) as (project, connection, state):
        if state is None:
            raise FileNotFoundError("Feedback requires a managed video plan")
        record = _claim(project, _rows(connection), state, request)
        require_phase(record["phase"], capabilities)
        if record["phase"] != "script":
            raise ValueError("Only the script phase has a managed artifact binding; refused before spend")
        outcome = _stale(project, record, state)
        if outcome is None:
            argv = ["refine", project_id, "--phase", "script"]
            if "--projects-dir" in capabilities["flags"]:
                argv += ["--projects-dir", str(get_config().resolved_projects_path)]
            before = {kind: binding["sha256"] for kind, binding in state["bindings"].items()}
            try:
                result = await produce(project, connection, state, argv, run_cli)
                outcome = {"status": "applied", "command": result.command, "exit": result.returncode,
                           "stdout_sha256": hashlib.sha256(result.stdout.encode()).hexdigest(),
                           "changed_bindings": sorted(k for k, b in state["bindings"].items() if before.get(k) != b["sha256"]),
                           "refinement_quality": "UNKNOWN: a CLI exit is not a quality judgment"}
            except asyncio.CancelledError as cancellation:
                try:
                    _record(connection, record, "cli_phase", {"status": "cancelled_unknown", "command": argv})
                    connection.commit()
                except Exception as error:
                    cancellation.add_note(f"Refinement attempt persistence liability: {type(error).__name__}: {error}")
                raise
            except Exception as error:
                outcome = {"status": "failed", "error": f"{type(error).__name__}: {error}"}
        return _record(connection, record, "cli_phase", outcome), state["revision"]


async def manage_feedback(project_id: str, request: FeedbackRequest) -> dict:
    """Dispatch capabilities/add/show/apply/retry; probe-gated phases refuse before the transaction."""
    result = FeedbackResult(project_id=project_id, action=request.action)
    probe = await probe_capabilities() if request.action == "capabilities" or request.processor == "cli_phase" else None
    if request.action == "capabilities":
        return result.model_copy(update={"capabilities": probe}).model_dump()
    if request.action == "add" and probe is not None:
        require_phase(request.phase, probe)
    if request.action in {"apply", "retry"} and probe is not None:
        record, revision = await apply_cli(project_id, request, probe)
        return result.model_copy(update={"feedback": record, "plan_revision": revision, "capabilities": probe}).model_dump()
    project = project_directory(project_id)
    with plan_transaction(project) as (connection, state):
        if state is None:
            raise FileNotFoundError("Feedback requires a managed video plan; create one with explainer_plan")
        if request.action == "show":
            rows = _rows(connection)
            if request.feedback_id and request.feedback_id not in rows:
                raise FileNotFoundError(f"Feedback not found: {request.feedback_id}")
            items = [rows[request.feedback_id]] if request.feedback_id else list(rows.values())
            return result.model_copy(update={"feedback_items": items, "plan_revision": state["revision"]}).model_dump()
        record = add(project, connection, state, request, probe) if request.action == "add" else apply_local(project, connection, state, request)
        revision = record["attempts"][-1].get("to_revision", state["revision"]) if record["attempts"] else state["revision"]
        return result.model_copy(update={"feedback": record, "plan_revision": revision}).model_dump()
