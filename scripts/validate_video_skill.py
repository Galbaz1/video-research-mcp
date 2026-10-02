"""Validate retained video-derived authoring evidence without executing a task."""

import argparse
import datetime as dt
import json
import math
import sys
from pathlib import Path

import yaml

if __package__:
    from .video_skill_contract import (
        HASH, TEXT_SUFFIXES, InvalidSkill, Snapshot, canonical, frontmatter, linked_files, parse_json, require,
        scan, sha,
    )
else:
    from video_skill_contract import (
        HASH, TEXT_SUFFIXES, InvalidSkill, Snapshot, canonical, frontmatter, linked_files, parse_json, require,
        scan, sha,
    )


def fields(value, required, optional=()):
    """Reject missing or unknown fields in evidence records."""
    require(isinstance(value, dict) and set(required) <= set(value) <= set(required) | set(optional),
            "missing or unknown evidence fields")


def text(value, label):
    require(isinstance(value, str) and 0 < len(value) <= 32768, f"invalid {label}")
    return value


def full_hash(value):
    require(isinstance(value, str) and HASH.fullmatch(value), "invalid full SHA-256")
    return value


def interval(record, duration):
    """Require finite source-absolute intervals within the declared duration."""
    start, end = record.get("start_seconds"), record.get("end_seconds")
    require(type(start) in (int, float) and type(end) in (int, float) and
            math.isfinite(start) and math.isfinite(end) and 0 <= start < end <= duration,
            "invalid source-absolute interval")
    return start, end


def _provenance(snapshot):
    metadata, _ = frontmatter(snapshot.read("SKILL.md", member=True))
    required = {"name", "description", "source_type", "source_path", "source_sha256",
                "extraction_date", "status", "evidence_file"}
    fields(metadata, required, {"compatibility", "metadata", "license", "allowed-tools"})
    require(metadata["source_type"] in {"video", "demo", "document", "manual"}, "invalid source type")
    require(metadata["status"] in {"source-grounded", "execution-verified"}, "invalid evidence status")
    full_hash(metadata["source_sha256"])
    require(isinstance(metadata["extraction_date"], str), "extraction date must be ISO text")
    dt.date.fromisoformat(metadata["extraction_date"])
    require(snapshot.source(metadata["source_path"]) == metadata["source_sha256"],
            "original source SHA-256 mismatch")
    evidence = snapshot.document(metadata["evidence_file"], member=True)
    fields(evidence, {"schema_version", "source_origin", "duration_seconds", "timeline_origin_seconds",
                      "coverage", "events", "media_plan", "assets"}, {"execution", "trigger_report"})
    require(type(evidence["schema_version"]) is int and evidence["schema_version"] == 1,
            "unsupported evidence schema")
    require(evidence["source_origin"] in {"recorded", "synthetic"}, "invalid source origin")
    duration = evidence["duration_seconds"]
    require(type(duration) in (float, int) and math.isfinite(duration) and 0 < duration <= 86400,
            "invalid source duration")
    require(type(evidence["timeline_origin_seconds"]) in (int, float) and
            evidence["timeline_origin_seconds"] == 0, "timeline must be source-absolute")
    require(evidence["coverage"] in {"complete", "sampled"}, "invalid coverage declaration")
    return metadata, evidence


def _events(evidence):
    events, end = {}, 0
    require(isinstance(evidence["events"], list) and evidence["events"], "missing source events")
    for event in evidence["events"]:
        fields(event, {"id", "start_seconds", "end_seconds", "origin", "text", "asset_ids"})
        key = text(event["id"], "event id")
        require(key not in events, "duplicate event id")
        start, current_end = interval(event, evidence["duration_seconds"])
        require(start >= end, "events must be ordered without overlap")
        end = current_end
        require(event["origin"] in {"observed", "generated"}, "invalid event origin")
        require(event["origin"] != "generated" or evidence["source_origin"] == "synthetic",
                "generated event mislabeled as recorded source")
        scan(text(event["text"], "event text").encode(), "event text")
        require(isinstance(event["asset_ids"], list) and
                all(isinstance(item, str) for item in event["asset_ids"]) and
                len(set(event["asset_ids"])) == len(event["asset_ids"]), "invalid event asset refs")
        events[key] = event
    return events


