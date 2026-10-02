"""Persistent render identity, ownership, cancellation and artifact receipts."""

from __future__ import annotations

import hashlib
import json

import pytest

from video_explainer_mcp.job_store import JobStore
from video_explainer_mcp.jobs import create_job, get_job, reconcile_job

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _project(tmp_path, monkeypatch):
    project = tmp_path / "projects" / "test"
    project.mkdir(parents=True)
    (project / "source.json").write_text('{"original":"fixture"}')
    (project / "storyboard").mkdir()
    (project / "storyboard/storyboard.json").write_text('{"scenes":[]}')
    (project / "config.json").write_text(json.dumps({"paths": {
        "storyboard": "storyboard/storyboard.json", "final_video": "output/final.mp4",
    }}))
    monkeypatch.setenv("EXPLAINER_PATH", str(tmp_path))


def test_create_retains_public_identity_and_frozen_request():
    """The former short job identifier remains stable with a persisted source/settings binding."""
    job = create_job("test", "1080p", False)
    assert len(job["job_id"]) == 12
    assert job["request"]["project_id"] == "test"
    assert job["request"]["resolution"] == "1080p"
    assert job["request"]["fast"] is False
    assert job["status"] == "queued"
    assert len(job["source_revision"]) == 64
    assert len(job["request_sha256"]) == 64


def test_get_after_store_recreation():
    """A new store instance retains the exact identifier, source and request revisions."""
    job = create_job("test")
    found = get_job(job["job_id"])
    assert found["job_id"] == job["job_id"]
    assert found["request"] == job["request"]
    assert found["source_revision"] == job["source_revision"]
    assert get_job("nonexistent") is None


def test_rejects_other_job_kinds():
    job = JobStore().create("research", {"prompt": "fixture"}, "revision")
    assert get_job(job["job_id"]) is None


def test_owned_completion_retains_output_and_duration(tmp_path):
    """Only a current owner can accept the actual output digest and duration."""
    job = create_job("test")
    artifact = tmp_path / "out.mp4"
    artifact.write_bytes(b"owned output")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert JobStore().claim(job["job_id"], "worker")
    assert JobStore().checkpoint(
        job["job_id"],
        "worker",
        status="completed",
        result={
            "output": {
                "path": str(artifact),
                "sha256": digest,
                "size_bytes": artifact.stat().st_size,
            },
            "duration_seconds": 42.5,
        },
        artifact_hashes={str(artifact): digest},
    )
    found = get_job(job["job_id"])
    assert found["status"] == "completed"
    assert found["result"]["duration_seconds"] == 42.5
    assert found["attestation"]["artifact_integrity"] == "verified"
    assert not JobStore().checkpoint(job["job_id"], "worker", status="failed")


def test_failure_retains_exact_error():
    job = create_job("test")
    assert JobStore().claim(job["job_id"], "worker")
    assert JobStore().checkpoint(job["job_id"], "worker", status="failed", error="OOM")
    assert get_job(job["job_id"])["error"] == "OOM"
    assert not JobStore().checkpoint("missing", "worker", status="failed")


def test_queued_cancel_is_terminal_and_cannot_complete():
    job = create_job("test")
    assert JobStore().cancel(job["job_id"])["status"] == "cancelled"
    assert JobStore().claim(job["job_id"], "worker") is None


def test_active_lease_cannot_be_recovered():
    job = create_job("test")
    claimed = JobStore().claim(job["job_id"], "worker")
    recovered = reconcile_job(job["job_id"])
    assert recovered["owner"] == "worker"
    assert recovered["attempts"] == claimed["attempts"]
    assert recovered["status"] == "running"


def test_stale_process_is_unknown_and_never_relaunched():
    job = create_job("test")
    assert JobStore().claim(job["job_id"], "old-worker", now=1)
    assert JobStore().checkpoint(
        job["job_id"], "old-worker", external_id="process:123:owned-token", now=2
    )
    recovered = reconcile_job(job["job_id"])
    assert recovered["status"] == "unknown"
    assert recovered["external_id"] == "process:123:owned-token"
    assert recovered["owner"] is None
    assert recovered["attempts"] == 2
    with pytest.raises(RuntimeError, match="already in progress"):
        create_job("test")
