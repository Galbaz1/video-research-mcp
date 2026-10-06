"""Fixed-clock, cursor, deadline and actual ordinary-library persistence boundaries."""

import hashlib
import json
import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest
from pydantic import ValidationError

from video_research_mcp import live_finalize as finalizer
from video_research_mcp import live_monitor as monitoring
from video_research_mcp.corpus_index import connect
from video_research_mcp.live_replay import load, read, replay
from video_research_mcp.models.live import (
    FinalizeRequest, MonitorRequest, ReadRequest, ReplayRequest, SessionPin,
)
from video_research_mcp.tools.live import live_finalize, live_replay


@pytest.fixture
def fixture_request(tmp_path, monkeypatch, clean_config):
    """Four fixed original clocks and an independent 10 ms alignment oracle."""
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))
    sources, events = [], []
    specs = [("speech", "s1", "1/48000", 48000, 0, "inferred"),
             ("OCR", "o1", "1/1000", 1000, 10000, "inferred"),
             ("frame", "f1", "1/90000", 90000, 5000, "observed"),
             ("browser", "b1", "1/1000", 500, 500000, "observed")]
    for kind, identity, time_base, ticks, offset, basis in specs:
        path = tmp_path / f"{identity}.original"
        raw = f"fixed independent fixture original {kind}".encode()
        path.write_bytes(raw)
        sources.append({"source_id": identity, "revision": "original-r1", "path": str(path),
                        "sha256": hashlib.sha256(raw).hexdigest(), "time_base": time_base,
                        "offset_us": offset, "clock_basis": "observed" if kind == "frame" else "inferred",
                        "clock_description": "fixed fixture clock offset; no native acquisition claim"})
        event = {"event_id": identity, "source_id": identity, "kind": kind, "basis": basis,
                 "timestamp_ticks": ticks, "duration_ticks": 0, "reference_us": 1_000_000,
                 "text": f"fixture {kind} evidence"}
        if kind == "browser":
            event["category"] = "console"
        events.append(event)
    return ReplayRequest(store_dir=str(tmp_path / "replays"), session_id="fixed-session", revision="r1",
                         clock_id="media-clock", tolerance_us=10000, sources=sources, events=events,
                         queue={"depth": 2, "dropped_frames": 3, "dropped_events": None, "basis": "source_reported"})


@pytest.fixture
def session(fixture_request):
    """Publish real local fixture bytes through the production replay path."""
    return SessionPin.model_validate(replay(fixture_request)["data"]["pin"])


def test_four_clock_alignment_preserves_original_basis_and_ticks(fixture_request, session):
    """GIVEN independent clocks WHEN replayed THEN the frozen 10 ms oracle holds."""
    result = read(ReadRequest(pin=session, limit=4))
    events = result["data"]["events"]
    assert [e["event_id"] for e in events] == ["b1", "s1", "f1", "o1"]
    expected = {"b1": Fraction(1), "s1": Fraction(1), "f1": Fraction(201, 200), "o1": Fraction(101, 100)}
    originals = {e.event_id: e for e in fixture_request.events}
    for event in events:
        assert Fraction(event["media_seconds_exact"]) == expected[event["event_id"]]
        assert abs(Fraction(event["media_seconds_exact"]) - 1) <= Fraction(1, 100)
        assert event["timestamp_ticks"] == originals[event["event_id"]].timestamp_ticks
        assert event["basis"] == originals[event["event_id"]].basis
    assert events[2]["clock_basis"] == "observed"
    assert events[0]["clock_basis"] == "inferred"
    assert result["recording_started"] is False


def test_fractional_clock_does_not_round_original_ticks(fixture_request):
    """GIVEN a thirds clock WHEN aligned THEN rational precision survives serialization."""
    value = fixture_request.model_dump()
    value["sources"] = [value["sources"][0]]
    value["sources"][0].update(time_base="1/3", offset_us=0)
    value["events"] = [value["events"][0]]
    value["events"][0].update(timestamp_ticks=1, reference_us=333333)
    value["tolerance_us"] = 1
    pin = SessionPin.model_validate(replay(ReplayRequest.model_validate(value))["data"]["pin"])
    event = read(ReadRequest(pin=pin))["data"]["events"][0]
    assert event["media_seconds_exact"] == "1/3"
    assert event["alignment_error_us_exact"] == "1/3"


def test_outside_frozen_tolerance_fails_before_any_write(fixture_request):
    value = fixture_request.model_dump()
    value["tolerance_us"] = 9999
    with pytest.raises(ValidationError, match="alignment tolerance"):
        ReplayRequest.model_validate(value)
    assert not Path(fixture_request.store_dir).exists()


