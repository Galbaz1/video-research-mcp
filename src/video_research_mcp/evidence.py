"""Deterministic source binding and exact-claim lineage checks."""

import hashlib
import json
from pathlib import Path

from .models.evidence import EvidencePacket
from .media_local_io import _open_regular

STAGES = ("script", "narration", "storyboard", "rendered_text")
MAX_SOURCE_BYTES = 512 * 1024 * 1024
MAX_TEXT_BYTES = 8 * 1024 * 1024


def _read_original_text(path: Path) -> bytes:
    """Use one bounded buffer for original SHA and exact snapshot comparison."""
    with _open_regular(path) as stream:
        original = stream.read(MAX_TEXT_BYTES + 1)
    if len(original) > MAX_TEXT_BYTES:
        raise ValueError("Original text exceeds 8 MiB byte ceiling")
    return original


def _source_hash(path: Path) -> str:
    """Hash bounded original bytes without allocating the full asset."""
    digest, consumed = hashlib.sha256(), 0
    with _open_regular(path) as stream:
        while chunk := stream.read(64 * 1024):
            consumed += len(chunk)
            if consumed > MAX_SOURCE_BYTES:
                raise ValueError("Evidence source exceeds byte ceiling")
            digest.update(chunk)
    return digest.hexdigest()


def _source_issues(source: dict, root: Path) -> list[str]:
    """Check original bytes and frozen observations without executing their text."""
    issues = []
    try:
        relative = Path(source["path"])
        path = (root / relative).resolve()
        if relative.is_absolute() or not path.is_relative_to(root):
            raise ValueError("Evidence source escapes source root")
        if not path.is_file() or path.stat().st_size > MAX_SOURCE_BYTES:
            raise ValueError("Evidence source missing or exceeds byte ceiling")
        snapshot = source["snapshot"]
        if hashlib.sha256(snapshot["text"].encode()).hexdigest() != snapshot["sha256"]:
            issues.append("frozen snapshot hash mismatch")
        if source["modality"] in {"text", "geometry", "tabular"}:
            original = _read_original_text(path)
            if hashlib.sha256(original).hexdigest() != source["sha256"]:
                issues.append("original source hash mismatch")
            if source["sha256"] != snapshot["sha256"]:
                issues.append("original text and snapshot hash commitments differ")
            if original.decode("utf-8") != snapshot["text"]:
                issues.append("snapshot differs from original source text")
        else:
            if _source_hash(path) != source["sha256"]:
                issues.append("original source hash mismatch")
            issues.extend(_media_record_issues(source))
        if source["asset_kind"] != "original":
            issues.append("support must bind an original source, not a derived/synthetic asset")
        for span in source["observed_intervals"]:
            if source["duration_ms"] is not None and span["end_ms"] > source["duration_ms"]:
                issues.append("observed interval exceeds declared source duration")
        for passage in source["passages"]:
            issues.extend(_passage_issues(source, passage))
    except (OSError, ValueError) as error:
        issues.append(str(error))
    return [f"{source['id']}: {issue}" for issue in issues]


def _passage_issues(source: dict, passage: dict) -> list[str]:
    """Check exact snapshot quote and observed media clock binding separately."""
    issues = []
    if (
        source["modality"] in {"text", "geometry", "tabular"}
        and passage["quote"] not in source["snapshot"]["text"]
    ):
        issues.append(f"{passage['id']}: exact quote absent from frozen snapshot")
    start, end = passage["start_ms"], passage["end_ms"]
    if source["modality"] in {"video", "audio"} and start is None:
        issues.append(f"{passage['id']}: temporal source passage requires an interval")
    if start is not None:
        observed = any(
            span["start_ms"] <= start < end <= span["end_ms"]
            for span in source["observed_intervals"]
        )
        if not observed:
            issues.append(f"{passage['id']}: passage interval not actually observed")
        if source["duration_ms"] is not None and end > source["duration_ms"]:
            issues.append(f"{passage['id']}: passage exceeds declared source duration")
    return issues


