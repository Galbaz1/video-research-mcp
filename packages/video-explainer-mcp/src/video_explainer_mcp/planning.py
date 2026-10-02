"""Durable per-project plan CAS and a shared production critical section."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import stat

from .models.planning import PlanRequest, VideoPlan
from .planning_sources import (
    canonical, digest, packet_inputs, project_directory, selected_evidence, validate_plan,
)


@contextmanager
def plan_transaction(project: Path, *, create: bool = False):
    """Fail fast on concurrent writes; keep admission held across CLI awaits."""
    path = project / "planning.sqlite3"
    for suffix in ("", "-journal", "-wal", "-shm"):
        candidate = project / ("planning.sqlite3" + suffix)
        if candidate.is_symlink():
            raise ValueError("Plan database and sidecars must not be symlinks")
    if not path.exists() and not create:
        yield None, None
        return
    if path.exists() and (not stat.S_ISREG(path.stat().st_mode) or path.stat().st_size > 8 * 1024 * 1024):
        raise ValueError("Plan database must be a regular project file of at most 8 MiB")
    connection = sqlite3.connect(path, timeout=0, isolation_level=None)
    try:
        page_size = connection.execute("PRAGMA page_size").fetchone()[0]
        connection.execute(f"PRAGMA max_page_count={8 * 1024 * 1024 // page_size}")
        try:
            connection.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as error:
            raise ValueError("Plan is busy with another revision or production operation") from error
        connection.execute("CREATE TABLE IF NOT EXISTS plan (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)")
        row = connection.execute("SELECT payload FROM plan WHERE id=1").fetchone()
        yield connection, json.loads(row[0]) if row else None
        connection.commit()
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()
        path.chmod(0o600)


def save_plan(connection: sqlite3.Connection, state: dict) -> None:
    """Persist the complete state inside the caller's admitted transaction."""
    encoded = canonical(state)
    if len(encoded.encode()) > 2 * 1024 * 1024:
        raise ValueError("Durable plan state exceeds 2 MiB allowance")
    connection.execute("INSERT INTO plan(id,payload) VALUES(1,?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                       (encoded,))


def require_approved(project: Path, state: dict) -> dict:
    """Check current approval and original commitments before producing artifacts."""
    if state["approval_revision"] != state["revision"]:
        raise ValueError("Approve the current plan revision before production")
    packet, report, commitment = packet_inputs(project)
    if commitment != state["source_commitment_sha256"]:
        raise ValueError("Sources or claims changed; revise and approve the plan again")
    plan = VideoPlan.model_validate(state["plan"])
    if digest(plan.model_dump()) != state["plan_sha256"]:
        raise ValueError("Stored plan commitment differs from its content")
    validate_plan(plan, packet, report, approving=True)
    return packet


def public_plan(project_id: str, project: Path, state: dict) -> dict:
    """Inspect current source and artifact bindings without changing approval."""
    from .plan_artifacts import inspect_bindings

    result = {"project_id": project_id, **state, "factual_success": False,
              "approval_role": "editorial", "semantic_support": "not_verified"}
    try:
        _, _, commitment = packet_inputs(project)
        result["sources_current"] = commitment == state["source_commitment_sha256"]
    except (OSError, ValueError) as error:
        result.update(sources_current=False, source_error=str(error))
    result["bindings"] = inspect_bindings(project, state)
    approved = state["approval_revision"] == state["revision"]
    result["status"] = "approved" if approved and result["sources_current"] else "draft"
    if approved and not result["sources_current"]:
        result.update(status="stale", approval_revision=None)
    return result


def apply_plan(project_id: str, request: PlanRequest) -> dict:
    """Create/show/revise/approve with exact revision and source population checks."""
    project = project_directory(project_id)
    with plan_transaction(project, create=request.action == "create") as (connection, state):
        if request.action == "show":
            if state is None:
                raise FileNotFoundError("No managed video plan exists")
            return public_plan(project_id, project, state)
        revision = state["revision"] if state else 0
        if request.expected_revision != revision:
            raise ValueError(f"Plan revision conflict: expected {request.expected_revision}, current {revision}")
        if request.action == "create" and state is not None:
            raise ValueError("Plan already exists; use revise with its current revision")
        if request.action == "create" and (project / "plan/plan.json").exists():
            raise ValueError("Existing unmanaged plan must be preserved or removed before creating a managed plan")
        if request.action != "create" and state is None:
            raise FileNotFoundError("Create a plan before revising or approving it")
        packet, report, commitment = packet_inputs(project)
        now = datetime.now(timezone.utc).isoformat()
        if request.action in {"create", "revise"}:
            validate_plan(request.plan, packet, report, approving=False)
            state = {"revision": revision + 1, "approval_revision": None,
                     "created_at": state["created_at"] if state else now, "approved_at": None,
                     "plan": request.plan.model_dump(), "plan_sha256": digest(request.plan.model_dump()),
                     "source_commitment_sha256": commitment, "bindings": {},
                     "evidence_refs": selected_evidence(request.plan, packet)}
        else:
            if commitment != state["source_commitment_sha256"]:
                raise ValueError("Sources or claims changed; revise before approving")
            validate_plan(VideoPlan.model_validate(state["plan"]), packet, report, approving=True)
            state = {**state, "approval_revision": revision, "approved_at": now}
        save_plan(connection, state)
        return public_plan(project_id, project, state)