def test_cursor_repeat_next_eof_and_queue_are_explicit(session):
    first = read(ReadRequest(pin=session, limit=2))["data"]
    assert read(ReadRequest(pin=session, cursor=first["cursor"], limit=2))["data"] == first
    second = read(ReadRequest(pin=session, cursor=first["next_cursor"], limit=2))["data"]
    assert [e["event_id"] for e in first["events"] + second["events"]] == ["b1", "s1", "f1", "o1"]
    assert first["queue"] == {"depth": 2, "dropped_frames": 3, "dropped_events": None, "basis": "source_reported"}
    assert first["remaining_events"] == 2
    assert not second["has_more"]
    eof = read(ReadRequest(pin=session, cursor=second["next_cursor"], limit=2))["data"]
    assert eof["events"] == []
    assert eof["next_cursor"] == second["next_cursor"]


def test_absent_queue_telemetry_remains_unknown(fixture_request):
    value = fixture_request.model_dump()
    value["queue"] = {}
    pin = SessionPin.model_validate(replay(ReplayRequest.model_validate(value))["data"]["pin"])
    result = read(ReadRequest(pin=pin))["data"]
    assert result["queue"] == {"depth": None, "dropped_frames": None, "dropped_events": None, "basis": "unknown"}


def test_cursor_rejects_changed_page_size_or_archive(session):
    cursor = read(ReadRequest(pin=session, limit=2))["data"]["next_cursor"]
    with pytest.raises(ValueError, match="page size"):
        read(ReadRequest(pin=session, cursor=cursor, limit=1))
    with pytest.raises(ValueError, match="page boundary"):
        read(ReadRequest(pin=session, cursor=f"{session.sha256}:2:1", limit=2))
    Path(session.path).write_bytes(b"changed source archive")
    with pytest.raises(ValueError, match="SHA256 mismatch"):
        read(ReadRequest(pin=session, cursor=cursor, limit=2))


def test_pinned_archive_rejects_coerced_retained_size(session):
    value = json.loads(Path(session.path).read_bytes())
    value["retained"]["s1"]["bytes"] = True
    raw = json.dumps(value).encode()
    Path(session.path).write_bytes(raw)
    pin = session.model_copy(update={"sha256": hashlib.sha256(raw).hexdigest()})
    with pytest.raises(ValidationError):
        read(ReadRequest(pin=pin))


