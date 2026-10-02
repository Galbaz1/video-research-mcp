"""Actual bounded simulator storage, exact host authority, stop and image evidence."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import stat
import struct
import zlib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from video_research_mcp.hardware_authority import canonical, digest, host_approval
from video_research_mcp.hardware_simulator import CAPABILITIES, SimulatedHardware


def core(tmp_path: Path, check=lambda: None) -> SimulatedHardware:
    """Construct one owned core without any physical, network or provider route."""
    return SimulatedHardware(tmp_path / "hardware.sqlite3", tmp_path / "artifacts",
                             tmp_path / "approval.json", check=check)


def approve(simulator, *receipts):
    """Act as the test's external host operator, never through a public tool argument."""
    path = simulator.authority_file
    path.write_bytes(canonical({"approved_commands": [r["commitment_sha256"] for r in receipts]}))
    path.chmod(0o600)


def row_count(tmp_path):
    with sqlite3.connect(tmp_path / "hardware.sqlite3") as connection:
        return connection.execute("SELECT COUNT(*) FROM hardware_commands").fetchone()[0]


def test_registered_metadata_filters_and_actual_defaults(tmp_path):
    simulator = core(tmp_path)
    discovered = simulator.discover()
    assert [d["device_id"] for d in discovered["devices"]] == ["simulator/lamp", "simulator/camera"]
    lamp = simulator.meta("simulator/lamp")
    assert lamp["state"] == {"revision": 0, "mode": "online", "outputs_enabled": True,
                             "values": {"on": False, "brightness": 0}}
    assert lamp["state_sha256"] == digest(lamp["state"])
    assert lamp["capabilities"]["brightness"]["hard"] == [0, 100]
    assert lamp["capabilities"]["brightness"]["soft"] == [0, 80]
    assert lamp["capabilities"]["power"]["requires_authority"] is True
    camera = simulator.meta("simulator/camera")
    assert camera["capabilities"]["image"]["direction"] == "read"
    assert camera["capabilities"]["exposure"]["soft"] == [1, 30]
    assert simulator.discover("lamp", "local")["devices"][0]["device_id"] == "simulator/lamp"
    assert simulator.discover(tag="physical")["devices"] == []
    assert lamp["origin"] == "simulated" and lamp["physical_qualified"] is False
    assert lamp["calibration_verified"] is False and lamp["safety_qualified"] is False


def test_write_receipt_restart_replay_and_json_parameter_commitments(tmp_path):
    simulator = core(tmp_path)
    before = simulator.meta("simulator/lamp")["state"]
    receipt = simulator.write("simulator/lamp", "brightness", {"brightness": 40}, "ordinary")
    assert receipt["status"] == "executed" and receipt["terminal"] and receipt["action_attempted"]
    assert receipt["before"]["state"] == before
    assert receipt["after"]["state"]["values"]["brightness"] == 40
    assert receipt["after"]["state"]["revision"] == 1
    assert receipt["before"]["state_sha256"] == digest(before)
    assert receipt["after"]["state_sha256"] == digest(receipt["after"]["state"])
    assert receipt["params"] == {"brightness": 40} and receipt["effective_limits"]["hard"] == [0, 100]
    assert receipt["intent_sha256"] == digest(receipt["intent"])
    assert receipt["commitment_sha256"] == digest(receipt["proposal"])
    fresh = core(tmp_path)
    assert fresh.write("simulator/lamp", "brightness", {"brightness": 40}, "ordinary") == receipt
    assert row_count(tmp_path) == 1 and fresh.meta("simulator/lamp")["state"]["revision"] == 1


@pytest.mark.parametrize("value", [-1, 101, True, "40", float("nan"), float("inf"), None])
def test_whole_numeric_hard_failure_is_durable_without_value_mutation(tmp_path, value):
    simulator = core(tmp_path)
    before = simulator.meta("simulator/lamp")
    receipt = simulator.write("simulator/lamp", "brightness", {"brightness": value}, "invalid", confirm=True)
    assert receipt["status"] == "refused" and receipt["recorded"] and not receipt["action_attempted"]
    after = simulator.meta("simulator/lamp")
    assert after["state"] == before["state"] and after["state_sha256"] == before["state_sha256"]
    assert after["audit"]["health_required"] is True
    assert core(tmp_path).write("simulator/lamp", "brightness", {"brightness": value}, "invalid", confirm=True) == receipt
    assert row_count(tmp_path) == 1


