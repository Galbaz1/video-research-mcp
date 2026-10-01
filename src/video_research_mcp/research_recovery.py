"""Read back exact terminal research artifacts without resubmitting ambiguous runs."""

import hashlib
import json
from pathlib import Path

from .evidence import validate_evidence_packet
from .models.evidence import EvidencePacket
from .models.research_execution import ResearchExecutionResponse
from .media_local_io import _open_regular
from .research_execution_provider import ResearchExecutionFailure, check_sources

MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


def _read(path: Path) -> bytes:
    """Use the same bounded, nonsymlink buffer for commitment and parsing."""
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ResearchExecutionFailure("Research recovery artifact is unsafe or exceeds eight MiB")
    with _open_regular(path) as stream:
        body = stream.read(MAX_ARTIFACT_BYTES + 1)
    if len(body) > MAX_ARTIFACT_BYTES:
        raise ResearchExecutionFailure("Research recovery artifact exceeds eight MiB")
    return body


def digest(path: Path) -> str:
    """Hash the actual bounded private artifact."""
    return hashlib.sha256(_read(path)).hexdigest()


def replay(directory: Path, request_sha256: str, selected: tuple) -> dict:
    """Require exact request/account and stored bytes before returning any prior result."""
    state_path = directory / "state.json"
    state_body = _read(state_path)
    state = json.loads(state_body)
    if state.get("request_sha256") != request_sha256 or state.get("run_id") != directory.name:
        raise ResearchExecutionFailure("Research run_id belongs to a different request or configured account")
    receipt_path = directory / "result-receipt.json"
    if not receipt_path.is_file():
        return {"error": "Recorded research run has no accepted terminal result; work was not resubmitted",
                "category": "RECOVERY_REQUIRED", "hint": "Inspect the retained failures and ambiguous attempts",
                "retryable": False, "retry_after_seconds": None,
                "run_id": state["run_id"], "request_sha256": request_sha256, "plan": state["plan"],
                "branches": state["branches"], "execution": {**state["execution"], "replay_new_calls": 0,
                    "provider_calls": None, "last_checkpoint_provider_calls": state["execution"]["provider_calls"],
                    "usage_complete": False, "recorded_execution_may_be_stale": True,
                    "retained_operation_failure": state.get("operation_failure"),
                    "source_preparation": state.get("source_preparation")},
                "state_path": str(state_path)}
    receipt = json.loads(_read(receipt_path))
    if (receipt.get("schema_version") != 1 or receipt.get("request_sha256") != request_sha256
            or receipt.get("run_id") != directory.name
            or set(receipt.get("files", {})) != {"response.json", "state.json", "evidence-packet.json"}):
        raise ResearchExecutionFailure("Research recovery receipt identity or file population changed")
    bodies = {"state.json": state_body, "response.json": _read(directory / "response.json"),
              "evidence-packet.json": _read(directory / "evidence-packet.json")}
    for name, body in bodies.items():
        if hashlib.sha256(body).hexdigest() != receipt["files"][name]:
            raise ResearchExecutionFailure("Research recovery artifact bytes changed")
    packet = EvidencePacket.model_validate_json(bodies["evidence-packet.json"])
    check_sources(directory, packet.sources, selected)
    if validate_evidence_packet(packet, directory)["source_errors"]:
        raise ResearchExecutionFailure("Research recovery original source bytes changed")
    result = ResearchExecutionResponse.model_validate_json(bodies["response.json"]).model_dump(mode="json")
    if (result["request_sha256"] != request_sha256 or result["run_id"] != state["run_id"]
            or result["status"] != state["status"]):
        raise ResearchExecutionFailure("Research recovery result identity changed")
    result["execution"].update(replayed=True, replay_new_calls=0)
    return result


def record_result(directory: Path, result: dict, writer) -> None:
    """Bind response/state/packet bytes after each complete atomic publication."""
    writer(directory / "response.json", result)
    files = {name: digest(directory / name) for name in ("response.json", "state.json", "evidence-packet.json")}
    writer(directory / "result-receipt.json", {"schema_version": 1, "files": files,
                                               "request_sha256": result["request_sha256"],
                                               "run_id": result["run_id"]})