def _plan(evidence, events):
    plans = evidence["media_plan"]
    require(isinstance(plans, list) and len(plans) == len(events), "media plan must cover every event")
    for plan, event in zip(plans, events.values(), strict=True):
        fields(plan, {"event_id", "start_seconds", "end_seconds", "asset_ids", "disposition", "reason"})
        require(plan["event_id"] == event["id"] and interval(plan, evidence["duration_seconds"]) ==
                interval(event, evidence["duration_seconds"]), "media plan event/interval mismatch")
        require(plan["asset_ids"] == event["asset_ids"], "media plan asset refs mismatch")
        require(plan["disposition"] in {"included", "omitted"}, "invalid plan disposition")
        text(plan["reason"], "plan reason")
        require(plan["disposition"] != "omitted" or not plan["asset_ids"], "omitted event has assets")


def _grant(snapshot, asset):
    grant = parse_json(snapshot.bound(asset["grant"], member=True))
    fields(grant, {"asset_sha256", "kind", "attribution", "redistribution"}, {"license_source"})
    require(grant["asset_sha256"] == asset["sha256"] and grant["redistribution"] is True,
            "asset redistribution/hash grant gap")
    text(grant["attribution"], "grant attribution")
    require(grant["kind"] in {"first-party", "licensed"}, "unsupported asset grant")
    if grant["kind"] == "licensed":
        require("license_source" in grant, "licensed asset requires a bound license source")
        snapshot.bound(grant["license_source"], member=True)
    else:
        require("license_source" not in grant, "unexpected first-party license source")
    scan(canonical(grant), "asset grant")


def _assets(snapshot, evidence, events, source_hash):
    require(isinstance(evidence["assets"], list), "assets must be a list")
    assets = {}
    for asset in evidence["assets"]:
        fields(asset, {"id", "path", "sha256", "origin", "content_origin", "event_id",
                       "start_seconds", "end_seconds", "source_sha256", "receipt", "grant"})
        key = text(asset["id"], "asset id")
        require(key not in assets and asset["event_id"] in events, "duplicate asset or unknown event")
        event = events[asset["event_id"]]
        start, end = interval(asset, evidence["duration_seconds"])
        require(event["start_seconds"] <= start < end <= event["end_seconds"],
                "asset interval escapes source event")
        require(asset["origin"] in {"extracted", "generated"}, "invalid asset origin")
        expected_origin = evidence["source_origin"] if asset["origin"] == "extracted" else "synthetic"
        require(asset["content_origin"] == expected_origin and asset["source_sha256"] ==
                (source_hash if asset["origin"] == "extracted" else None), "mislabeled asset origin")
        snapshot.bound({"path": asset["path"], "sha256": asset["sha256"]}, member=True)
        receipt = parse_json(snapshot.bound(asset["receipt"]))
        keys = {"id", "asset_sha256", "origin", "content_origin", "event_id", "start_seconds",
                "end_seconds", "source_sha256", "method"}
        fields(receipt, keys)
        expected = {key: asset[key] for key in keys - {"asset_sha256", "method"}}
        expected["asset_sha256"] = asset["sha256"]
        require(all(canonical(receipt[key]) == canonical(value) for key, value in expected.items()),
                "asset receipt disagrees with manifest")
        text(receipt["method"], "asset method")
        scan(canonical(receipt), "asset receipt")
        _grant(snapshot, asset)
        assets[key] = asset
    refs = [key for event in events.values() for key in event["asset_ids"]]
    require(len(refs) == len(set(refs)) and set(refs) == set(assets), "unknown or unreferenced asset")
    require(all(asset["id"] in events[asset["event_id"]]["asset_ids"] for asset in assets.values()),
            "asset bound to wrong event")


def _trigger(snapshot, ref):
    report = parse_json(snapshot.bound(ref))
    fields(report, {"kind", "cases"})
    require(report["kind"] == "trigger-judgement" and isinstance(report["cases"], list),
            "invalid trigger judgment report")
    ids = set()
    for case in report["cases"]:
        fields(case, {"id", "outcome"})
        key = text(case["id"], "trigger case id")
        require(key not in ids and case["outcome"] in {"pass", "fail", "unknown", "refused", "error"},
                "invalid trigger case outcome")
        ids.add(key)
    return len(ids)


def _timestamp(value):
    timestamp = dt.datetime.fromisoformat(text(value, "run timestamp"))
    require(timestamp.tzinfo is not None, "run timestamps require timezone")
    return timestamp