@pytest.mark.parametrize("capability,params", [("brightness", {}), ("brightness", {"brightness": 20, "unknown": 1}),
    ("power", {"on": 1}), ("missing", {"x": 1}), ("brightness", {"brightness": {"invalid_nonfinite_number": "nan"}})])
def test_unknown_or_wrong_shape_params_are_not_partially_applied(tmp_path, capability, params):
    simulator = core(tmp_path)
    assert simulator.write("simulator/lamp", capability, params, "badshape")["status"] == "refused"
    metadata = simulator.meta("simulator/lamp")
    assert metadata["state"]["revision"] == 0 and metadata["audit"]["health_required"]


def test_readonly_direction_and_unknown_device_never_mutate(tmp_path):
    simulator = core(tmp_path)
    receipt = simulator.write("simulator/camera", "image", {}, "wrongdirection")
    assert receipt["status"] == "refused" and simulator.meta("simulator/camera")["audit"]["health_required"]
    assert simulator.write("physical/camera", "exposure", {"exposure_ms": 20}, "unknown")["status"] == "refused"
    assert simulator.read("simulator/lamp", "brightness", {"value": 1})["status"] == "refused"
    assert simulator.meta("camera")["status"] == "refused"


def test_health_gate_survives_restart_and_requires_actual_explicit_health(tmp_path):
    simulator = core(tmp_path)
    simulator.write("simulator/lamp", "brightness", {"brightness": 101}, "hard")
    fresh = core(tmp_path)
    blocked = fresh.write("simulator/lamp", "brightness", {"brightness": 30}, "blocked")
    assert blocked["status"] == "refused" and fresh.meta("simulator/lamp")["state"]["revision"] == 0
    evidence = fresh.health("simulator/lamp")["devices"][0]
    assert evidence["simulated"] and evidence["generation"] == 1 and evidence["checked_at_ns"] > 0
    assert evidence["state_sha256"] == fresh.meta("simulator/lamp")["state_sha256"]
    assert fresh.meta("simulator/lamp")["audit"]["health_required"] is False
    assert fresh.write("simulator/lamp", "brightness", {"brightness": 30}, "blocked") == blocked
    assert fresh.write("simulator/lamp", "brightness", {"brightness": 30}, "fresh")["status"] == "executed"


@pytest.mark.parametrize("device,capability,params", [("simulator/lamp", "power", {"on": True}),
    ("simulator/lamp", "brightness", {"brightness": 90}), ("simulator/camera", "exposure", {"exposure_ms": 50})])
def test_pending_host_proposal_can_resume_exactly_once_even_without_model_confirm(tmp_path, device, capability, params):
    simulator = core(tmp_path)
    before = simulator.meta(device)["state"]
    pending = simulator.write(device, capability, params, "review", confirm=False)
    assert pending["status"] == "approval_required" and not pending["terminal"] and not pending["action_attempted"]
    assert pending["before"]["state"] == pending["after"]["state"] == before
    assert pending["proposal"]["state_revision"] == before["revision"]
    assert pending["commitment_sha256"] == digest(pending["proposal"])
    assert simulator.meta(device)["audit"]["health_required"] is False
    approve(simulator, pending)
    original_authority = simulator.authority_file.read_bytes()
    executed = core(tmp_path).write(device, capability, params, "review", confirm=False)
    assert executed["status"] == "executed" and executed["after"]["state"]["revision"] == 1
    assert executed["authority"]["consumed_by_command_id"] == "review"
    assert simulator.authority_file.read_bytes() == original_authority
    assert simulator.write(device, capability, params, "review", confirm=False) == executed
    with sqlite3.connect(tmp_path / "hardware.sqlite3") as connection:
        assert connection.execute("SELECT approval_sha FROM hardware_commands WHERE id='review'").fetchone()[0] == pending["commitment_sha256"]


