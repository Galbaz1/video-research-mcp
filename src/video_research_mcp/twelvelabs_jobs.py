"""Immutable account-scoped call receipts; recovery never repeats an HTTP operation."""

import json
from pathlib import Path
from uuid import uuid4

from .job_store import JobStore
from .research_jobs import receipt
from .search_provider_results import digest


def prepare(request, binding):
    """Persist one operation before attempting it; return an existing receipt on replay."""
    root = Path(__file__).parent
    paths = ("twelvelabs_client.py", "twelvelabs_jobs.py", "twelvelabs_payloads.py",
             "twelvelabs_results.py", "twelvelabs_validation.py", "twelvelabs_routes.py", "models/twelvelabs.py",
             "search_provider_results.py", "vision_http.py", "provider_readiness.py", "models/search_provider.py",
             "models/image_edit.py", "errors.py", "job_store.py", "config.py", "media_local_io.py",
             "media_snapshot.py", "media_acquisition.py")
    revision = digest(json.dumps({name: digest((root / name).read_bytes()) for name in paths}, sort_keys=True).encode())
    store = JobStore()
    job = store.create("twelvelabs_call", binding, revision, job_id=request.job_id)
    if job["attestation"]["request_integrity"] != "verified":
        raise ValueError("TwelveLabs immutable request failed readback")
    if job["attempts"] or job["status"] != "queued":
        return store, job, ""
    owner = uuid4().hex
    claimed = store.claim(job["job_id"], owner, lease_seconds=request.timeout_seconds + 10)
    return store, claimed or store.get(job["job_id"]), owner if claimed else ""


def retained(job):
    """Require storage integrity; an interrupted launch stays unknown until reconciliation."""
    if job["result"] is None:
        return {"job_receipt": receipt(job), "status": "unknown",
                "hint": "This call was already reserved. Read job_status; reconcile the provider operation without resubmitting."}
    if not job["attestation"]["verified"]:
        raise ValueError("Retained TwelveLabs response failed readback")
    return {**job["result"], "job_receipt": receipt(job)}


def finish(store, job, owner, result, *, unknown=False):
    """Complete the local observation separately from the remote task's lifecycle."""
    status = "unknown" if unknown else "failed" if "error" in result else "completed"
    if not store.checkpoint(job["job_id"], owner, status=status, result=result, release=True):
        raise RuntimeError("TwelveLabs receipt lost ownership")
    return retained(store.get(job["job_id"]))


def ready_asset(request, account_scope):
    """Admit indexed creation from an attested ready asset observation in this account."""
    if request.operation != "indexed_asset_create":
        return
    if not request.ready_asset_job_id:
        raise ValueError("Indexed creation requires ready_asset_job_id from a prior asset_get ready observation")
    job = JobStore().get(request.ready_asset_job_id)
    if not job or not job["attestation"]["verified"] or job["kind"] != "twelvelabs_call":
        raise ValueError("Ready asset receipt is missing or fails integrity")
    result = job["result"]
    if (job["request"].get("account_scope") != account_scope or result.get("operation") != "asset_get"
            or result.get("status") != "ready" or result["ids"].get("asset_id") != request.parameters["asset_id"]):
        raise ValueError("Ready asset receipt has a different account, ID or readiness state")