def _execution(snapshot, evidence, revision):
    execution = evidence.get("execution")
    fields(execution, {"run_record"})
    run = parse_json(snapshot.bound(execution["run_record"]))
    fields(run, {"schema_version", "origin", "state", "skill_revision_sha256", "command", "exit_code",
                 "started_at", "finished_at", "stdout", "stderr", "outputs", "end_state"})
    require(type(run["schema_version"]) is int and run["schema_version"] == 1 and
            run["origin"] == "host-controller" and run["state"] == "complete", "invalid run origin/state")
    require(run["skill_revision_sha256"] == revision, "run binds a different skill revision")
    command = run["command"]
    require(isinstance(command, list) and 1 <= len(command) <= 16 and
            all(isinstance(arg, str) and 0 < len(arg) <= 1024 and
                not any(ord(char) < 32 for char in arg) for arg in command), "invalid run command")
    scan(" ".join(command).encode(), "run command")
    require(type(run["exit_code"]) is int and run["exit_code"] == 0, "run did not exit successfully")
    require(_timestamp(run["started_at"]) <= _timestamp(run["finished_at"]), "run timestamps out of order")
    snapshot.bound(run["stdout"])
    snapshot.bound(run["stderr"])
    require(isinstance(run["outputs"], list) and run["outputs"], "missing retained run outputs")
    output_paths = set()
    for output in run["outputs"]:
        fields(output, {"path", "sha256", "expected_sha256"})
        full_hash(output["expected_sha256"])
        require(output["path"] not in output_paths and output["sha256"] == output["expected_sha256"],
                "run output disagrees with expected output")
        output_paths.add(output["path"])
        snapshot.bound({key: output[key] for key in ("path", "sha256")})
    end = run["end_state"]
    fields(end, {"path", "sha256", "expected"})
    actual = parse_json(snapshot.bound({key: end[key] for key in ("path", "sha256")}))
    require(isinstance(end["expected"], dict) and canonical(actual) == canonical(end["expected"]),
            "run end-state disagrees with expectation")
    scan(canonical(run), "run record")


def _validate(directory, progress):
    snapshot = Snapshot(directory)
    metadata, evidence = _provenance(snapshot)
    events = _events(evidence)
    _plan(evidence, events)
    _assets(snapshot, evidence, events, metadata["source_sha256"])
    linked_files(snapshot)
    declared_assets = {asset["path"] for asset in evidence["assets"]}
    for name in snapshot.members:
        require(not name.startswith("assets/") or name in declared_assets,
                "linked asset lacks manifest/grant")
        require(Path(name).suffix in TEXT_SUFFIXES or name in declared_assets,
                "non-text resource lacks asset manifest/grant")
    for name, data in snapshot.members.items():
        if Path(name).suffix in TEXT_SUFFIXES:
            scan(data, name)
    normalized = {key: value for key, value in evidence.items() if key not in {"execution", "trigger_report"}}
    members = {name: sha(data) for name, data in snapshot.members.items()}
    members[metadata["evidence_file"]] = sha(canonical(normalized))
    revision = sha(canonical(members))
    progress["candidate_revision_sha256"] = revision
    trigger_count = _trigger(snapshot, evidence["trigger_report"]) if "trigger_report" in evidence else 0
    if metadata["status"] == "execution-verified" or "execution" in evidence:
        _execution(snapshot, evidence, revision)
        progress["retained_execution_bindings"] = "pass"
    snapshot.recheck()
    progress.update({"status": "pass", "name": metadata["name"], "declared_status": metadata["status"],
                     "coverage": evidence["coverage"], "event_count": len(events),
                     "asset_count": len(evidence["assets"]), "trigger_case_count": trigger_count,
                     "members": sorted(snapshot.members), "bindings": snapshot.bindings,
                     "omitted_provenance": sorted(set(snapshot.bindings) - set(snapshot.members))})
    return snapshot


def facts():
    """Keep structural checks separate from unobserved factual/authority claims."""
    return {"status": "fail", "execution_observed": False, "factual_success": False,
            "human_rights_audit": False, "semantic_safety_certified": False,
            "pattern_scan_scope": "selected UTF-8 instructions, metadata, linked text and command argv",
            "retained_execution_bindings": "absent", "portable_revalidation": False,
            "validation_scope": "retained authoring directory; private provenance may be omitted from ZIP"}


def validate_skill(directory):
    """Return bounded syntax/hash checks without running tasks or authenticating observations."""
    result = facts()
    try:
        _validate(Path(directory), result)
    except (InvalidSkill, OSError, ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError) as exc:
        result.update(status="fail", error=str(exc))
    return result


def main():
    """Print a JSON result and signal validation failure through the exit status."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    result = validate_skill(args.directory)
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
