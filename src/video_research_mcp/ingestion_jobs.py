"""Joined ingestion ownership and exact-artifact completion in the shared job store."""

from .image_preprocessing import check_worker
from .job_store import JobStore, _artifact_readback


def reserve(binding, source, job_id, owner, timeout, state, cancelled, deadline):
    """Claim only an untouched queued identity; never repeat attempted parser work."""
    def guard():
        check_worker(cancelled, deadline)
    guard()
    store = JobStore(readback_check=guard)
    row = store.create("source_ingestion", binding, source["revision"], job_id=job_id)
    if row["attempts"] or row["status"] != "queued":
        return False
    guard()
    row = store.claim(job_id, owner, lease_seconds=timeout + 15)
    if row is None:
        return False
    state["row"] = row
    guard()
    if not store.checkpoint(job_id, owner, result={"original": source, "indexed": False},
                            artifact_hashes={source["path"]: source["sha256"]}):
        raise RuntimeError("Ingestion reservation lost ownership")
    return True


def publish(job_id, owner, artifacts, cancelled, deadline):
    """Commit completion only after exact outputs and the ownership guard verify."""
    def guard():
        check_worker(cancelled, deadline)
    integrity, _ = _artifact_readback(artifacts["artifact_hashes"], guard)
    if integrity != "verified":
        raise ValueError("Ingestion completion artifact readback failed")
    guard()
    store = JobStore(readback_check=guard)
    if not store.checkpoint(job_id, owner, status="completed", release=True,
                            result={"manifest": artifacts["manifest"]},
                            artifact_hashes=artifacts["artifact_hashes"]):
        raise RuntimeError("Ingestion completion lost ownership or cancellation changed")