def _media_record_issues(source: dict) -> list[str]:
    """Bind media clock/quote observations to the exact committed record bytes."""
    try:
        record = json.loads(source["snapshot"]["text"])
        if not isinstance(record, dict):
            raise ValueError("Media snapshot must be a JSON observation object")
        issues = []
        if (
            record.get("asset_sha256") != source["sha256"]
            or record.get("revision") != source["revision"]
        ):
            issues.append("media observation original hash/revision mismatch")
        if record.get("observed_intervals") != source["observed_intervals"]:
            issues.append("media observation intervals differ from frozen record")
        expected = [
            {key: passage[key] for key in ("id", "quote", "start_ms", "end_ms")}
            for passage in source["passages"]
        ]
        if record.get("passages") != expected:
            issues.append("media passages/intervals differ from frozen record")
        return issues
    except (ValueError, TypeError) as error:
        return [str(error)]


def _claim_support(claim: dict, passages: dict) -> str:
    """Only exact source text gets deterministic support; paraphrases stay unknown."""
    if claim["abstained"]:
        return "abstained"
    references = claim["support"]
    matched = all(
        passages.get((ref["source_id"], ref["passage_id"])) == claim["text"] for ref in references
    )
    return "exact_source_text" if references and matched else "unknown"


def _lineage_issues(node: dict, nodes: dict, claims: dict, support: dict) -> list[str]:
    """Compare every factual stage, including rendered captions and voiceover."""
    issues = []
    ids = node["claim_ids"]
    referenced = [claims.get(claim_id) for claim_id in ids]
    if not ids or len(ids) != len(set(ids)) or any(claim is None for claim in referenced):
        return [f"{node['id']}: missing, duplicate or unknown claim reference"]
    if node["text"] != "\n".join(claim["text"] for claim in referenced):
        issues.append("text contains an unapproved addition or paraphrase")
    for claim in referenced:
        if not claim["editorial_approved"] or support[claim["id"]] != "exact_source_text":
            issues.append(f"claim {claim['id']} is unapproved or lacks exact original support")
    index = STAGES.index(node["stage"])
    parents = node["parent_ids"]
    if index == 0:
        if set(parents) != set(ids) or len(parents) != len(ids):
            issues.append("script parents must be the exact claim set")
    else:
        previous = [nodes.get(parent) for parent in parents]
        if (
            not parents
            or len(parents) != len(set(parents))
            or any(parent is None or parent["stage"] != STAGES[index - 1] for parent in previous)
        ):
            issues.append("missing or incorrect preceding production stage")
        elif set(ids) != {claim_id for parent in previous for claim_id in parent["claim_ids"]}:
            issues.append("claim set differs from parent lineage")
    return [f"{node['id']}: {issue}" for issue in issues]


def _validate_packet_data(data: dict, source_root: Path) -> dict:
    """Keep source integrity, exact support, lineage and semantic review separate."""
    root = source_root.resolve()
    passages, source_errors = {}, []
    for source in data["sources"]:
        errors = _source_issues(source, root)
        source_errors.extend(errors)
        if not errors:
            passages.update({(source["id"], p["id"]): p["quote"] for p in source["passages"]})
    claims = {claim["id"]: claim for claim in data["claims"]}
    support = {key: _claim_support(claim, passages) for key, claim in claims.items()}
    nodes = {node["id"]: node for node in data["lineage"]}
    lineage_errors = [
        issue for node in nodes.values() for issue in _lineage_issues(node, nodes, claims, support)
    ]
    missing = {
        key: [
            stage
            for stage in STAGES
            if not any(
                node["stage"] == stage and key in node["claim_ids"] for node in nodes.values()
            )
        ]
        for key in claims
    }
    passed = bool(claims) and not source_errors and not lineage_errors
    passed = passed and all(value == "exact_source_text" for value in support.values())
    passed = passed and not any(missing.values())
    return {
        "source_errors": source_errors,
        "claim_support": support,
        "lineage_errors": lineage_errors,
        "missing_stages": missing,
        "contract_passed": bool(passed),
        "factual_success": False,
        "semantic_support": "not_verified",
        "source_content_role": "data",
    }


def validate_evidence_packet(packet: EvidencePacket | dict, source_root: Path) -> dict:
    """Validate retained sources and the five-stage exact-claim chain."""
    from .local_path_policy import enforce_local_access_root

    root = enforce_local_access_root(source_root)
    parsed = packet if isinstance(packet, EvidencePacket) else EvidencePacket.model_validate(packet)
    return _validate_packet_data(parsed.model_dump(mode="json"), root)
