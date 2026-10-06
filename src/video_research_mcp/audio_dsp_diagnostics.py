"""Bounded, identity-checked DSP observations for the existing collector and durable jobs."""

import hashlib
import json
import re

from .audio_dsp_stdio import INITIALIZE, MAX_LINE, MAX_TOTAL, TOOLS, encode
from .media_local_io import _open_regular

CAP = 65536
IDENTITY_KEYS = {"request_sha256", "helper_sha256", "executable_sha256", "backend", "tool"}
WIRE_KEYS = IDENTITY_KEYS | {
    "schema",
    "phase",
    "response_bytes",
    "total_response_bytes",
    "notifications",
    "observation",
    "terminal",
    "native_returncode",
    "native_process_joined",
    "stderr_drain_joined",
    "stderr",
}
STDERR_KEYS = {"observed_bytes", "retained_bytes", "retained_sha256", "truncated", "eof"}
OBSERVATIONS = {
    "pending",
    "response_received",
    "empty_eof",
    "unterminated_line",
    "line_overflow",
    "aggregate_overflow",
    "notification_exhaustion",
    "invalid_response",
    "collector_error",
    "interrupted",
    "complete",
}


def require(condition):
    """Reject untrusted diagnostic data with one public message that includes no native text."""
    if not condition:
        raise ValueError("Native DSP diagnostic failed bounded identity/schema readback")


def digest(value):
    """Validate a SHA256 string without admitting arbitrary native text."""
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def count(value, maximum):
    """Accept only nonnegative bounded integers, excluding JSON booleans."""
    return type(value) is int and 0 <= value <= maximum


def validate_observation(value, binding):
    """Admit a fixed wire schema and observed counts, never native text or inferred cause."""
    require(isinstance(value, dict) and set(value) == WIRE_KEYS)
    require(type(value["schema"]) is int and value["schema"] == 1)
    require(all(value[key] == binding[key] for key in IDENTITY_KEYS))
    require(all(digest(value[key]) for key in IDENTITY_KEYS if key.endswith("sha256")))
    require(value["backend"] in TOOLS and value["tool"] in TOOLS[value["backend"]])
    require(isinstance(value["observation"], str) and value["observation"] in OBSERVATIONS)
    require(count(value["response_bytes"], MAX_LINE + 1))
    require(count(value["total_response_bytes"], MAX_TOTAL + MAX_LINE + 1))
    require(value["response_bytes"] <= value["total_response_bytes"])
    require(count(value["notifications"], 16))
    validate_boundary(value)
    phase = value["phase"]
    if phase is not None:
        require(isinstance(phase, dict) and set(phase) == {"id", "method", "request_sha256"})
        require(type(phase["id"]) is int and phase["id"] in {1, 2, 3, 4})
        require(
            phase["method"]
            == {1: "initialize", 2: "tools/list", 3: "tools/call", 4: "tools/call"}[phase["id"]]
        )
        require(digest(phase["request_sha256"]))
        if "phases" in binding:
            if phase["id"] == 4:
                require(value["backend"] == "ferrous" and value["tool"] == "analyze_audio")
            else:
                require(phase == binding["phases"][phase["id"]])
    require(
        all(
            type(value[key]) is bool
            for key in ("terminal", "native_process_joined", "stderr_drain_joined")
        )
    )
    if value["terminal"]:
        require(value["native_process_joined"] and value["stderr_drain_joined"])
        require(
            type(value["native_returncode"]) is int and -255 <= value["native_returncode"] <= 255
        )
        validate_stderr(value["stderr"], terminal=True)
    else:
        require(value["native_returncode"] is None and not value["native_process_joined"])
        require(not value["stderr_drain_joined"] and value["stderr"] is None)


def validate_boundary(value):
    """Reject boundary labels contradicted by the helper's observed phase and byte counts."""
    reason = value["observation"]
    if value["phase"] is None:
        require(reason in {"pending", "interrupted", "collector_error"})
        require(
            value["response_bytes"] == value["total_response_bytes"] == value["notifications"] == 0
        )
    if reason == "pending":
        require(not value["terminal"])
    if reason == "empty_eof":
        require(value["response_bytes"] == 0)
    elif reason == "unterminated_line":
        require(0 < value["response_bytes"] <= MAX_LINE)
    elif reason == "line_overflow":
        require(value["response_bytes"] == MAX_LINE + 1)
    elif reason == "aggregate_overflow":
        require(value["total_response_bytes"] > MAX_TOTAL and value["response_bytes"] <= MAX_LINE)
    elif reason == "notification_exhaustion":
        require(value["notifications"] == 16 and 0 < value["response_bytes"] <= MAX_LINE)
        require(value["total_response_bytes"] <= MAX_TOTAL)


