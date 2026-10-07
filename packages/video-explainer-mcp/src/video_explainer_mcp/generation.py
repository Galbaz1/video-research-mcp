"""Selected DashScope lifecycle with durable intent and no automatic resubmission.

Lifecycle requirements were informed by MoneyPrinterTurbo at
44e6d5e11832beccc2c3ce6b139bf437e920bb6a (MIT); no foreign provider wire is reused.
"""

import asyncio
import base64
import hashlib
import json
from pathlib import Path
import re
import time
from uuid import uuid4

from .generation_assets import MAX_ASSET_BYTES, acquire_asset, executable_identity, qualify_asset, request_bytes
from .generation_request import contract_for, adapter_revisions, freeze_request, provider_payload, read_operator_quote, selected_config, verify_sources
from .generation_optional import MODES, verify_public_references
from .job_store import JobStore
from .models.generation import GenerationOperation, GenerationRequest, GenerationResult, TaskResponse
from .planning_sources import digest, project_directory
from .render_artifacts import verify_output

KIND = "dashscope_generation"


def _store() -> JobStore:
    """Bound this caller's controller readback before any remote operation."""
    deadline = time.monotonic() + 5

    def check():
        if time.monotonic() > deadline:
            raise TimeoutError("Generation artifact readback deadline exceeded")

    return JobStore(readback_check=check, max_artifact_bytes=MAX_ASSET_BYTES)


def _load(job_id: str) -> dict:
    """Require exact kind and controller-verified immutable request/result bytes."""
    row = _store().get(job_id)
    if not row or row["kind"] != KIND:
        raise ValueError("Selected generation job was not found")
    if (row["attestation"]["request_integrity"] != "verified"
            or row["attestation"]["result_integrity"] not in {"verified", "absent"}):
        raise ValueError("Selected generation job integrity failed")
    return row


def _public(value):
    """Exclude private provider bodies and signed input URLs from public readback."""
    if isinstance(value, dict):
        return {key: _public(item) for key, item in value.items()
                if key not in {"public_url", "provider_evidence"}}
    if isinstance(value, list):
        return [_public(item) for item in value]
    return value


def _evidence(state: dict, body: bytes) -> None:
    """Retain the exact bounded provider response privately, including failed schemas."""
    state.setdefault("provider_evidence", []).append({"sha256": hashlib.sha256(body).hexdigest(),
        "bytes": len(body), "body_base64": base64.b64encode(body).decode("ascii")})


def _handoff(row: dict) -> dict:
    """Bind final media to the same durable scene, controls and reference commitments."""
    value = row["request"]["generation"]
    return {"provider": "dashscope", "model": value["model"],
            "provider_operation_id": row["external_id"], "source_revision": row["source_revision"],
            "request_sha256": row["request_sha256"],
            **{name: value[name] for name in ("scene_id", "script_id", "scene", "script", "label",
                "seed", "references", "continuation", "transparent_background", "duration", "resolution",
                "ratio", "expected_audio")},
            "audio_setting": value.get("audio_setting"),
            "prompt_extend": value.get("prompt_extend", False), "watermark": value.get("watermark", True),
            "expected_dimensions": row["request"]["expected_pixels"],
            **{name: row["request"][name] for name in ("wire_model", "mode", "reference_metadata",
                "dimension_basis", "continuation_settings", "expected_seconds") if name in row["request"]}}


def _view(row: dict) -> dict:
    """Report current byte proof and source handoff independently of recorded status."""
    state = row["result"] or {}
    status = row["status"]
    if status in {"running", "queued"} and not row["external_id"]:
        status = "unknown"
    if status == "completed":
        artifact = state.get("asset", {})
        proof = artifact.get("qualification", {})
        if (not row["attestation"]["verified"] or not verify_output(artifact, MAX_ASSET_BYTES)
                or not proof.get("full_decode") or proof.get("artifact_sha256") != artifact.get("sha256")
                or artifact.get("handoff") != _handoff(row)):
            status = "unknown"
        try:
            verify_sources(Path(row["request"]["project_dir"]), row["request"]["generation"])
        except (ValueError, OSError):
            status = "unknown"
    return GenerationResult(job_id=row["job_id"], status=status, recorded_status=row["status"],
                            model=row["request"]["generation"]["model"], source_revision=row["source_revision"],
                            request_sha256=row["request_sha256"], provider_operation_id=row["external_id"],
                            state=_public({**state, "request": row["request"]["generation"]}),
                            artifact_hashes=row["artifact_hashes"], attestation=row["attestation"],
                            error=row["error"]).model_dump(mode="json")


def _save(row: dict, owner: str, state: dict, status: str, *, release=False, external_id=None,
          error="", artifact_hashes=None) -> None:
    """Stop on failed CAS; an expired owner must never continue an external effect."""
    if not _store().checkpoint(row["job_id"], owner, status=status, result=state,
                                release=release, external_id=external_id, error=error,
                                artifact_hashes=artifact_hashes):
        raise RuntimeError("Generation ownership checkpoint failed; external state is UNKNOWN")


