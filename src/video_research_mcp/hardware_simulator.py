"""Two truthful local simulated devices; no physical adapter or safety qualification."""

from __future__ import annotations

import copy
import math
import re
import sqlite3
import struct
import time
import zlib
from pathlib import Path

from .hardware_authority import canonical, digest, host_approval
from .hardware_store import DEFAULTS, HardwareStore

CAPABILITIES = {
    "simulator/lamp": {
        "brightness": {"direction": "both", "write_params": {"brightness": "number"},
                       "hard": [0, 100], "soft": [0, 80], "unit": "%", "requires_authority": False},
        "power": {"direction": "both", "write_params": {"on": "boolean"}, "requires_authority": True}},
    "simulator/camera": {
        "exposure": {"direction": "both", "write_params": {"exposure_ms": "number"},
                     "hard": [1, 100], "soft": [1, 30], "unit": "ms", "requires_authority": False},
        "image": {"direction": "read", "read_params": {}},
        "sensor": {"direction": "read", "read_params": {}}}}
ORIGIN = {"origin": "simulated", "simulated": True, "asset_kind": "synthetic",
          "physical_qualified": False, "safety_qualified": False, "calibration_verified": False}


def _wire(value, depth=0):
    """Commit admitted bounded JSON types, distinguishing invalid nonfinite inputs."""
    if depth > 4:
        raise ValueError("Command JSON nesting exceeds four")
    if value is None or type(value) is bool:
        return [type(value).__name__, value]
    if type(value) in {int, float}:
        if type(value) is int and value.bit_length() > 256:
            raise ValueError("Command integer exceeds 256 bits")
        return [type(value).__name__, value if type(value) is int or math.isfinite(value) else str(value)]
    if type(value) is str and len(value) <= 512:
        return ["str", value]
    if type(value) is dict and len(value) <= 8 and all(type(k) is str and len(k) <= 128 for k in value):
        return ["dict", [[k, _wire(v, depth + 1)] for k, v in sorted(value.items())]]
    if type(value) is list and len(value) <= 8:
        return ["list", [_wire(v, depth + 1) for v in value]]
    raise ValueError("Command requires bounded JSON data")


def _portable(wire):
    """Keep ordinary params literal while representing refused nonfinite numbers honestly."""
    kind, value = wire
    if kind == "dict":
        return {k: _portable(v) for k, v in value}
    if kind == "list":
        return [_portable(v) for v in value]
    return {"invalid_nonfinite_number": value} if kind == "float" and type(value) is str else value


