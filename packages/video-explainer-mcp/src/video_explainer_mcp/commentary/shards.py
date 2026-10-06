"""Immutable content-addressed shard sets and explicit per-shard host execution scope."""

from __future__ import annotations

import json
from pathlib import Path

from .plan import validate_plan
from .project import load, verify_source
from .store import (
    APPROVAL_SCHEMA, REPORT_SCHEMA, SHARD_SCHEMA, canonical, read_bytes, read_record, revision, sha256, write_once,
)

REPORT_FIELDS = ["schema", "shard_id", "shard_sha256", "approval_sha256", "status", "segments",
                 "output_video", "duration_sec", "qa_checks", "unresolved"]


def set_id(validation: dict) -> str:
    """Shard sets are named by everything that must invalidate them when it changes."""
    keys = ("plan_sha256", "script_sha256", "facts_sha256", "evidence")
    return sha256(canonical({k: validation[k] for k in keys}))[:16]


def current_set(root: Path, manifest: dict) -> tuple[str, dict]:
    """Return the frozen set matching the current source, plan, facts and evidence."""
    verify_source(manifest)
    validation = validate_plan(root, manifest)
    if not validation["valid"]:
        raise ValueError("Current plan is invalid: " + "; ".join(validation["errors"][:5]))
    name = set_id(validation)
    index_path = root / "shards" / name / "index.json"
    if not index_path.is_file():
        raise ValueError("Current plan/facts/evidence have no frozen shard set; freeze before execution")
    index = read_record(index_path)
    for shard_id, digest in index["shards"].items():
        if revision(root / "shards" / name / f"{shard_id}.json")["sha256"] != digest:
            raise ValueError(f"Frozen shard {shard_id} changed after freezing")
    return name, index


def freeze(project_id: str, segments_per_shard: int) -> dict:
    """Validate first; then write each consecutive segment group exactly once."""
    if not 1 <= segments_per_shard <= 20:
        raise ValueError("segments_per_shard must be between 1 and 20")
    root, manifest = load(project_id)
    verify_source(manifest)
    validation = validate_plan(root, manifest)
    if not validation["valid"]:
        raise ValueError("Plan validation failed: " + "; ".join(validation["errors"]))
    raw = read_bytes(root / "plan/editing_plan.json")
    if sha256(raw) != validation["plan_sha256"]:
        raise ValueError("Plan changed during validation")
    segments = json.loads(raw)["segments"]
    name = set_id(validation)
    groups = [segments[i:i + segments_per_shard] for i in range(0, len(segments), segments_per_shard)]
    digests = {}
    for number, group in enumerate(groups, start=1):
        shard_id = f"shard_{number:02d}"
        refs = {r for s in group for r in s["visual_plan"]["movie_locator"]["evidence_refs"]}
        digests[shard_id] = write_once(root / "shards" / name / f"{shard_id}.json", {
            "schema": SHARD_SCHEMA, "set_id": name, "shard_id": shard_id, "shard_index": number,
            "shard_count": len(groups), "source": manifest["source"], "facts_sha256": validation["facts_sha256"],
            "plan_sha256": validation["plan_sha256"], "segments": group,
            "evidence": {r: validation["evidence"][r] for r in sorted(refs)}})
    index = {"schema": SHARD_SCHEMA + "#index", "set_id": name, "segments_per_shard": segments_per_shard,
             "source_sha256": manifest["source"]["sha256"],
             **{k: validation[k] for k in ("plan_sha256", "script_sha256", "facts_sha256", "evidence")},
             "segment_ids": [s["segment_id"] for s in segments], "shards": digests}
    index_sha256 = write_once(root / "shards" / name / "index.json", index)
    return {"set_id": name, "index_sha256": index_sha256, "shards": digests,
            "segment_count": len(segments), "immutable": True}


def approve(project_id: str, shard_id: str, approval: dict) -> dict:
    """Record one explicit approval and return the exact host execution scope."""
    root, manifest = load(project_id)
    name, index = current_set(root, manifest)
    if shard_id not in index["shards"]:
        raise ValueError(f"Unknown shard in the current frozen set: {shard_id}")
    if approval["shard_sha256"] != index["shards"][shard_id]:
        raise ValueError("Approval names different shard bytes than the current frozen shard")
    if approval["source_sha256"] != manifest["source"]["sha256"]:
        raise ValueError("Approval names a different source revision")
    record = {"schema": APPROVAL_SCHEMA, "set_id": name, "shard_id": shard_id, **approval,
              "authority_basis": "caller_asserted_not_verified", "rights_inferred": False}
    approval_sha256 = write_once(root / "approvals" / name / f"{shard_id}.json", record)
    output = root / "out" / name / shard_id
    return {"status": "approved_scope_recorded", "execution": "host_must_execute_exactly_this_scope",
            "agents_spawned": 0, "renders_started": 0, "set_id": name, "shard_id": shard_id,
            "shard_path": str(root / "shards" / name / f"{shard_id}.json"),
            "execution_facts_path": str(root / "plan/execution_facts.json"),
            "source": manifest["source"], "approval_sha256": approval_sha256,
            "output_video": str(output / f"{shard_id}.mp4"), "output_report": str(output / "exec_report.json"),
            "report_schema": REPORT_SCHEMA, "report_fields": REPORT_FIELDS}