def _state() -> dict:
    """Start finite operation history and separate generation/cancel/fetch counters."""
    return {"submit_count": 0, "poll_count": 0, "cancel_count": 0, "operations": {},
            "provider_status": "UNKNOWN"}


def _begin(row: dict, action: str, operation: GenerationOperation) -> tuple[str, dict] | None:
    """Deduplicate explicit operations and lease one bounded foreground invocation."""
    if not operation.authorize:
        raise ValueError("Explicit caller operation authorization is required")
    if operation.principal != row["request"]["generation"]["operation"]["principal"]:
        raise ValueError("Caller-declared principal differs from the frozen request")
    state = row["result"] or _state()
    previous = state["operations"].get(operation.operation_id)
    if previous and previous != action:
        raise ValueError("Operation ID is already bound to a different action")
    if previous or row["status"] in {"completed", "failed", "cancelled", "partial"}:
        return None
    if action != "submit" and not row["external_id"]:
        return None
    if (adapter_revisions() != row["request"]["adapter_revision"]
            or contract_for(row["request"]["generation"]["model"]) != row["request"]["contract"]):
        raise ValueError("Generation adapter changed; frozen job requires reconciliation")
    base, _ = selected_config()
    if base != row["request"]["api_origin"]:
        raise ValueError("Selected endpoint differs from the frozen operation origin")
    if action != "submit" and state["poll_count"] >= row["request"]["generation"]["max_polls"]:
        raise ValueError("Generation task fetch budget exhausted; remote state remains unresolved")
    if action == "cancel" and state["cancel_count"]:
        return None
    owner = uuid4().hex
    claimed = _store().claim(row["job_id"], owner, lease_seconds=180)
    if not claimed:
        return None
    state = claimed["result"] or _state()
    previous = state["operations"].get(operation.operation_id)
    if previous or (action == "submit" and claimed["result"]) or (action == "cancel" and state["cancel_count"]):
        _save(claimed, owner, state, claimed["status"], release=True)
        if previous and previous != action:
            raise ValueError("Operation ID is already bound to a different action")
        return None
    state["operations"][operation.operation_id] = action
    _save(row, owner, state, "unknown")
    return owner, state


async def _task_request(row: dict, owner: str, state: dict) -> TaskResponse:
    """Fetch once, counting durable intent before HTTP and rejecting ID substitution."""
    if state["poll_count"] >= row["request"]["generation"]["max_polls"]:
        raise ValueError("Generation task fetch budget exhausted")
    state["poll_count"] += 1
    _save(row, owner, state, "unknown")
    base, key = selected_config()
    if base != row["request"]["api_origin"]:
        raise ValueError("Task fetch origin differs from the frozen request")
    body = await request_bytes("GET", base + "/tasks/" + row["external_id"],
                               {"Authorization": "Bearer " + key}, None, 65536)
    _evidence(state, body)
    _save(row, owner, state, "unknown")
    task = TaskResponse.model_validate_json(body)
    if task.output.task_id != row["external_id"]:
        raise ValueError("Fetched provider task identity differs from durable operation")
    state["provider_status"] = task.output.task_status
    state["last_request_id"] = task.request_id
    _save(row, owner, state, "unknown")
    return task


async def _apply(row: dict, owner: str, state: dict, task: TaskResponse, action: str) -> None:
    """Accept only observed provider terminal state and fully qualified local bytes."""
    status = task.output.task_status
    if status == "SUCCEEDED" and action == "poll":
        project = project_directory(row["request"]["project_id"])
        if str(project) != row["request"]["project_dir"]:
            raise ValueError("Generation project differs from frozen output location")
        artifact = await acquire_asset(project, row["job_id"], task.output.video_url or (task.output.results or {}).get("video_url"))
        artifact["handoff"] = _handoff(row)
        state["asset"] = artifact
        hashes = {artifact["path"]: artifact["sha256"]}
        _save(row, owner, state, "unknown", artifact_hashes=hashes)
        artifact["qualification"] = await qualify_asset(artifact, row["request"])
        _save(row, owner, state, "completed", release=True, artifact_hashes=hashes)
        return
    mapped = {"PENDING": "running", "RUNNING": "running", "SUCCEEDED": "running",
              "CANCELED": "cancelled", "FAILED": "failed", "UNKNOWN": "unknown"}[status]
    error = "" if status in {"PENDING", "RUNNING", "CANCELED"} else (
        "Provider completed; explicit poll required to qualify asset" if status == "SUCCEEDED"
        else "Provider task failed" if status == "FAILED" else "Provider task state is UNKNOWN")
    _save(row, owner, state, mapped, release=True, error=error)


