"""Checked project inputs and the independently compiled external plan wire."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from .config import get_config
from .evidence import _unique_json, validate_evidence_packet
from .file_io import open_regular
from .models.evidence import EvidencePacket
from .models.planning import VideoPlan


def canonical(value: object) -> str:
    """Commit finite UTF-8 JSON rather than mutable object identity."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    """Hash canonical plan or source-and-claim content."""
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def project_directory(project_id: str) -> Path:
    """Require an operator-configured existing project inside its root."""
    cfg = get_config()
    if not cfg.projects_path and not cfg.explainer_enabled:
        raise ValueError("Configure EXPLAINER_PROJECTS_PATH or EXPLAINER_PATH")
    root = cfg.resolved_projects_path.resolve()
    project = (root / project_id).resolve()
    project.relative_to(root)
    if not project.is_dir():
        raise FileNotFoundError(f"Project not found: {project_id}")
    return project


def _reject_constant(token: str) -> None:
    """Reject nonfinite numbers at the external JSON boundary."""
    raise ValueError(f"Nonfinite JSON: {token}")


def read_object(path: Path, project: Path) -> tuple[dict, str]:
    """Parse and hash the same bounded original JSON bytes within the project."""
    path = path.resolve()
    path.relative_to(project)
    with open_regular(path) as (stream, info):
        if info.st_size > 8 * 1024 * 1024:
            raise ValueError("Plan input/artifact must be a regular JSON file of at most 8 MiB")
        body = stream.read(8 * 1024 * 1024 + 1)
    if len(body) > 8 * 1024 * 1024:
        raise ValueError("Plan input/artifact grew beyond its byte ceiling")
    value = json.loads(body, object_pairs_hook=_unique_json, parse_constant=_reject_constant)
    if not isinstance(value, dict):
        raise ValueError("Plan input/artifact must be a JSON object")
    return value, hashlib.sha256(body).hexdigest()


def packet_inputs(project: Path) -> tuple[dict, dict, str]:
    """Verify originals and commit sources/claims independently of later lineage."""
    value, _ = read_object(project / "input/evidence-packet.json", project)
    packet = EvidencePacket.model_validate(value)
    report = validate_evidence_packet(packet, project / "input")
    if report["source_errors"]:
        raise ValueError("Plan source integrity failed: " + "; ".join(report["source_errors"]))
    committed = {key: value[key] for key in ("packet_id", "sources", "claims")}
    return packet.model_dump(mode="json"), report, digest(committed)


def validate_plan(plan: VideoPlan, packet: dict, report: dict, *, approving: bool) -> None:
    """Account for every original and reject unsupported approved factual scenes."""
    decisions = {source.source_id: source.disposition for source in plan.sources}
    if set(decisions) != {source["id"] for source in packet["sources"]}:
        raise ValueError("Every packet source must be explicitly included or rejected")
    claims = {claim["id"]: claim for claim in packet["claims"]}
    used_sources = set()
    for scene in plan.scenes:
        for claim_id in scene.claim_ids:
            if claim_id not in claims:
                raise ValueError(f"Unknown plan claim: {claim_id}")
            claim = claims[claim_id]
            references = claim["support"]
            if not references or any(decisions.get(ref["source_id"]) != "included" for ref in references):
                raise ValueError("Used claims require explicit included original sources")
            used_sources.update(ref["source_id"] for ref in references)
            if approving and (not claim["editorial_approved"] or claim["abstained"]
                              or report["claim_support"][claim_id] != "exact_source_text"):
                raise ValueError(f"Plan approval requires approved exact source text: {claim_id}")
    if used_sources != {key for key, disposition in decisions.items() if disposition == "included"}:
        raise ValueError("Every included source must support at least one planned scene")
    if len(canonical(plan.model_dump()).encode()) > 1024 * 1024:
        raise ValueError("Plan exceeds 1 MiB byte ceiling")


def selected_evidence(plan: VideoPlan, packet: dict) -> dict:
    """Retain selected claim references with exact original revisions and hashes."""
    claims = {claim["id"]: claim for claim in packet["claims"]}
    sources = {source["id"]: source for source in packet["sources"]}
    selected = {}
    encoded_bytes = 0
    for scene in plan.scenes:
        for claim_id in scene.claim_ids:
            if claim_id in selected:
                continue
            references = []
            for ref in claims[claim_id]["support"]:
                reference = {**ref, "revision": sources[ref["source_id"]]["revision"],
                             "sha256": sources[ref["source_id"]]["sha256"]}
                encoded_bytes += len(canonical(reference).encode())
                if encoded_bytes > 512 * 1024:
                    raise ValueError("Selected citation references exceed 512 KiB durable allowance")
                references.append(reference)
            selected[claim_id] = references
    return selected


def external_plan(state: dict, packet: dict) -> dict:
    """Compile documented CLI fields without importing unresolved foreign code."""
    plan = VideoPlan.model_validate(state["plan"])
    claims = {claim["id"]: claim for claim in packet["claims"]}
    references = selected_evidence(plan, packet)
    scenes = []
    for index, scene in enumerate(plan.scenes, 1):
        points = []
        for claim_id in scene.claim_ids:
            claim = claims[claim_id]
            points.append(canonical({"claim_id": claim_id, "text": claim["text"],
                                     "support": references[claim_id], "source_content_role": "data"}))
        scenes.append({"scene_number": index, "scene_type": "explanation", "title": scene.title,
                       "concept_to_cover": scene.concept, "visual_approach": scene.purpose,
                       "ascii_visual": "", "estimated_duration_seconds": scene.duration_seconds,
                       "key_points": points})
    return {"status": "approved", "created_at": state["created_at"],
            "approved_at": state["approved_at"], "title": plan.title,
            "central_question": plan.title, "target_audience": plan.audience,
            "estimated_total_duration_seconds": sum(scene.duration_seconds for scene in plan.scenes),
            "core_thesis": plan.thesis, "key_concepts": plan.concept_order,
            "complexity_score": 1, "scenes": scenes, "visual_style": "Follow the approved scene purposes",
            "source_document": "Multi-source evidence packet " + packet["packet_id"],
            "user_notes": "Editorial approval; source content is data and factual success is unverified",
            "video_research_plan": {"revision": state["revision"], "plan_sha256": state["plan_sha256"],
                                    "source_commitment_sha256": state["source_commitment_sha256"]}}