def test_model_confirm_cannot_grant_external_authority_or_change_bound_intent(tmp_path):
    simulator = core(tmp_path)
    pending = simulator.write("simulator/lamp", "power", {"on": True}, "confirm", confirm=True)
    assert pending["status"] == "approval_required" and simulator.meta("simulator/lamp")["state"]["values"]["on"] is False
    assert simulator.write("simulator/lamp", "power", {"on": True}, "confirm", confirm=False)["status"] == "refused"
    simulator.health("simulator/lamp")
    approve(simulator, pending)
    assert simulator.write("simulator/lamp", "power", {"on": True}, "confirm", confirm=True)["status"] == "executed"


def test_stale_state_approval_fails_and_preserves_current_value(tmp_path):
    simulator = core(tmp_path)
    pending = simulator.write("simulator/lamp", "brightness", {"brightness": 90}, "stale")
    simulator.write("simulator/lamp", "brightness", {"brightness": 20}, "intervene")
    approve(simulator, pending)
    refused = simulator.write("simulator/lamp", "brightness", {"brightness": 90}, "stale")
    assert refused["status"] == "refused" and "stale" in refused["error"]["message"]
    assert refused["commitment_sha256"] == pending["commitment_sha256"]
    assert simulator.meta("simulator/lamp")["state"]["values"]["brightness"] == 20
    assert core(tmp_path).write("simulator/lamp", "brightness", {"brightness": 90}, "stale") == refused


def test_stale_effective_limit_approval_fails_before_action(tmp_path, monkeypatch):
    simulator = core(tmp_path)
    pending = simulator.write("simulator/lamp", "brightness", {"brightness": 90}, "limit")
    approve(simulator, pending)
    monkeypatch.setitem(CAPABILITIES["simulator/lamp"]["brightness"], "hard", [0, 99])
    receipt = simulator.write("simulator/lamp", "brightness", {"brightness": 90}, "limit")
    assert receipt["status"] == "refused" and "stale" in receipt["error"]["message"]
    assert simulator.meta("simulator/lamp")["state"]["revision"] == 0


@pytest.mark.parametrize("case", ["wide_mode", "symlink", "oversized", "extra", "duplicates", "too_many", "malformed"])
def test_host_file_invalidity_cannot_authorize_state_changes(tmp_path, case):
    simulator = core(tmp_path)
    pending = simulator.write("simulator/lamp", "power", {"on": True}, "authority")
    approve(simulator, pending)
    path = simulator.authority_file
    if case == "wide_mode":
        path.chmod(0o644)
    elif case == "symlink":
        other = tmp_path / "other.json"
        path.rename(other)
        path.symlink_to(other)
    elif case == "oversized":
        path.write_bytes(b" " * 17000 + path.read_bytes())
    elif case == "extra":
        path.write_bytes(canonical({"approved_commands": [pending["commitment_sha256"]], "trusted": True}))
    elif case == "duplicates":
        path.write_text('{"approved_commands":[],"approved_commands":["' + pending["commitment_sha256"] + '"]}')
    elif case == "too_many":
        path.write_bytes(canonical({"approved_commands": [f"{n:064x}" for n in range(65)]}))
    else:
        path.write_bytes(b"not json")
    result = simulator.write("simulator/lamp", "power", {"on": True}, "authority")
    assert result["status"] == "approval_required" and not result["action_attempted"]
    assert simulator.meta("simulator/lamp")["state"]["revision"] == 0
    assert host_approval(path, pending["commitment_sha256"])["authorized"] is False


