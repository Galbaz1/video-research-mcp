"""Measured cold-start races and saturation must preserve simulated stop controls."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sqlite3
from threading import Barrier

import pytest

from video_research_mcp.hardware_simulator import SimulatedHardware


def simulator(directory):
    """Use actual private SQLite and artifact files in a fresh test directory."""
    return SimulatedHardware(directory / "hardware.sqlite3", directory / "artifacts",
                             directory / "approval.json", check=lambda: None)


@pytest.mark.parametrize("target", ["database", "directory"])
def test_synchronized_cold_creation_joins_two_actual_owners(tmp_path, monkeypatch, target):
    barrier = Barrier(2, timeout=5)
    if target == "database":
        (tmp_path / "artifacts").mkdir()
        original = os.open

        def create(path, flags, *args, **kwargs):
            if path == tmp_path / "hardware.sqlite3" and flags & os.O_EXCL:
                barrier.wait()
            return original(path, flags, *args, **kwargs)

        monkeypatch.setattr(os, "open", create)
    else:
        original = Path.mkdir

        def create(path, *args, **kwargs):
            if path == tmp_path / "artifacts":
                barrier.wait()
            return original(path, *args, **kwargs)

        monkeypatch.setattr(Path, "mkdir", create)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(simulator, tmp_path) for _ in range(2)]
        owners = [future.result(timeout=10) for future in futures]
    assert owners[0].discover() == owners[1].discover()
    assert len(owners[0].discover()["devices"]) == 2


def test_saturated_normal_history_still_stops_both_devices_and_replays(tmp_path):
    owner = simulator(tmp_path)
    for number in range(510):
        assert owner.write("simulator/lamp", "brightness", {"brightness": 10},
                           f"ordinary-{number}")["status"] == "executed"
    overflow = owner.write("simulator/lamp", "brightness", {"brightness": 20}, "overflow")
    assert overflow["status"] == "refused" and overflow["recorded"] is False
    receipts = [owner.reset(device, "estop", f"stop-{index}") for index, device in
                enumerate(("simulator/lamp", "simulator/camera"))]
    restarted = simulator(tmp_path)
    for index, device in enumerate(("simulator/lamp", "simulator/camera")):
        assert receipts[index]["status"] == "executed"
        assert restarted.reset(device, "estop", f"stop-{index}") == receipts[index]
        assert restarted.meta(device)["state"]["outputs_enabled"] is False
        recovery = restarted.reset(device, "soft", f"full-recovery-{index}")
        assert recovery["status"] == "refused" and recovery["action_attempted"] is False
        assert restarted.meta(device)["state"]["mode"] == "estopped"
    with sqlite3.connect(tmp_path / "hardware.sqlite3") as connection:
        assert connection.execute("SELECT COUNT(*) FROM hardware_commands").fetchone()[0] == 512


def test_pending_approved_recovery_cannot_consume_its_future_stop_slot(tmp_path):
    owner = simulator(tmp_path)
    for index, device in enumerate(("simulator/lamp", "simulator/camera")):
        assert owner.reset(device, "estop", f"stop-{index}")["status"] == "executed"
    pending = owner.reset("simulator/lamp", "soft", "recover")
    assert pending["status"] == "approval_required"
    for number in range(509):
        refused = owner.write("simulator/lamp", "brightness", {"brightness": 10},
                              f"stopped-write-{number}")
        assert refused["status"] == "refused" and refused["recorded"] is True
    approval = tmp_path / "approval.json"
    approval.write_text(json.dumps({"approved_commands": [pending["commitment_sha256"]]}))
    approval.chmod(0o600)
    refused = owner.reset("simulator/lamp", "soft", "recover")
    assert refused["status"] == "refused" and refused["recorded"] is True
    assert refused["action_attempted"] is False
    assert simulator(tmp_path).reset("simulator/lamp", "soft", "recover") == refused
    assert owner.meta("simulator/lamp")["state"]["mode"] == "estopped"