def _failure(row: dict, owner: str, state: dict, action: str, exc: BaseException) -> None:
    """Retain provenance and downloaded hashes while suppressing remote secrets/prose."""
    status = "failed" if state.get("provider_status") == "SUCCEEDED" and action == "poll" else "unknown"
    hashes = {state["asset"]["path"]: state["asset"]["sha256"]} if "asset" in state else None
    _save(row, owner, state, status, release=True, artifact_hashes=hashes,
          error=f"{action} did not verify ({type(exc).__name__}); no automatic generation retry")


async def submit_generation(project_id: str, request: GenerationRequest) -> dict:
    """Submit at most once for this immutable logical request, including across reload."""
    job_id = "wan-" + digest({"project_id": project_id, "logical_job_id": request.logical_job_id})[:32]
    row = _store().get(job_id)
    if row:
        row = _load(job_id)
        if row["request"]["project_id"] != project_id or row["request"]["generation"] != request.model_dump(mode="json"):
            raise ValueError("Existing logical generation request conflicts with frozen request")
        return _view(row)
    frozen, source = freeze_request(project_id, request)
    executable_identity()
    row = _store().create(KIND, frozen, source, job_id=job_id, exclusive_key=job_id)
    if row["status"] != "queued" or row["result"]:
        return _view(row)
    begun = _begin(row, "submit", request.operation)
    if begun is None:
        return _view(_load(job_id))
    owner, state = begun
    try:
        verify_sources(Path(frozen["project_dir"]), frozen["generation"])
        if read_operator_quote(Path(frozen["project_dir"]), request, frozen["api_origin"]) != frozen["quote"]:
            raise ValueError("Selected operator quote changed before submission")
        if request.model in MODES:
            await verify_public_references(frozen, request_bytes)
        state["submit_count"] = 1
        state["submission_intent_id"] = request.operation.operation_id
        _save(row, owner, state, "unknown")
        base, key = selected_config()
        if base != frozen["api_origin"]:
            raise ValueError("Submit origin differs from the frozen request")
        body = await request_bytes("POST", base + frozen.get("submit_path", "/services/aigc/video-generation/video-synthesis"),
                                   {"Authorization": "Bearer " + key, "X-DashScope-Async": "enable"},
                                   provider_payload(frozen), 65536)
        _evidence(state, body)
        _save(row, owner, state, "unknown")
        task = TaskResponse.model_validate_json(body)
        state["provider_status"] = task.output.task_status
        state["last_request_id"] = task.request_id
        _save(row, owner, state, "unknown", external_id=task.output.task_id)
        row = _load(job_id)
        await _apply(row, owner, state, task, "submit")
    except BaseException as exc:
        _failure(row, owner, state, "submit", exc)
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
    return _view(_load(job_id))


async def poll_generation(job_id: str, operation: GenerationOperation) -> dict:
    """Fetch one provider state, or report durable UNKNOWN without an external ID."""
    row = _load(job_id)
    begun = _begin(row, "poll", operation)
    if begun is None:
        return _view(_load(job_id))
    owner, state = begun
    try:
        task = await _task_request(row, owner, state)
        await _apply(row, owner, state, task, "poll")
    except BaseException as exc:
        _failure(row, owner, state, "poll", exc)
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
    return _view(_load(job_id))


async def cancel_generation(job_id: str, operation: GenerationOperation) -> dict:
    """Cancel only fresh PENDING; a JSON-string ACK requires a confirming fetch."""
    row = _load(job_id)
    begun = _begin(row, "cancel", operation)
    if begun is None:
        return _view(_load(job_id))
    owner, state = begun
    try:
        task = await _task_request(row, owner, state)
        if task.output.task_status != "PENDING":
            state["cancel_refused"] = "Only freshly observed PENDING tasks can be cancelled"
            await _apply(row, owner, state, task, "cancel")
            return _view(_load(job_id))
        if state["poll_count"] >= row["request"]["generation"]["max_polls"]:
            raise ValueError("Cancellation confirmation fetch budget unavailable")
        base, key = selected_config()
        if base != row["request"]["api_origin"]:
            raise ValueError("Cancellation origin differs from the frozen request")
        state["cancel_count"] = 1
        state["cancel_intent_id"] = operation.operation_id
        _save(row, owner, state, "unknown")
        body = await request_bytes("POST", base + "/tasks/" + row["external_id"] + "/cancel",
                                   {"Authorization": "Bearer " + key}, None, 65536)
        _evidence(state, body)
        _save(row, owner, state, "unknown")
        ack = json.loads(body)
        if not isinstance(ack, str) or not re.fullmatch(r"[a-zA-Z0-9_-]{1,100}", ack):
            raise ValueError("Cancel success must be the official JSON-string request ID")
        state["cancel_ack_request_id"] = ack
        _save(row, owner, state, "unknown")
        confirmed = await _task_request(row, owner, state)
        state["cancellation_confirmed"] = confirmed.output.task_status == "CANCELED"
        await _apply(row, owner, state, confirmed, "cancel")
    except BaseException as exc:
        _failure(row, owner, state, "cancel", exc)
        if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt, SystemExit)):
            raise
    return _view(_load(job_id))