def test_estop_is_latched_outputs_off_and_host_recovery_resets_defaults(tmp_path):
    simulator = core(tmp_path)
    simulator.write("simulator/camera", "exposure", {"exposure_ms": 20}, "expose")
    stopped = simulator.reset("simulator/camera", "estop", "stop")
    assert stopped["status"] == "executed" and stopped["after"]["state"]["mode"] == "estopped"
    assert stopped["after"]["state"]["outputs_enabled"] is False
    assert simulator.read("simulator/camera", "image", {})["status"] == "refused"
    assert simulator.write("simulator/camera", "exposure", {"exposure_ms": 10}, "stopped-write")["status"] == "refused"
    assert simulator.health("simulator/camera")["devices"][0]["mode"] == "estopped"
    recovery = simulator.reset("simulator/camera", "soft", "recover")
    assert recovery["status"] == "approval_required" and simulator.meta("simulator/camera")["state"]["mode"] == "estopped"
    approve(simulator, recovery)
    recovered = core(tmp_path).reset("simulator/camera", "soft", "recover")
    assert recovered["status"] == "executed"
    assert recovered["after"]["state"]["mode"] == "online" and recovered["after"]["state"]["outputs_enabled"]
    assert recovered["after"]["state"]["values"] == {"exposure_ms": 10}
    assert simulator.reset("simulator/camera", "estop", "stop") == stopped
    assert simulator.meta("simulator/camera")["state"]["mode"] == "online"


def test_estop_turns_lamp_output_off_even_when_failure_gate_is_set(tmp_path):
    simulator = core(tmp_path)
    pending = simulator.write("simulator/lamp", "power", {"on": True}, "on")
    approve(simulator, pending)
    simulator.write("simulator/lamp", "power", {"on": True}, "on")
    simulator.write("simulator/lamp", "brightness", {"brightness": 101}, "bad")
    stopped = simulator.reset("simulator/lamp", "estop", "stop")
    assert stopped["status"] == "executed" and stopped["after"]["state"]["values"] == {"on": False, "brightness": 0}


def test_concurrent_exact_identity_executes_once_and_writes_serialize(tmp_path):
    simulators = [core(tmp_path), core(tmp_path)]
    with ThreadPoolExecutor(max_workers=8) as executor:
        same = list(executor.map(lambda i: simulators[i % 2].write("simulator/lamp", "brightness", {"brightness": 10}, "same"), range(12)))
    assert all(result == same[0] for result in same) and row_count(tmp_path) == 1
    with ThreadPoolExecutor(max_workers=8) as executor:
        receipts = list(executor.map(lambda i: simulators[i % 2].write("simulator/lamp", "brightness", {"brightness": i}, f"parallel-{i}"), range(12)))
    ordered = sorted(receipts, key=lambda r: r["after"]["state"]["revision"])
    assert [r["after"]["state"]["revision"] for r in ordered] == list(range(2, 14))
    assert all(left["after"]["state_sha256"] == right["before"]["state_sha256"] for left, right in zip(ordered, ordered[1:]))
    assert row_count(tmp_path) == 13


