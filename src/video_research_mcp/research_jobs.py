"""Durable operation bindings for research launches and provider reconciliation."""

from __future__ import annotations

import asyncio
import hashlib
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from .config import get_config
from .job_store import JobStore

TERMINAL = {"completed", "failed", "partial", "cancelled"}


def account_scope() -> str:
    """Bind operation lookup to the configured credential without retaining it."""
    return hashlib.sha256(get_config().gemini_api_key.encode()).hexdigest()


def prepare_launch(kind: str, request: dict, job_id: str | None) -> tuple[dict, str]:
    """Persist admission before submission; a resumed launch never resends work."""
    store = JobStore()
    request = {**request, "account_scope": account_scope()}
    sources = ("research_jobs.py", "research_operations.py", "research_poll.py")
    revision = hashlib.sha256(
        b"".join((Path(__file__).parent / name).read_bytes() for name in sources)
    ).hexdigest()
    active = [
        item
        for item in store.list_active("research_web") + store.list_active("research_followup")
        if item["request"].get("account_scope") == account_scope() and item["job_id"] != job_id
    ]
    if active:
        raise RuntimeError(
            "Deep Research task already in progress: "
            + str(active[0]["external_id"] or active[0]["job_id"])
        )
    job = store.create(
        kind,
        request,
        revision,
        job_id=job_id,
        exclusive_key="research:" + account_scope(),
    )
    if job["attestation"]["request_integrity"] != "verified":
        raise ValueError("Research request failed readback attestation")
    if job["attempts"] or job["status"] != "queued":
        return job, ""
    owner = uuid4().hex
    claimed = store.claim(job["job_id"], owner)
    if claimed is None:
        return store.get(job["job_id"]), ""
    if claimed["attestation"]["request_integrity"] != "verified":
        raise ValueError("Research request failed readback attestation")
    return claimed, owner


def find_operation(interaction_id: str) -> dict | None:
    """Find only operations launched under this configured account."""
    job = JobStore().find_external(interaction_id)
    if job and job["kind"] in {"research_web", "research_followup"}:
        if (
            job["attestation"]["request_integrity"] != "verified"
            or job["attestation"]["result_integrity"] != "verified"
        ):
            raise ValueError("Research operation failed readback attestation")
        if job["request"]["account_scope"] != account_scope():
            raise PermissionError("Research operation belongs to a different configured account")
        return job
    return None


def receipt(job: dict) -> dict:
    """Expose controller identity and readback attestation separately from output."""
    return {
        key: job[key]
        for key in (
            "job_id",
            "status",
            "source_revision",
            "request_sha256",
            "external_id",
            "result_sha256",
            "artifact_hashes",
            "attestation",
            "error",
            "attempts",
        )
    }


def retained_result(job: dict) -> dict:
    """Return retained output only after its actual storage attestation passes."""
    if job["result"] is not None:
        if not job["attestation"]["verified"]:
            raise ValueError("Retained research evidence failed readback attestation")
        result = dict(job["result"])
    else:
        result = {
            "interaction_id": job["external_id"],
            "status": job["status"],
            "hint": "Poll the recorded operation; do not resubmit an ambiguous launch",
        }
    result["job_receipt"] = receipt(job)
    return result


@asynccontextmanager
async def live_lease(store: JobStore, job_id: str, owner: str):
    """Maintain ownership while provider or media work awaits external progress."""

    async def pulse():
        while True:
            await asyncio.sleep(5)
            if not store.heartbeat(job_id, owner):
                raise RuntimeError("Durable job ownership expired")

    heartbeat = asyncio.create_task(pulse())
    try:
        yield
        if heartbeat.done():
            heartbeat.result()
    finally:
        heartbeat.cancel()
        await asyncio.gather(heartbeat, return_exceptions=True)


def record_status(store: JobStore, job: dict, owner: str, result: dict) -> dict:
    """Persist provider status without treating cancellation or unknown as success."""
    remote = result["status"]
    status = {
        "queued": "running",
        "in_progress": "running",
        "completed": "completed",
        "failed": "failed",
        "cancelled": "cancelled",
        "incomplete": "partial",
        "requires_action": "unknown",
        "cancel_requested": "cancel_requested",
    }.get(remote, "unknown")
    current = store.get(job["job_id"])
    if current["status"] == "cancel_requested" and status == "completed":
        status = "partial"
        result = {**result, "status": "completed_after_cancel", "reconciliation_required": True}
    if current["status"] == "cancel_requested" and status in {"running", "unknown"}:
        status = "cancel_requested"
    if not store.checkpoint(
        job["job_id"],
        owner,
        status=status,
        external_id=result["interaction_id"],
        result=result,
        release=True,
    ):
        raise RuntimeError("Durable status checkpoint lost ownership")
    return retained_result(store.get(job["job_id"]))
