"""Immutable DSP source/runtime bindings and durable exact-artifact completion."""

from pathlib import Path
from uuid import uuid4

from .image_manifest import json_digest
from .image_preprocessing import check_worker
from .job_store import JobStore, _artifact_readback
from .research_jobs import receipt

REVISION_FILES = (
    "audio_dsp.py",
    "audio_dsp_jobs.py",
    "audio_dsp_backend.py",
    "audio_dsp_stdio.py",
    "audio_dsp_measure.py",
    "audio_dsp_native.py",
    "audio_dsp_pcm.py",
    "audio_dsp_visuals.py",
    "models/audio_dsp.py",
    "audio_assets.py",
    "audio_fingerprints.py",
    "media_snapshot.py",
    "media_local_io.py",
    "media_process.py",
    "media_probe.py",
    "media_clip_timing.py",
    "image_preprocessing.py",
    "image_manifest.py",
    "job_store.py",
    "config.py",
    "errors.py",
    "redaction.py",
)


def prepare(request, binding, timeout, state, cancelled, deadline):
    """Reserve only untouched queued work; restarts never rerun an attempted native operation."""
    import hashlib

    check_worker(cancelled, deadline)
    root = Path(__file__).parent
    revision = json_digest(
        {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in REVISION_FILES}
    )
    store = JobStore(readback_check=lambda: check_worker(cancelled, deadline))
    job = store.create("audio_dsp", binding, revision, job_id=request.job_id)
    state.update(store=store, job=job, owner="")
    if job["attestation"]["request_integrity"] != "verified":
        raise ValueError("DSP immutable request failed readback")
    if job["attempts"] or job["status"] != "queued":
        return store, job, ""
    check_worker(cancelled, deadline)
    owner = uuid4().hex
    state["owner"] = owner
    claimed = store.claim(job["job_id"], owner, lease_seconds=timeout + 15)
    state.update(job=claimed or job, owner=owner if claimed else "")
    check_worker(cancelled, deadline)
    return store, claimed or store.get(job["job_id"]), owner if claimed else ""


def retained(job):
    """Return only attested result bytes; an interrupted reservation remains explicitly unknown."""
    if job["result"] is None:
        return {
            "metadata": {
                "status": "unknown",
                "hint": "Read job_status; an attempted DSP job is never automatically repeated",
            },
            "job_receipt": receipt(job),
        }
    if not job["attestation"]["verified"]:
        raise ValueError("Retained DSP artifact or result failed readback")
    return {"metadata": job["result"], "job_receipt": receipt(job)}


def finish(state, result, status, artifacts, cancelled, deadline):
    """Checkpoint only after owned workers/processes and source readbacks have joined."""
    store, job, owner = (state[key] for key in ("store", "job", "owner"))
    def guard():
        check_worker(cancelled, deadline)

    store.readback_check = guard
    hashes = {row["path"]: row["sha256"] for row in artifacts}
    integrity, _ = _artifact_readback(hashes, guard)
    if integrity not in {"verified", "absent"}:
        raise ValueError("DSP completion artifact failed readback")
    guard()
    if not store.checkpoint(
        job["job_id"], owner, status=status, result=result, artifact_hashes=hashes, release=True
    ):
        raise RuntimeError("DSP completion lost durable ownership")
    state["terminal"] = True
    return retained(store.get(job["job_id"]))
