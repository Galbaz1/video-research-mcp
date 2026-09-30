"""Restart-safe bounded video batches with per-item checkpoints and no resubmission."""

from __future__ import annotations

import asyncio
import hashlib
from pathlib import Path
from uuid import uuid4

from .job_execution import job_submission
from .config import get_config
from .job_store import JobStore
from .media_identity import identify_source
from .redaction import redact_text
from .research_jobs import TERMINAL, account_scope, live_lease, receipt, retained_result
from .tools.video_core import analyze_video
from .tools.video_file import _video_file_content


def runtime_settings() -> dict:
    """Freeze the concrete account, model and sampling settings used by this batch."""
    cfg = get_config()
    return {
        "account_scope": account_scope(),
        "model": cfg.default_model,
        "temperature": cfg.default_temperature,
    }


def batch_result(directory: str, items: list[dict]) -> dict:
    """Retain every denominator item, including failed, canceled and unknown work."""
    return {
        "directory": directory,
        "total_files": len(items),
        "successful": sum(item["status"] == "completed" for item in items),
        "failed": sum(item["status"] == "failed" for item in items),
        "canceled": sum(item["status"] == "cancelled" for item in items),
        "partial": sum(
            item["status"] in {"unknown", "running", "queued", "completed_after_cancel"}
            for item in items
        ),
        "items": items,
    }


def _verify_prepared(item, contents, content_id):
    """Reject prepared payloads or current originals outside the frozen item digest."""
    if (
        content_id != item["source_sha256"]
        or identify_source(
            item["file_path"], expected_digest=item["source_sha256"], persist=False
        ).state
        != "fresh"
    ):
        raise ValueError("Prepared video differs from frozen batch source")
    for part in contents.parts:
        if (
            part.inline_data is not None
            and hashlib.sha256(part.inline_data.data).hexdigest() != item["source_sha256"]
        ):
            raise ValueError("Prepared video bytes differ from frozen batch source")


async def _analyze_item(store, job, owner, items, index) -> dict | None:
    """Verify exact original bytes/settings before the item's single submission."""
    item = items[index]
    request = job["request"]
    current = identify_source(
        item["file_path"], expected_digest=item["source_sha256"], persist=False
    )
    if current.state != "fresh":
        raise ValueError("Batch original source changed or became unavailable")
    if runtime_settings() != request["runtime"]:
        raise ValueError("Batch account/model/sampling settings changed")
    contents, content_id, _ = await _video_file_content(item["file_path"], request["instruction"])
    _verify_prepared(item, contents, content_id)
    if runtime_settings() != request["runtime"]:
        raise ValueError("Batch account/model/sampling settings changed during preparation")
    if store.get(job["job_id"])["status"] == "cancel_requested":
        item["status"] = "cancelled"
        return None
    if not store.checkpoint(job["job_id"], owner, result=batch_result(request["directory"], items)):
        raise RuntimeError("Batch item lost ownership before provider submission")
    return await analyze_video(
        contents,
        instruction=request["instruction"],
        content_id=content_id,
        source_label=item["file_path"],
        output_schema=request["output_schema"],
        thinking_level=request["thinking_level"],
        use_cache=True,
        local_filepath=item["file_path"],
    )


async def _process_item(store, job, owner, items, index, semaphore):
    """Checkpoint before provider submission; failures retain the original item."""
    async with semaphore:
        item = items[index]
        if item["status"] != "queued":
            return
        if store.get(job["job_id"])["status"] == "cancel_requested":
            item["status"] = "cancelled"
        else:
            item["status"] = "running"
        if not store.checkpoint(
            job["job_id"], owner, result=batch_result(job["request"]["directory"], items)
        ):
            raise RuntimeError("Batch item lost ownership before media preparation")
        if item["status"] == "cancelled":
            return
        request = job["request"]
        try:
            result = await _analyze_item(store, job, owner, items, index)
            if result is None:
                return
            item.update(
                result=result,
                status="failed" if "error" in result else "completed",
                error=result.get("error", ""),
            )
            if store.get(job["job_id"])["status"] == "cancel_requested":
                item.update(status="completed_after_cancel", reconciliation_required=True)
        except asyncio.CancelledError:
            item.update(
                status="unknown", error="Submission interrupted; provider completion unknown"
            )
            raise
        except Exception as error:
            item.update(status="failed", error=redact_text(str(error)))
        finally:
            store.checkpoint(job["job_id"], owner, result=batch_result(request["directory"], items))


async def execute_batch(request: dict, job_id: str | None) -> dict:
    """Recover queued items once and retain ambiguous submissions without retrying them."""
    store = JobStore()
    revision = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    job = store.create("video_batch", request, revision, job_id=job_id)
    if job["attestation"]["request_integrity"] != "verified" or job["attestation"][
        "result_integrity"
    ] not in {"verified", "absent"}:
        raise ValueError("Batch evidence failed readback attestation")
    if job["status"] in TERMINAL:
        return retained_result(job)
    owner = uuid4().hex
    claimed = store.claim(job["job_id"], owner)
    if claimed is None:
        result = dict(job["result"] or batch_result(request["directory"], request["items"]))
        return {**result, "job_receipt": receipt(job)}
    job = claimed
    if job["attestation"]["request_integrity"] != "verified" or job["attestation"][
        "result_integrity"
    ] not in {"verified", "absent"}:
        raise ValueError("Batch evidence failed readback attestation")
    items = job["result"]["items"] if job["result"] else request["items"]
    for item in items:
        if item["status"] == "running":
            item.update(status="unknown", error="Previous submission interrupted; not resubmitted")
    semaphore = asyncio.Semaphore(request["max_concurrency"])
    try:
        with job_submission():
            async with live_lease(store, job["job_id"], owner):
                async with asyncio.TaskGroup() as group:
                    for index in range(len(items)):
                        group.create_task(_process_item(store, job, owner, items, index, semaphore))
    except asyncio.CancelledError:
        for item in items:
            if item["status"] == "queued":
                item["status"] = "cancelled"
        store.cancel(job["job_id"])
        store.checkpoint(
            job["job_id"],
            owner,
            status="partial",
            result=batch_result(request["directory"], items),
            release=True,
        )
        raise
    return _finish_batch(store, job, owner, items)


def _finish_batch(store, job, owner, items) -> dict:
    """Acknowledge the final checkpoint while retaining mixed/cancelled denominators."""
    request = job["request"]
    result = batch_result(request["directory"], items)
    current = store.get(job["job_id"])
    if current["status"] == "cancel_requested":
        status = "partial" if result["partial"] else "cancelled"
    elif result["partial"] or result["failed"] and result["successful"]:
        status = "partial"
    else:
        status = "failed" if result["failed"] else "completed"
    if not store.checkpoint(job["job_id"], owner, status=status, result=result, release=True):
        raise RuntimeError("Batch final checkpoint lost ownership")
    return retained_result(store.get(job["job_id"]))
