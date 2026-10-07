"""Reject oversized or concurrently changing regular controller artifacts."""

import hashlib

from video_research_mcp.job_store import JobStore


def completed(tmp_path, body=b"owned"):
    path = tmp_path / "asset.bin"
    path.write_bytes(body)
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create("fixture", {}, "source", job_id="fixture")
    store.claim("fixture", "owner", now=10)
    digest = hashlib.sha256(body).hexdigest()
    assert store.checkpoint("fixture", "owner", status="completed", artifact_hashes={str(path): digest}, now=11)
    return path, store


def test_controller_size_ceiling_refuses_oversized_regular_artifact(tmp_path):
    path, store = completed(tmp_path)
    with path.open("wb") as stream:
        stream.truncate(32 * 1024 * 1024 + 1)
    bounded = JobStore(store.path, max_artifact_bytes=32 * 1024 * 1024)
    result = bounded.get("fixture")
    assert result["attestation"]["artifact_integrity"] == "unavailable"
    assert not result["attestation"]["verified"]
    assert result["artifact_hashes"] == {str(path): hashlib.sha256(b"owned").hexdigest()}


def test_controller_growth_during_readback_refuses_finite_snapshot(tmp_path):
    path, store = completed(tmp_path)
    calls = 0

    def grow():
        nonlocal calls
        calls += 1
        if calls == 2:
            with path.open("ab") as stream:
                stream.write(b"growth")

    bounded = JobStore(store.path, readback_check=grow, max_artifact_bytes=32 * 1024 * 1024)
    result = bounded.get("fixture")
    assert result["attestation"]["artifact_integrity"] == "unavailable"
    assert calls < 6 and not result["attestation"]["verified"]