def _png(exposure) -> bytes:
    """Author a fixed 32-by-24 RGB gradient, explicitly synthetic and bounded."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    level = round(exposure * 2)
    rows = b"".join(b"\x00" + bytes(v for x in range(32) for v in
                       ((x * 7 + level) % 256, (y * 9 + level) % 256, level % 256)) for y in range(24))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 32, 24, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


class SimulatedHardware:
    """Persist deterministic simulator state and exact host-authorized command outcomes."""

    def __init__(self, database: Path, artifacts: Path, authority_file: Path | None, *, check):
        self.check, self.authority_file = check, authority_file
        self.store = HardwareStore(database, artifacts, check)

    def _run(self, operation):
        try:
            with self.store.transaction() as connection:
                return operation(connection)
        except TimeoutError:
            raise
        except ValueError as exc:
            return {**ORIGIN, "status": "refused", "action_attempted": False,
                    "recorded": False, "error": {"code": "preflight_refused", "message": str(exc)}}
        except (OSError, sqlite3.Error) as exc:
            return {**ORIGIN, "status": "failed", "action_attempted": False,
                    "recorded": False, "error": {"code": type(exc).__name__, "message": str(exc)}}

    def _meta(self, connection, device_id):
        state, audit = self.store.device(connection, device_id)
        return {**ORIGIN, "status": "ok", "adapter_id": "simulator", "device_id": device_id,
                "device_type": device_id.split("/")[1], "tags": ["simulated", "local"],
                "state": state, "state_sha256": digest(state), "audit": audit,
                "capabilities": copy.deepcopy(CAPABILITIES[device_id]),
                "limits": {"command_receipts": 512, "database_bytes": 4194304,
                           "artifact_files": 64, "artifact_bytes": 1048576},
                "physical_route": "unavailable_pending_named_owner_qualification"}

    def discover(self, device_type=None, tag=None) -> dict:
        """Return only the two registered simulator devices under exact optional filters."""
        def operation(connection):
            if any(v is not None and (type(v) is not str or not 1 <= len(v) <= 128)
                   for v in (device_type, tag)):
                raise ValueError("Discovery filters must be bounded strings or null")
            devices = [self._meta(connection, identifier) for identifier in DEFAULTS]
            return {**ORIGIN, "status": "ok", "devices": [d for d in devices if
                (device_type is None or d["device_type"] == device_type) and (tag is None or tag in d["tags"])]}
        return self._run(operation)

    def meta(self, device_id) -> dict:
        """Read current simulator values, directions, hard/soft limits and audit gates."""
        return self._run(lambda connection: self._meta(connection, device_id))

    def health(self, device_id=None) -> dict:
        """Obtain fresh simulated evidence and clear only the independent failure gate."""
        def operation(connection):
            identifiers = list(DEFAULTS) if device_id is None else [device_id]
            results = []
            for identifier in identifiers:
                state, audit = self.store.device(connection, identifier)
                evidence = {**ORIGIN, "device_id": identifier, "state_sha256": digest(state),
                    "state_revision": state["revision"], "checked_at_ns": time.time_ns(),
                    "time_source": "host_wallclock_untrusted", "healthy": True,
                    "mode": state["mode"], "generation": audit["health_generation"] + 1}
                audit.update(health_required=False, health_generation=evidence["generation"], last_health=evidence)
                self.store.update(connection, identifier, state, audit)
                results.append(evidence)
            return {**ORIGIN, "status": "ok", "devices": results}
        return self._run(operation)

    def read(self, device_id, capability, params) -> dict:
        """Read validated simulator values or owned PNG/state artifacts without linked access."""
        def operation(connection):
            metadata = self._meta(connection, device_id)
            if type(params) is not dict or params or capability not in CAPABILITIES[device_id]:
                raise ValueError("Read requires a declared capability and exactly empty params")
            state, values = metadata["state"], metadata["state"]["values"]
            result = {**ORIGIN, "status": "ok", "device_id": device_id, "capability": capability,
                      "state": state, "state_sha256": metadata["state_sha256"]}
            if capability == "image":
                if state["mode"] != "online":
                    raise ValueError("Image read is refused while emergency stop is latched")
                source = {**ORIGIN, "device_id": device_id, "state": state,
                          "effective_limits": CAPABILITIES[device_id]}
                stamp = digest(source)
                artifacts = self.store.publish({f"state-{stamp}.json": canonical(source),
                                                f"frame-{stamp}.png": _png(values["exposure_ms"])})
                result.update(source=artifacts[0], artifact={**artifacts[1], "mime_type": "image/png",
                                                          "width": 32, "height": 24})
            elif capability == "sensor":
                result["value"] = {"temperature": {"value": 22, "unit": "degC"}}
            else:
                key = next(iter(CAPABILITIES[device_id][capability]["write_params"]))
                result.update(value=values[key], unit=CAPABILITIES[device_id][capability].get("unit"))
            return result
        return self._run(operation)

    def _intent(self, device_id, capability, params, command_id, confirm, action) -> dict:
        if type(command_id) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", command_id):
            raise ValueError("A bounded explicit command_id is required")
        if type(device_id) is not str or len(device_id) > 128 or type(capability) is not str or len(capability) > 128:
            raise ValueError("Bounded device and capability strings are required")
        wire = _wire(params)
        intent = {"command_id": command_id, "adapter_id": "simulator", "device_id": device_id,
                  "action": action, "capability" if action == "write" else "mode": capability,
                  "params": _portable(wire), "params_wire": wire, "confirm": confirm}
        if type(confirm) is not bool or len(canonical(intent)) > 4096:
            raise ValueError("Command requires boolean confirm and at most 4 KiB of intent")
        return intent

    def _preflight(self, intent, state, audit) -> tuple[dict, bool]:
        if intent["action"] == "reset":
            if intent["mode"] not in {"soft", "estop"}:
                raise ValueError("Reset mode must be soft or estop")
            return {"reset": intent["mode"], "safe_defaults": DEFAULTS[intent["device_id"]]}, intent["mode"] == "soft"
        cap = CAPABILITIES[intent["device_id"]].get(intent["capability"])
        if cap is None or cap["direction"] == "read":
            raise ValueError("Capability is undeclared or not writable")
        params = intent["params"]
        if type(params) is not dict or set(params) != set(cap["write_params"]):
            raise ValueError("Write params must match the whole declared request")
        value = next(iter(params.values()))
        if "hard" in cap:
            if type(value) not in {int, float} or (type(value) is float and not math.isfinite(value)):
                raise ValueError("Numeric params must be finite numbers, excluding booleans")
            if not cap["hard"][0] <= value <= cap["hard"][1]:
                raise ValueError("Hard limits cannot be overridden")
        elif type(value) is not bool:
            raise ValueError("Power on must be an actual boolean")
        if state["mode"] != "online" or audit["health_required"]:
            raise ValueError("Write requires online mode and fresh health after any failed write")
        approval = cap["requires_authority"] or ("soft" in cap and not cap["soft"][0] <= value <= cap["soft"][1])
        return copy.deepcopy(cap), approval

    def _refusal(self, connection, intent, state, audit, reason, receipt=None, recorded=True):
        if state is not None and intent["action"] == "write":
            audit.update(health_required=True, failure_count=audit["failure_count"] + 1)
            self.store.update(connection, intent["device_id"], state, audit)
        receipt = receipt or {**ORIGIN, "command_id": intent["command_id"], "intent": intent,
                              "intent_sha256": digest(intent), "params": intent["params"]}
        if "proposal" not in receipt:
            limits = copy.deepcopy(CAPABILITIES.get(intent["device_id"], {}).get(intent.get("capability"), {}))
            proposal = {"version": 1, "intent": intent, "state_revision": state["revision"] if state else None,
                        "state_sha256": digest(state) if state else None, "effective_limits": limits}
            receipt.update(effective_limits=limits, proposal=proposal, commitment_sha256=digest(proposal))
        receipt.update(status="refused", terminal=True, action_attempted=False, recorded=recorded,
                       error={"code": "preflight_refused", "message": reason},
                       before={"state": state, "state_sha256": digest(state) if state else None},
                       after={"state": state, "state_sha256": digest(state) if state else None})
        if recorded:
            self.store.save_command(connection, intent, receipt)
        return receipt

    def _command(self, connection, intent) -> dict:
        existing = self.store.command(connection, intent["command_id"])
        known = intent["device_id"] in DEFAULTS
        state, audit = self.store.device(connection, intent["device_id"]) if known else (None, None)
        if existing and existing[0] != intent:
            return self._refusal(connection, intent, state, audit, "command_id is bound to a different intent", recorded=False)
        if existing and existing[1]["terminal"]:
            return existing[1]
        if not self.store.has_capacity(connection, intent, project_reset=True):
            return self._refusal(connection, intent, state, audit,
                                 "512-command limit reserves a stop receipt per online device",
                                 existing[1] if existing else None, recorded=existing is not None)
        try:
            if not known:
                raise ValueError("Unknown registered simulator device")
            limits, needs_approval = self._preflight(intent, state, audit)
        except ValueError as exc:
            return self._refusal(connection, intent, state, audit, str(exc))
        proposal = {"version": 1, "intent": intent, "state_revision": state["revision"],
                    "state_sha256": digest(state), "effective_limits": limits}
        receipt = {**ORIGIN, "status": "approval_required", "terminal": False, "recorded": True,
                   "command_id": intent["command_id"], "intent": intent, "intent_sha256": digest(intent),
                   "params": intent["params"], "effective_limits": limits, "proposal": proposal,
                   "commitment_sha256": digest(proposal), "action_attempted": False,
                   "before": {"state": copy.deepcopy(state), "state_sha256": digest(state)},
                   "after": {"state": copy.deepcopy(state), "state_sha256": digest(state)}}
        if existing and existing[1]["proposal"] != proposal:
            return self._refusal(connection, intent, state, audit, "Pending proposal state or limits are stale", existing[1])
        approval = host_approval(self.authority_file, receipt["commitment_sha256"]) if needs_approval else None
        if needs_approval and not approval["authorized"]:
            receipt["authority"] = approval
            self.store.save_command(connection, intent, receipt)
            return receipt
        return self._execute(connection, intent, state, audit, receipt, approval)

    def _execute(self, connection, intent, state, audit, receipt, approval):
        self.check()
        if intent["action"] == "write":
            state["values"].update(intent["params"])
        else:
            state.update(mode="estopped" if intent["mode"] == "estop" else "online",
                         outputs_enabled=intent["mode"] != "estop", values=copy.deepcopy(DEFAULTS[intent["device_id"]]))
        state["revision"] += 1
        self.store.update(connection, intent["device_id"], state, audit)
        receipt.update(status="executed", terminal=True, action_attempted=True,
                       after={"state": state, "state_sha256": digest(state)}, result={"state": state})
        if approval is not None:
            receipt["authority"] = {**approval, "consumed_by_command_id": intent["command_id"]}
        self.store.save_command(connection, intent, receipt, approved=approval is not None)
        return receipt

    def write(self, device_id, capability, params, command_id, confirm=False) -> dict:
        """Validate one intent, durably refuse/propose it or execute it once in simulation."""
        def operation(connection):
            try:
                intent = self._intent(device_id, capability, params, command_id, confirm, "write")
            except ValueError as exc:
                if type(device_id) is str and device_id in DEFAULTS:
                    state, audit = self.store.device(connection, device_id)
                    audit.update(health_required=True, failure_count=audit["failure_count"] + 1)
                    self.store.update(connection, device_id, state, audit)
                return {**ORIGIN, "status": "refused", "terminal": True, "recorded": False,
                        "action_attempted": False, "error": {"code": "invalid_command_envelope", "message": str(exc)}}
            return self._command(connection, intent)
        return self._run(operation)

    def reset(self, device_id, mode, command_id) -> dict:
        """Latch a simulated stop freely or require separate authority for soft recovery."""
        return self._run(lambda connection: self._command(connection, self._intent(
            device_id, mode, {}, command_id, False, "reset")))