def test_restart_reads_same_page_in_fresh_dummy_subprocess(session):
    """GIVEN durable bytes WHEN a new Python process reads THEN no in-memory queue is needed."""
    expected = read(ReadRequest(pin=session, limit=2))["data"]
    code = (
        "import json,sys; from pathlib import Path; import video_research_mcp.dotenv as d; "
        "d.DEFAULT_ENV_PATH=Path('/nonexistent-r173-unit-env'); "
        "from video_research_mcp.models.live import SessionPin,ReadRequest; "
        "from video_research_mcp.live_replay import read; "
        "print(json.dumps(read(ReadRequest(pin=SessionPin.model_validate_json(sys.argv[1]),limit=2))['data']))"
    )
    result = subprocess.run([sys.executable, "-c", code, session.model_dump_json()],
                            env={**os.environ, "PYTHONPATH": "src", "PYTHONDONTWRITEBYTECODE": "1"},
                            capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(result.stdout) == expected


def test_max_checks_stops_with_unmet_condition_and_resumable_cursor(session):
    request = MonitorRequest(pin=session, limit=1, kind="OCR", contains="absent", max_checks=2,
                             deadline_seconds=10.0)
    result = monitoring.monitor(request)
    assert result["status"] == "condition_unmet"
    assert result["data"]["reason"] == "max_checks"
    assert result["data"]["checks"] == 2
    remaining = read(ReadRequest(pin=session, limit=1, cursor=result["data"]["next_cursor"]))
    assert remaining["data"]["events"][0]["event_id"] == "f1"


def test_deadline_stops_before_consuming_late_page(session, monkeypatch):
    """GIVEN a clock crossing the deadline WHEN a page finishes THEN its cursor is unconsumed."""
    clock = iter([0.0, 0.1, 1.0])
    monkeypatch.setattr(monitoring.time, "monotonic", lambda: next(clock))
    result = monitoring.monitor(MonitorRequest(pin=session, limit=1, kind="browser",
                                               max_checks=10, deadline_seconds=1.0))
    assert result["status"] == "condition_unmet"
    assert result["data"]["reason"] == "deadline"
    assert result["data"]["checks"] == 0
    assert result["data"]["next_cursor"] is None
    assert result["data"]["matches"] == []


def test_monitor_literal_count_success_and_end_of_replay(session):
    found = monitoring.monitor(MonitorRequest(pin=session, limit=4, kind="speech", contains="fixture",
                                              max_checks=2, deadline_seconds=10.0))
    assert found["status"] == "condition_met"
    assert found["data"]["matches"][0]["basis"] == "inferred"
    unmet = monitoring.monitor(MonitorRequest(pin=session, limit=4, kind="speech", min_matches=2,
                                              max_checks=2, deadline_seconds=10.0))
    assert unmet["data"]["reason"] == "end_of_replay"
    assert unmet["status"] == "condition_unmet"


def test_finalize_ordinary_library_retains_bytes_and_exact_timestamps(session, fixture_request, tmp_path):
    """GIVEN original fixtures WHEN stopped/finalized THEN the real library stores pinned evidence."""
    before = Path(session.path).read_bytes()
    for source in fixture_request.sources:
        Path(source.path).unlink()
    request = FinalizeRequest(pin=session, index_path=str(tmp_path / "library.sqlite3"),
                              collection="ordinary", expected_revision=0)
    result = finalizer.finalize(request)
    assert result["status"] == "finalized"
    assert result["data"]["reprocessed"] is False
    assert Path(session.path).read_bytes() == before
    assert finalizer.finalize(request) == result
    with connect(request.index_path) as db:
        rows = db.execute("SELECT payload FROM observations ORDER BY observation").fetchall()
        assert db.execute("SELECT revision FROM collections WHERE name='ordinary'").fetchone()[0] == 1
    assert len(rows) == 4
    for row in rows:
        observation = json.loads(row["payload"])
        assert observation["source_revision"] == "original-r1"
        archive_ref = observation["artifact_refs"][1]
        assert hashlib.sha256(Path(archive_ref["path"]).read_bytes()).hexdigest() == session.sha256
    assert [e["timestamp_ticks"] for e in json.loads(before)["request"]["events"]] == [48000, 1000, 90000, 500]
    assert finalizer.stop(session) == finalizer.stop(session)


async def test_finalize_tampered_retained_bytes_fails_before_library_write(session, tmp_path):
    archive = load(session)
    Path(archive["retained"]["s1"]["path"]).write_bytes(b"tampered")
    index = tmp_path / "library.sqlite3"
    result = await live_finalize(FinalizeRequest(pin=session, index_path=str(index), collection="ordinary", expected_revision=0))
    assert "integrity mismatch" in result["error"]
    assert not index.exists()
    assert not Path(session.path + ".finalize-intent.json").exists()


def test_post_commit_receipt_failure_reconciles_without_reindexing(session, tmp_path, monkeypatch):
    """GIVEN a committed library and failed receipt WHEN resumed THEN readback establishes custody."""
    request = FinalizeRequest(pin=session, index_path=str(tmp_path / "library.sqlite3"),
                              collection="ordinary", expected_revision=0)
    original_publish = finalizer._publish_exact

    def fail_receipt(path, value):
        if str(path).endswith(".finalized.json"):
            raise OSError("fixture receipt interruption")
        original_publish(path, value)

    monkeypatch.setattr(finalizer, "_publish_exact", fail_receipt)
    with pytest.raises(OSError, match="receipt interruption"):
        finalizer.finalize(request)
    monkeypatch.setattr(finalizer, "_publish_exact", original_publish)
    monkeypatch.setattr(finalizer, "mutate", lambda _: pytest.fail("must not reindex interrupted intent"))
    result = finalizer.finalize(request)
    assert result["status"] == "finalized"
    with connect(request.index_path) as db:
        assert db.execute("SELECT count(*) FROM observations").fetchone()[0] == 4


def test_occupied_pre_effect_intent_is_unresolved_without_retry(session, tmp_path, monkeypatch):
    request = FinalizeRequest(pin=session, index_path=str(tmp_path / "library.sqlite3"),
                              collection="ordinary", expected_revision=0)

    def fail_effect(_):
        raise OSError("fixture unavailable library")

    monkeypatch.setattr(finalizer, "mutate", fail_effect)
    with pytest.raises(OSError, match="unavailable library"):
        finalizer.finalize(request)
    monkeypatch.setattr(finalizer, "mutate", lambda _: pytest.fail("must not retry occupied intent"))
    assert finalizer.finalize(request)["status"] == "unresolved"
    assert not Path(request.index_path).exists()


def test_changed_finalization_destination_is_refused(session, tmp_path):
    request = FinalizeRequest(pin=session, index_path=str(tmp_path / "library.sqlite3"),
                              collection="ordinary", expected_revision=0)
    finalizer.finalize(request)
    with pytest.raises(ValueError, match="conflicts with durable intent"):
        finalizer.finalize(request.model_copy(update={"collection": "different"}))


def test_corrupt_final_receipt_cannot_promote_wrong_evidence(session, tmp_path):
    request = FinalizeRequest(pin=session, index_path=str(tmp_path / "library.sqlite3"),
                              collection="ordinary", expected_revision=0)
    finalizer.finalize(request)
    receipt = Path(session.path + ".finalized.json")
    receipt.write_text('{"status":"finalized","data":{"pin":"wrong-source"}}')
    with pytest.raises(ValueError, match="receipt integrity mismatch"):
        finalizer.finalize(request)
    assert "wrong-source" in receipt.read_text()


def test_missing_library_after_receipt_is_unresolved_without_retry(session, tmp_path, monkeypatch):
    request = FinalizeRequest(pin=session, index_path=str(tmp_path / "library.sqlite3"),
                              collection="ordinary", expected_revision=0)
    finalizer.finalize(request)
    Path(request.index_path).unlink()
    monkeypatch.setattr(finalizer, "mutate", lambda _: pytest.fail("must not reindex missing library"))
    assert finalizer.finalize(request)["status"] == "unresolved"


def test_new_session_revision_retains_both_library_epochs(fixture_request, tmp_path):
    """GIVEN revised replay evidence WHEN finalized THEN the old immutable library epoch survives."""
    value = fixture_request.model_dump()
    value["session_id"] = "s" * 64
    value["events"][0]["event_id"] = "e" * 64
    first = ReplayRequest.model_validate(value)
    index = str(tmp_path / "library.sqlite3")
    for revision, expected in [("r1", 0), ("r2", 1)]:
        value["revision"] = revision
        pin = SessionPin.model_validate(replay(ReplayRequest.model_validate(value))["data"]["pin"])
        assert finalizer.finalize(FinalizeRequest(pin=pin, index_path=index, collection="ordinary",
                                                expected_revision=expected))["status"] == "finalized"
    with connect(index) as db:
        rows = db.execute("SELECT observation,payload FROM observations").fetchall()
    assert len(rows) == 8
    assert all(len(row["observation"]) <= 128 for row in rows)
    assert len({row["observation"] for row in rows}) == 8
    assert {Path(json.loads(row["payload"])["artifact_refs"][1]["path"]).name for row in rows} == {
        f"{first.session_id}.r1.json", f"{first.session_id}.r2.json"}


def test_original_byte_ceiling_refuses_before_publishing(fixture_request):
    value = fixture_request.model_dump()
    raw = b"x" * (2 * 1024 * 1024 + 1)
    Path(value["sources"][0]["path"]).write_bytes(raw)
    value["sources"][0]["sha256"] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(ValueError, match="byte ceiling"):
        replay(ReplayRequest.model_validate(value))
    assert not Path(fixture_request.store_dir).exists()


async def test_source_mismatch_and_immutable_revision_conflict_are_structured(fixture_request):
    bad = fixture_request.model_dump()
    bad["sources"][0]["sha256"] = "0" * 64
    result = await live_replay(ReplayRequest.model_validate(bad))
    assert "SHA256 mismatch" in result["error"]
    assert not Path(fixture_request.store_dir).exists()
    replay(fixture_request)
    changed = fixture_request.model_dump()
    changed["events"][0]["text"] = "changed evidence"
    result = await live_replay(ReplayRequest.model_validate(changed))
    assert "Immutable live session conflict" in result["error"]


def test_symlink_and_local_root_escape_are_refused(fixture_request, tmp_path):
    value = fixture_request.model_dump()
    link = tmp_path / "link.original"
    link.symlink_to(value["sources"][0]["path"])
    value["sources"][0]["path"] = str(link)
    with pytest.raises(PermissionError, match="symlinks"):
        replay(ReplayRequest.model_validate(value))
    value = fixture_request.model_dump()
    value["store_dir"] = str(tmp_path.parent / "outside-r173-owned-root")
    with pytest.raises(PermissionError, match="outside LOCAL_FILE_ACCESS_ROOT"):
        replay(ReplayRequest.model_validate(value))
