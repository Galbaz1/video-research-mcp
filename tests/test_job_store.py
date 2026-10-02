"""Durable job ownership and readback using real, isolated SQLite databases."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import stat
from threading import Barrier

import pytest

from video_research_mcp.job_store import JobStore


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "jobs.sqlite3")


def create(store, *, job_id="fixture", kind="fixture", exclusive_key=None):
    return store.create(
        kind,
        {"instruction": "Owned fixture", "settings": {"depth": 1}},
        "sha256:owned-source",
        job_id=job_id,
        exclusive_key=exclusive_key,
    )


def test_constructor_and_default_env_are_lazy(tmp_path, monkeypatch):
    target = tmp_path / "unopened" / "jobs.sqlite3"
    monkeypatch.setenv("VRM_JOB_DB", str(target))
    current = JobStore()
    assert Path(current.path) == target
    assert not target.parent.exists()
    assert current.get("missing") is None
    assert target.exists()


def test_new_state_and_database_are_private_before_wal(tmp_path):
    ancestor_mode = stat.S_IMODE(tmp_path.stat().st_mode)
    target = tmp_path / "private-state" / "jobs.sqlite3"
    current = JobStore(target)
    create(current)
    assert stat.S_IMODE(target.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == ancestor_mode
    with sqlite3.connect(target) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE jobs SET updated_at=updated_at WHERE job_id=?", ("fixture",))
        for suffix in ("-wal", "-shm"):
            assert stat.S_IMODE(Path(str(target) + suffix).stat().st_mode) == 0o600


def test_existing_parent_permissions_are_untouched_and_db_is_private(tmp_path):
    parent = tmp_path / "existing"
    parent.mkdir(mode=0o755)
    parent.chmod(0o755)
    target = parent / "jobs.sqlite3"
    with sqlite3.connect(target):
        pass
    target.chmod(0o644)
    assert JobStore(target).get("absent") is None
    assert stat.S_IMODE(parent.stat().st_mode) == 0o755
    assert stat.S_IMODE(target.stat().st_mode) == 0o600


def test_create_canonical_unicode_identity_and_restart(store):
    request = {"unicode": "Résumé", "settings": {"b": 2, "a": 1}}
    row = store.create("research", request, "source-revision", job_id="12hexfixture")
    expected = hashlib.sha256(
        json.dumps(
            {
                "kind": "research",
                "request": request,
                "source_revision": "source-revision",
                "exclusive_key": None,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()
    assert row["request_sha256"] == expected
    assert row["status"] == "queued" and row["attempts"] == 0
    assert row["request"] == request and row["source_revision"] == "source-revision"
    reopened = JobStore(store.path).get(row["job_id"])
    assert reopened["request"] == request and reopened["job_id"] == row["job_id"]
    assert reopened["attestation"]["request_integrity"] == "verified"
    assert (
        store.create(
            "research",
            {"settings": {"a": 1, "b": 2}, "unicode": "Résumé"},
            "source-revision",
            job_id="12hexfixture",
        )["job_id"]
        == row["job_id"]
    )


@pytest.mark.parametrize("changed", ["kind", "request", "source_revision", "exclusive_key"])
def test_existing_job_cannot_change_immutable_binding(store, changed):
    create(store)
    options = {
        "kind": "fixture",
        "request": {"instruction": "Owned fixture", "settings": {"depth": 1}},
        "source_revision": "sha256:owned-source",
        "job_id": "fixture",
        "exclusive_key": None,
    }
    options[changed] = {"changed": True} if changed == "request" else "changed"
    with pytest.raises(ValueError, match="binding"):
        store.create(**options)
    assert store.get("fixture")["status"] == "queued"


@pytest.mark.parametrize("status", ["queued", "running", "cancel_requested", "unknown"])
def test_active_or_unknown_exclusive_resource_blocks_duplicate(store, status):
    create(store, exclusive_key="owned-project")
    if status != "queued":
        store.claim("fixture", "owner", now=10)
        if status == "cancel_requested":
            store.cancel("fixture")
        elif status == "unknown":
            assert store.checkpoint("fixture", "owner", status="unknown", release=True, now=11)
    with pytest.raises(ValueError, match="exclusive"):
        create(store, job_id="duplicate", exclusive_key="owned-project")
    assert len(store.list_active("fixture")) == 1


def test_terminal_resource_can_be_reused_only_by_explicit_new_job(store):
    create(store, exclusive_key="owned-project")
    store.claim("fixture", "owner", now=10)
    assert store.checkpoint("fixture", "owner", status="failed", error="owned failure", now=11)
    new = create(store, job_id="explicit-new", exclusive_key="owned-project")
    assert new["status"] == "queued"
    assert store.claim("fixture", "other", now=100) is None


def test_two_connections_claim_exactly_one_owner(store):
    create(store)
    barrier = Barrier(2)

    def compete(owner):
        barrier.wait(timeout=5)
        return JobStore(store.path).claim("fixture", owner, now=10)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, ("one", "two")))
    assert sum(row is not None for row in results) == 1
    assert store.get("fixture")["attempts"] == 1


def test_simultaneous_fresh_database_creates_are_serialized_by_sqlite(tmp_path):
    target = tmp_path / "simultaneous" / "jobs.sqlite3"
    barrier = Barrier(4)

    def compete(index):
        barrier.wait(timeout=5)
        return create(JobStore(target), job_id=f"owned-{index}")

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(compete, range(4)))
    assert len({row["job_id"] for row in results}) == 4
    assert len(JobStore(target).list_active("fixture")) == 4


def test_wal_bootstrap_retries_controlled_sqlite_busy_only(tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    attempts = []

    class BusyOnce(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA journal_mode=WAL":
                attempts.append(sql)
                if len(attempts) == 1:
                    error = sqlite3.OperationalError("database is locked")
                    error.sqlite_errorcode = sqlite3.SQLITE_BUSY
                    raise error
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *args, **kwargs: original_connect(*args, factory=BusyOnce, **kwargs),
    )
    row = create(JobStore(tmp_path / "busy.sqlite3"))
    assert row["status"] == "queued" and len(attempts) == 2


def test_wal_bootstrap_does_not_retry_nonbusy_sqlite_failure(tmp_path, monkeypatch):
    original_connect = sqlite3.connect
    attempts = []

    class BrokenIO(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "PRAGMA journal_mode=WAL":
                attempts.append(sql)
                error = sqlite3.OperationalError("owned fixture disk I/O failure")
                error.sqlite_errorcode = sqlite3.SQLITE_IOERR
                raise error
            return super().execute(sql, *args, **kwargs)

    monkeypatch.setattr(
        sqlite3,
        "connect",
        lambda *args, **kwargs: original_connect(*args, factory=BrokenIO, **kwargs),
    )
    with pytest.raises(sqlite3.OperationalError, match="I/O"):
        create(JobStore(tmp_path / "broken.sqlite3"))
    assert len(attempts) == 1


def test_stale_lease_is_reconciliation_ownership_not_resubmission(store):
    create(store)
    initial = store.claim("fixture", "first", lease_seconds=20, now=10)
    assert initial["status"] == "running" and initial["attempts"] == 1
    assert store.checkpoint("fixture", "first", external_id="operation-owned", now=11)
    assert store.claim("fixture", "second", now=29) is None
    recovered = JobStore(store.path).claim("fixture", "second", now=30)
    assert recovered["status"] == "running" and recovered["attempts"] == 2
    assert recovered["external_id"] == "operation-owned"
    assert not store.heartbeat("fixture", "first", now=31)
    assert not store.checkpoint(
        "fixture", "first", status="completed", result={"late": True}, now=31
    )
    assert store.checkpoint(
        "fixture", "second", status="completed", result={"retained": True}, now=31
    )
    assert not store.checkpoint("fixture", "second", status="failed", now=32)


def test_release_preserves_running_operation_for_polling(store):
    create(store)
    store.claim("fixture", "submitter", now=10)
    assert store.checkpoint(
        "fixture", "submitter", external_id="remote-owned", release=True, now=11
    )
    row = store.get("fixture")
    assert row["status"] == "running" and row["owner"] is None and row["lease_until"] is None
    assert row["external_id"] == "remote-owned"
    poller = store.claim("fixture", "poller", now=12)
    assert poller["external_id"] == "remote-owned" and poller["attempts"] == 2


def test_heartbeat_requires_matching_unexpired_owner(store):
    create(store)
    store.claim("fixture", "owner", now=10)
    assert not store.heartbeat("fixture", "other", now=15)
    assert store.heartbeat("fixture", "owner", lease_seconds=30, now=20)
    assert store.get("fixture")["lease_until"] == 50
    assert not store.heartbeat("fixture", "owner", now=50)
    assert not store.checkpoint("fixture", "owner", result={"expired": True}, now=50)
    assert store.claim("fixture", "other", now=50) is not None


def test_queued_cancel_is_terminal_immediately(store):
    create(store)
    cancelled = store.cancel("fixture")
    assert cancelled["status"] == "cancelled" and cancelled["external_id"] is None
    assert store.claim("fixture", "owner", now=10) is None
    assert store.cancel("absent") is None


@pytest.mark.parametrize("terminal", ["cancelled", "failed", "partial"])
def test_requested_cancel_rejects_late_completion_and_allows_explicit_terminal(store, terminal):
    create(store)
    store.claim("fixture", "owner", now=10)
    assert store.cancel("fixture")["status"] == "cancel_requested"
    assert not store.checkpoint(
        "fixture", "owner", status="completed", result={"late": True}, now=11
    )
    assert not store.checkpoint("fixture", "owner", status="running", now=11)
    assert store.checkpoint("fixture", "owner", status=terminal, error="explicit outcome", now=12)
    assert store.get("fixture")["status"] == terminal
    assert store.claim("fixture", "restarted", now=100) is None


def test_unknown_submission_is_retained_and_cancel_is_not_external_ack(store):
    create(store)
    store.claim("fixture", "owner", now=10)
    assert store.checkpoint("fixture", "owner", status="unknown", release=True, now=11)
    recovered = JobStore(store.path).claim("fixture", "reconciler", now=12)
    assert recovered["status"] == "unknown" and recovered["attempts"] == 2
    assert store.cancel("fixture")["status"] == "cancel_requested"
    assert store.get("fixture")["external_id"] is None


def test_external_id_is_assign_once_unique_per_kind_and_terminal_lookup(store):
    create(store)
    create(store, job_id="other")
    store.claim("fixture", "one", now=10)
    store.claim("other", "two", now=10)
    assert store.checkpoint("fixture", "one", external_id="operation", now=11)
    assert store.checkpoint("fixture", "one", external_id="operation", now=12)
    assert not store.checkpoint("fixture", "one", external_id="replacement", now=12)
    assert not store.checkpoint("other", "two", external_id="operation", now=12)
    assert store.checkpoint("fixture", "one", status="completed", result={"items": []}, now=13)
    retained = JobStore(store.path).find_external("operation", kind="fixture")
    assert retained["job_id"] == "fixture" and retained["status"] == "completed"
    assert store.find_external("operation")["job_id"] == "fixture"
    assert store.find_external("missing") is None


def test_result_readback_digest_and_corruption_attestation(store):
    create(store)
    store.claim("fixture", "owner", now=10)
    result = {"unicode": "Résumé", "items": [1, 2]}
    assert store.checkpoint("fixture", "owner", status="completed", result=result, now=11)
    row = JobStore(store.path).get("fixture")
    encoded = json.dumps(
        {
            "result": result,
            "request_sha256": row["request_sha256"],
            "external_id": None,
            "artifact_hashes": {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert row["result_sha256"] == hashlib.sha256(encoded.encode()).hexdigest()
    assert row["attestation"]["verified"]
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE jobs SET result_json=? WHERE job_id=?", ('{"tampered":true}', "fixture"))
    corrupted = store.get("fixture")
    assert corrupted["status"] == "completed"
    assert corrupted["attestation"]["result_integrity"] == "mismatch"
    assert not corrupted["attestation"]["verified"]


def test_missing_result_digest_and_invalid_json_are_not_verified(store):
    create(store)
    store.claim("fixture", "owner", now=10)
    store.checkpoint("fixture", "owner", status="completed", result={"owned": True}, now=11)
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE jobs SET result_sha256=NULL WHERE job_id=?", ("fixture",))
    assert store.get("fixture")["attestation"]["result_integrity"] == "mismatch"
    assert not store.get("fixture")["attestation"]["verified"]
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE jobs SET result_json=? WHERE job_id=?", ("invalid JSON", "fixture"))
    assert store.get("fixture")["attestation"]["result_integrity"] == "invalid"


def test_request_corruption_does_not_change_identity_or_pass_attestation(store):
    create(store)
    expected = store.get("fixture")["request_sha256"]
    with sqlite3.connect(store.path) as db:
        db.execute("UPDATE jobs SET request_json=? WHERE job_id=?", ('{"changed":true}', "fixture"))
    row = store.get("fixture")
    assert row["request_sha256"] == expected
    assert row["attestation"]["request_integrity"] == "mismatch"
    assert not row["attestation"]["verified"]


def test_source_revision_edit_breaks_request_and_result_binding(store):
    create(store)
    store.claim("fixture", "owner", now=10)
    store.checkpoint("fixture", "owner", status="completed", result={"owned": True}, now=11)
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE jobs SET source_revision=? WHERE job_id=?", ("changed-source", "fixture")
        )
    row = store.get("fixture")
    assert row["attestation"]["request_integrity"] == "mismatch"
    assert row["attestation"]["result_integrity"] == "mismatch"
    assert not row["attestation"]["verified"]


def test_claim_rejects_corrupted_frozen_request_before_work(store):
    create(store)
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE jobs SET source_revision=? WHERE job_id=?", ("changed-source", "fixture")
        )
    with pytest.raises(ValueError, match="request.*integrity"):
        store.claim("fixture", "owner", now=10)
    row = store.get("fixture")
    assert row["owner"] is None and row["attempts"] == 0


def test_changed_artifact_manifest_and_matching_file_break_result_commitment(store, tmp_path):
    create(store)
    artifact = tmp_path / "owned-output.bin"
    artifact.write_bytes(b"original artifact")
    store.claim("fixture", "owner", now=10)
    store.checkpoint(
        "fixture",
        "owner",
        status="completed",
        result={"owned": True},
        artifact_hashes={str(artifact): hashlib.sha256(artifact.read_bytes()).hexdigest()},
        now=11,
    )
    artifact.write_bytes(b"changed artifact")
    manifest = {str(artifact): hashlib.sha256(artifact.read_bytes()).hexdigest()}
    with sqlite3.connect(store.path) as db:
        db.execute(
            "UPDATE jobs SET artifact_hashes_json=? WHERE job_id=?",
            (json.dumps(manifest), "fixture"),
        )
    row = store.get("fixture")
    assert row["attestation"]["artifact_integrity"] == "verified"
    assert row["attestation"]["result_integrity"] == "mismatch"
    assert not row["attestation"]["verified"]


def test_directory_artifact_is_unavailable_and_never_verified(store, tmp_path):
    create(store)
    store.claim("fixture", "owner", now=10)
    assert store.checkpoint(
        "fixture",
        "owner",
        status="completed",
        result={"owned": True},
        artifact_hashes={str(tmp_path): "0" * 64},
        now=11,
    )
    assert store.get("fixture")["attestation"]["artifact_integrity"] == "unavailable"


def test_fifo_artifact_does_not_block_readback(store, tmp_path):
    create(store)
    fifo = tmp_path / "untrusted-fifo"
    os.mkfifo(fifo)
    store.claim("fixture", "owner", now=10)
    store.checkpoint(
        "fixture",
        "owner",
        status="completed",
        result={"owned": True},
        artifact_hashes={str(fifo): "0" * 64},
        now=11,
    )
    assert store.get("fixture")["attestation"]["artifact_integrity"] == "unavailable"


def test_independently_loaded_stdlib_module_shares_identical_schema(store):
    import video_research_mcp.job_store as module

    spec = importlib.util.spec_from_file_location("independent_fixture_store", module.__file__)
    other = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(other)
    create(store)
    companion = other.JobStore(store.path)
    assert companion.claim("fixture", "companion", now=10)["owner"] == "companion"
    assert store.checkpoint(
        "fixture", "companion", external_id="shared-operation", release=True, now=11
    )
    assert (
        companion.find_external("shared-operation", kind="fixture")["source_revision"]
        == "sha256:owned-source"
    )


def test_parameterized_sql_treats_identifiers_as_data(store):
    label = "owned'; DROP TABLE jobs; --"
    row = create(store, job_id=label, kind=label, exclusive_key=label)
    assert store.get(label)["job_id"] == row["job_id"]
    assert store.get("missing") is None


def test_unscoped_external_collision_is_ambiguous_not_wrong_job(store):
    create(store, kind="first")
    create(store, job_id="second", kind="second")
    for job in ("fixture", "second"):
        store.claim(job, "owner", now=10)
        assert store.checkpoint(job, "owner", external_id="shared-label", release=True, now=11)
    assert store.find_external("shared-label") is None
    assert store.find_external("shared-label", kind="first")["job_id"] == "fixture"


@pytest.mark.parametrize("mutation", ["changed", "missing", "symlink"])
def test_completed_artifact_readback_never_certifies_changed_or_unavailable_bytes(
    store, tmp_path, mutation
):
    create(store)
    artifact = tmp_path / "owned-output.bin"
    artifact.write_bytes(b"owned exact artifact")
    expected = hashlib.sha256(artifact.read_bytes()).hexdigest()
    store.claim("fixture", "owner", now=10)
    assert store.checkpoint(
        "fixture",
        "owner",
        status="completed",
        result={"path": str(artifact)},
        artifact_hashes={str(artifact): expected},
        now=11,
    )
    assert store.get("fixture")["attestation"]["verified"]
    if mutation == "changed":
        artifact.write_bytes(b"changed exact artifact")
    elif mutation == "missing":
        artifact.unlink()
    else:
        replacement = tmp_path / "replacement.bin"
        replacement.write_bytes(b"owned exact artifact")
        artifact.unlink()
        artifact.symlink_to(replacement)
    row = JobStore(store.path).get("fixture")
    assert row["status"] == "completed" and not row["attestation"]["verified"]
    assert row["attestation"]["artifact_integrity"] != "verified"


def test_invalid_artifact_commitment_and_nonfinite_request_do_not_mutate(store, tmp_path):
    create(store)
    store.claim("fixture", "owner", now=10)
    with pytest.raises(ValueError, match="artifact"):
        store.checkpoint(
            "fixture", "owner", status="completed", artifact_hashes={"relative": "bad"}, now=11
        )
    assert store.get("fixture")["status"] == "running"
    with pytest.raises(ValueError):
        store.create("fixture", {"budget": float("nan")}, "source", job_id="nan")
    assert store.get("nan") is None
