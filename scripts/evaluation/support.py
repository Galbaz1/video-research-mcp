"""Read and hash local evidence; output text cannot replace source evidence."""

import hashlib
import json
from pathlib import Path

from scripts.evaluation.models import Case, Label


def sha256(path: Path) -> str:
    """Hash exact file bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained_path(root: Path, name: str) -> Path:
    """Keep untrusted fixture/result paths inside their declared bundle."""
    path = (root / name).resolve()
    if Path(name).is_absolute() or not path.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes bundle: {name}")
    return path


def read_json(path: Path):
    """Decode a UTF-8 JSON artifact."""
    return json.loads(path.read_text(encoding="utf-8"))


def evaluator_hash() -> str:
    """Commit the entire evaluator implementation, including file contracts."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def frozen_sources(case: Case, root: Path) -> dict[str, str]:
    """Re-fetch exact snapshots from disk and reject hash drift."""
    sources = {}
    snapshot_index = root / "source-snapshots.json"
    snapshots = read_json(snapshot_index) if snapshot_index.exists() else {}
    for source in case.sources:
        if source.id in sources:
            raise ValueError(f"duplicate source: {source.id}")
        path = contained_path(root, source.path)
        if sha256(path) != source.sha256:
            raise ValueError(f"source hash mismatch: {source.id}")
        sources[source.id] = (
            path.read_text(encoding="utf-8")
            if source.content_type.startswith("text/") or source.content_type == "application/json"
            else ""
        )
        if source.id in snapshots:
            snapshot = snapshots[source.id]
            path = contained_path(root, snapshot["path"])
            if snapshot["asset_sha256"] != source.sha256 or sha256(path) != snapshot["sha256"]:
                raise ValueError(f"judge snapshot hash mismatch: {source.id}")
            sources[source.id] = path.read_text(encoding="utf-8")
    return sources


def validate_labels(label: Label, sources: dict[str, str]) -> None:
    """Reject corrupt ground truth before judging any candidate."""
    if label.expected_status == "ok" and not (
        label.facts or label.temporal or label.required_artifacts
    ):
        raise ValueError("empty input cannot be labeled factual success")
    for items in (label.facts, label.temporal):
        ids = [item.id for item in items]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate label ID")
    for fact in label.facts:
        if not fact.evidence:
            raise ValueError(f"fact has no evidence: {fact.id}")
        for evidence in fact.evidence:
            if not evidence.quote or evidence.quote not in sources.get(evidence.source_id, ""):
                raise ValueError(f"ground-truth passage absent: {fact.id}")