def validate_stderr(value, terminal):
    """Keep retained-prefix digest and observed drained bytes distinct from unknown totals."""
    require(isinstance(value, dict) and set(value) == STDERR_KEYS)
    require(count(value["retained_bytes"], CAP) and digest(value["retained_sha256"]))
    require(type(value["eof"]) is bool)
    if terminal:
        require(value["eof"] and type(value["observed_bytes"]) is int)
        require(value["observed_bytes"] >= value["retained_bytes"])
        require(value["retained_bytes"] == min(CAP, value["observed_bytes"]))
        require(type(value["truncated"]) is bool)
        require(value["truncated"] == (value["observed_bytes"] > CAP))
    else:
        require(not value["eof"] and value["observed_bytes"] is None and value["truncated"] is None)


def bounded_file(path):
    """Read a small regular diagnostic file without following substituted links."""
    with _open_regular(path) as reader:
        body = reader.read(CAP + 1)
    require(len(body) <= CAP)
    return body


def read_diagnostic(directory, binding):
    """Read after group cleanup; a pending helper snapshot remains explicitly nonterminal."""
    try:
        try:
            body = bounded_file(directory / "native-diagnostic.json")
        except FileNotFoundError:
            return None
        value = json.loads(body)
        validate_observation(value, binding)
        stderr_path = directory / "native-stderr.bin"
        prefix = (
            bounded_file(stderr_path) if stderr_path.exists() or stderr_path.is_symlink() else b""
        )
        prefix_hash = hashlib.sha256(prefix).hexdigest()
        if value["terminal"]:
            require(value["stderr"]["retained_bytes"] == len(prefix))
            require(value["stderr"]["retained_sha256"] == prefix_hash)
        else:
            value["stderr"] = {
                "retained_bytes": len(prefix),
                "retained_sha256": prefix_hash,
                "observed_bytes": None,
                "truncated": None,
                "eof": False,
            }
        value["helper_terminal"] = value.pop("terminal")
        return value
    except (OSError, ValueError, TypeError, KeyError, RecursionError):
        raise ValueError("Native DSP diagnostic failed bounded identity/schema readback") from None


def request_binding(body, helper_sha256):
    """Bind the exact request phases to the helper digest already admitted by the job."""
    request = json.loads(body)
    phases = {}
    arguments = {
        1: ("initialize", INITIALIZE),
        2: ("tools/list", {}),
        3: ("tools/call", {"name": request["tool"], "arguments": request["arguments"]}),
    }
    for identifier, (method, params) in arguments.items():
        phases[identifier] = {
            "id": identifier,
            "method": method,
            "request_sha256": hashlib.sha256(
                encode({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
            ).hexdigest(),
        }
    return {
        "request_sha256": hashlib.sha256(body).hexdigest(),
        "helper_sha256": helper_sha256,
        "executable_sha256": request["executable_sha256"],
        "backend": request["backend"],
        "tool": request["tool"],
        "phases": phases,
    }


def validate_job_diagnostic(value, job):
    """Reject altered safe metadata against the durable source/runtime/request binding."""
    require(isinstance(value, dict))
    require(
        set(value)
        == (WIRE_KEYS - {"terminal"})
        | {
            "helper_terminal",
            "job_request_sha256",
            "component_revision",
            "source",
            "phase_binding",
        }
    )
    require(value["job_request_sha256"] == job["request_sha256"])
    require(value["component_revision"] == job["source_revision"])
    require(value["helper_sha256"] == job["request"]["diagnostic_contract"]["helper_sha256"])
    optional = job["request"]["runtime"]["optional"]
    require(value["source"] == optional["source"] and value["backend"] == optional["backend"])
    require(value["executable_sha256"] == optional["sha256"])
    require(isinstance(value["phase_binding"], dict))
    require({str(key) for key in value["phase_binding"]} == {"1", "2", "3"})
    for key, phase in value["phase_binding"].items():
        require(isinstance(phase, dict) and set(phase) == {"id", "method", "request_sha256"})
        require(type(phase["id"]) is int and phase["id"] == int(key))
        require(
            phase["method"] == {"1": "initialize", "2": "tools/list", "3": "tools/call"}[str(key)]
        )
        require(digest(phase["request_sha256"]))
    wire = {key: value[key] for key in WIRE_KEYS - {"terminal"}}
    wire["terminal"] = value["helper_terminal"]
    stderr = wire["stderr"]
    if not wire["terminal"]:
        validate_stderr(stderr, terminal=False)
        wire["stderr"] = None
    binding = {key: value[key] for key in IDENTITY_KEYS}
    binding["phases"] = {int(key): phase for key, phase in value["phase_binding"].items()}
    validate_observation(wire, binding)
