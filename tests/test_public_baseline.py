"""Reject broken public contracts and changed protected source originals."""

from copy import deepcopy
import hashlib
import json

import pytest

from scripts import check_public_baseline as gate


def tool():
    """Provide a literal public contract with required and optional inputs."""
    return {
        "name": "inspect_fixture",
        "description": "Inspect one fixture.",
        "annotations": {"read_only_hint": True, "open_world_hint": False},
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "required": ["source"],
            "properties": {
                "source": {"type": "string", "minLength": 1},
                "limit": {"type": "integer", "minimum": 1, "default": 3},
            },
        },
        "output_schema": {"type": "object", "additionalProperties": True},
    }


def test_allows_new_tools_and_optional_inputs():
    """Optional extension must preserve valid existing calls."""
    old = tool()
    new = deepcopy(old)
    new["parameters"]["properties"]["preview"] = {"type": "boolean", "default": False}
    extra = deepcopy(old)
    extra["name"] = "new_tool"
    assert gate.compatibility_issues([old], [new, extra]) == []


@pytest.mark.parametrize(
    "change",
    [
        "removed_tool",
        "removed_field",
        "required_extension",
        "narrowed_range",
        "default",
        "annotations",
        "output",
        "duplicate_tool",
    ],
)
def test_rejects_breaking_public_contract(change):
    """Dropping or narrowing a published call contract must fail the gate."""
    old = tool()
    new = deepcopy(old)
    current = [new]
    if change == "removed_tool":
        current = []
    elif change == "removed_field":
        del new["parameters"]["properties"]["source"]
    elif change == "required_extension":
        new["parameters"]["properties"]["token"] = {"type": "string"}
        new["parameters"]["required"].append("token")
    elif change == "narrowed_range":
        new["parameters"]["properties"]["limit"]["minimum"] = 2
    elif change == "default":
        new["parameters"]["properties"]["limit"]["default"] = 5
    elif change == "annotations":
        new["annotations"]["read_only_hint"] = False
    elif change == "output":
        new["output_schema"] = {"type": "string"}
    else:
        current.append(deepcopy(new))
    assert gate.compatibility_issues([old], current)


def test_description_edits_do_not_break_wire_contracts():
    """Documentation changes do not narrow accepted inputs."""
    old = tool()
    new = deepcopy(old)
    new["description"] = "Updated documentation."
    new["parameters"]["properties"]["source"]["description"] = "Frozen source."
    assert gate.compatibility_issues([old], [new]) == []


def test_rejects_frozen_source_hash_tampering(tmp_path, monkeypatch):
    """A changed recorded lock hash must disagree with the pinned Git blob."""
    monkeypatch.setattr(gate, "EVIDENCE_PATHS", ("uv.lock",))
    monkeypatch.setattr(gate, "CRITERIA_PATHS", (), raising=False)
    monkeypatch.setattr(gate, "git_blob", lambda repo, path: b"published lock\n")
    metadata = {
        "source_evidence": {"uv.lock": {"sha256": "0" * 64}},
        "full_gate_criteria_sources": {},
    }
    assert gate.source_evidence_issues(metadata, tmp_path)


def test_rejects_removed_source_evidence(tmp_path, monkeypatch):
    """Deleting a lock/source criterion cannot shrink the frozen population."""
    monkeypatch.setattr(gate, "EVIDENCE_PATHS", ("uv.lock", "docs/RELEASE_CHECKLIST.md"))
    metadata = {"source_evidence": {}}
    assert gate.source_evidence_issues(metadata, tmp_path)


def test_rejects_weakened_required_command_population(monkeypatch):
    """A missing required gate must not silently weaken later release acceptance."""
    monkeypatch.setattr(gate, "REQUIRED_COMMANDS", ((".", "required gate"),), raising=False)
    assert gate.criteria_issues(
        {"required_commands": [], "future_decode_requirement": gate.FUTURE_DECODE_REQUIREMENT}
    )


def test_rejects_changed_full_gate_criteria(tmp_path, monkeypatch):
    """A falsely weakened copy of the published criteria must fail source verification."""
    monkeypatch.setattr(gate, "EVIDENCE_PATHS", ("criterion.md",))
    monkeypatch.setattr(gate, "CRITERIA_PATHS", ("criterion.md",), raising=False)
    monkeypatch.setattr(gate, "git_blob", lambda repo, path: b"full published criterion\n")
    metadata = {
        "source_evidence": {
            "criterion.md": {"sha256": hashlib.sha256(b"full published criterion\n").hexdigest()}
        },
        "full_gate_criteria_sources": {"criterion.md": {"text": "weakened criterion\n"}},
    }
    assert gate.source_evidence_issues(metadata, tmp_path)


def protected_fixture(tmp_path, monkeypatch):
    """Create one protected original and a distinct authoritative manifest."""
    source = tmp_path / "original.txt"
    source.write_text("original bytes\n")
    files = [{"path": str(source), "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]
    manifest = tmp_path / "protected.json"
    manifest.write_text(json.dumps(files))
    protection = {
        "manifest": {
            "path": str(manifest),
            "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
        "files": files,
        "checkout": {
            "path": str(tmp_path),
            "head": "1" * 40,
            "branch": "feat/original",
            "dirty_files": ["original.txt"],
        },
    }
    states = {
        ("rev-parse", "HEAD"): "1" * 40,
        ("branch", "--show-current"): "feat/original",
        ("status", "--porcelain"): " M original.txt",
    }
    monkeypatch.setattr(gate, "git_text", lambda repo, *args: states[args])
    return protection, source, manifest, states


def test_accepts_unchanged_protected_original(tmp_path, monkeypatch):
    """The local preservation check succeeds only for the recorded bytes/state."""
    protection, _, _, _ = protected_fixture(tmp_path, monkeypatch)
    assert gate.protection_issues(protection) == []


def test_original_dirty_scope_preserves_git_porcelain_whitespace(tmp_path, monkeypatch):
    """Trimming Git's status prefix must not corrupt the first dirty filename."""
    actual_git_text = gate.git_text
    protection, _, _, states = protected_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(gate, "git_text", actual_git_text)
    monkeypatch.setattr(
        gate.subprocess, "check_output", lambda command, **kwargs: states[tuple(command[1:])] + "\n"
    )
    assert gate.protection_issues(protection) == []


@pytest.mark.parametrize("change", ["file", "manifest", "head", "branch", "dirty_scope", "missing"])
def test_rejects_changed_protected_original(tmp_path, monkeypatch, change):
    """Original bytes and checkout scope must never drift without detection."""
    protection, source, manifest, states = protected_fixture(tmp_path, monkeypatch)
    if change == "file":
        source.write_text("changed bytes\n")
    elif change == "manifest":
        manifest.write_text("[]")
    elif change == "head":
        states[("rev-parse", "HEAD")] = "2" * 40
    elif change == "branch":
        states[("branch", "--show-current")] = "main"
    elif change == "dirty_scope":
        states[("status", "--porcelain")] += "\n M other.txt"
    else:
        source.unlink()
    assert gate.protection_issues(protection)