def test_camera_png_and_immutable_state_snapshot_have_exact_owned_bytes(tmp_path):
    simulator = core(tmp_path)
    result = simulator.read("simulator/camera", "image", {})
    artifact, source = result["artifact"], result["source"]
    data = Path(artifact["path"]).read_bytes()
    assert artifact["sha256"] == hashlib.sha256(data).hexdigest() and artifact["bytes"] == len(data)
    assert data[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(">II", data[16:24]) == (32, 24)
    position, pixels, ended = 8, b"", False
    while position < len(data):
        size = struct.unpack(">I", data[position:position + 4])[0]
        kind, payload = data[position + 4:position + 8], data[position + 8:position + 8 + size]
        assert struct.unpack(">I", data[position + 8 + size:position + 12 + size])[0] == zlib.crc32(kind + payload)
        pixels += payload if kind == b"IDAT" else b""
        ended = ended or kind == b"IEND"
        position += 12 + size
    raw = zlib.decompress(pixels)
    assert ended and len(raw) == 24 * (1 + 32 * 3) and all(raw[y * 97] == 0 for y in range(24))
    assert Path(source["path"]).read_bytes() == canonical(json.loads(Path(source["path"]).read_bytes()))
    assert source["sha256"] == hashlib.sha256(Path(source["path"]).read_bytes()).hexdigest()
    assert json.loads(Path(source["path"]).read_bytes())["state"] == result["state"]
    assert result["asset_kind"] == "synthetic" and result["physical_qualified"] is False
    assert core(tmp_path).read("simulator/camera", "image", {}) == result
    assert len(list((tmp_path / "artifacts").iterdir())) == 2
    assert all(stat.S_IMODE(Path(record["path"]).stat().st_mode) == 0o600 for record in (artifact, source))
    assert simulator.read("simulator/camera", "sensor", {})["value"] == {"temperature": {"value": 22, "unit": "degC"}}


def test_tampered_image_is_not_overwritten_or_returned_as_verified(tmp_path):
    simulator = core(tmp_path)
    artifact = simulator.read("simulator/camera", "image", {})["artifact"]
    path = Path(artifact["path"])
    path.write_bytes(b"tampered")
    assert simulator.read("simulator/camera", "image", {})["status"] == "refused"
    assert path.read_bytes() == b"tampered"


def test_cancellation_before_command_commit_rolls_back_values_and_receipt(tmp_path):
    count = 0
    def check():
        nonlocal count
        count += 1
        if count == 3:
            raise TimeoutError("owned deadline")
    simulator = core(tmp_path)
    simulator.check = simulator.store.check = check
    with pytest.raises(TimeoutError, match="owned deadline"):
        simulator.write("simulator/lamp", "brightness", {"brightness": 40}, "cancel")
    fresh = core(tmp_path)
    assert fresh.meta("simulator/lamp")["state"]["revision"] == 0 and row_count(tmp_path) == 0


def test_cancellation_during_artifact_publication_removes_only_new_files(tmp_path):
    simulator = core(tmp_path)
    def check():
        if list((tmp_path / "artifacts").iterdir()):
            raise TimeoutError("owned publication deadline")
    simulator.check = simulator.store.check = check
    with pytest.raises(TimeoutError):
        simulator.read("simulator/camera", "image", {})
    assert list((tmp_path / "artifacts").iterdir()) == []


@pytest.mark.parametrize("kind", ["database", "artifact_directory", "artifact_file"])
def test_storage_symlink_substitutions_are_denied(tmp_path, kind):
    simulator = core(tmp_path)
    if kind == "database":
        path = tmp_path / "hardware.sqlite3"
        target = tmp_path / "other.sqlite3"
        path.rename(target)
        path.symlink_to(target)
        assert simulator.meta("simulator/lamp")["status"] == "failed"
    elif kind == "artifact_directory":
        path, target = tmp_path / "artifacts", tmp_path / "other-artifacts"
        path.rename(target)
        path.symlink_to(target, target_is_directory=True)
        assert simulator.read("simulator/camera", "image", {})["status"] == "failed"
    else:
        artifact = simulator.read("simulator/camera", "image", {})["artifact"]
        path, target = Path(artifact["path"]), tmp_path / "other.png"
        path.rename(target)
        path.symlink_to(target)
        assert simulator.read("simulator/camera", "image", {})["status"] == "failed"


def test_concrete_command_and_artifact_population_caps_have_no_automatic_deletion(tmp_path):
    simulator = core(tmp_path)
    for n in range(510):
        assert simulator.write("simulator/lamp", "brightness", {"brightness": 10}, f"bounded-{n}")["status"] == "executed"
    assert simulator.write("simulator/lamp", "brightness", {"brightness": 20}, "overflow")["status"] == "refused"
    assert row_count(tmp_path) == 510 and simulator.meta("simulator/lamp")["state"]["values"]["brightness"] == 10
    for n in range(64):
        (tmp_path / "artifacts" / f"owned-{n}").write_bytes(b"keep")
    assert simulator.read("simulator/camera", "image", {})["status"] == "refused"
    assert len(list((tmp_path / "artifacts").iterdir())) == 64
    for device in ("simulator/lamp", "simulator/camera"):
        assert simulator.reset(device, "estop", f"stop-{device.rsplit('/', 1)[1]}")["status"] == "executed"
    assert row_count(tmp_path) == 512


def test_invalid_bounded_envelope_sets_audit_gate_without_admitting_identity(tmp_path):
    simulator = core(tmp_path)
    result = simulator.write("simulator/lamp", "brightness", {"brightness": 20}, "", confirm=False)
    assert result["status"] == "refused" and result["recorded"] is False and not result["action_attempted"]
    assert row_count(tmp_path) == 0 and simulator.meta("simulator/lamp")["audit"]["health_required"] is True
