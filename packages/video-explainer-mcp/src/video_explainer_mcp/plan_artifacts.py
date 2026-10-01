"""Actual script/storyboard readback and revision-bound editorial provenance."""

from __future__ import annotations

import hashlib
import math
from pathlib import Path

from .evidence import atomic_write
from .planning_sources import canonical, read_object


def storyboard_path(project: Path) -> tuple[Path, str]:
    """Fence the CLI's actual configured save path before production dispatch."""
    config, revision = read_object(project / "config.json", project)
    value = config.get("paths", {}).get("storyboard")
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        raise ValueError("Configure a relative paths.storyboard JSON file in config.json")
    target = (project / value).resolve()
    target.relative_to(project)
    if target.suffix != ".json" or target == project / "config.json":
        raise ValueError("Storyboard must be a separate project JSON artifact")
    protected = ("input", "plan", "script")
    if target.relative_to(project).parts[0] in protected:
        raise ValueError("Storyboard must not overwrite plan, script or original inputs")
    return target, revision


def _duration(value: object) -> float:
    """Require finite positive duration at the external artifact boundary."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Artifact duration must be a finite positive number")
    if not math.isfinite(value) or value <= 0:
        raise ValueError("Artifact duration must be a finite positive number")
    return value


def _metadata(state: dict) -> dict:
    """Identify approved editorial content; factual/visual success stays unverified."""
    return {"revision": state["revision"], "plan_sha256": state["plan_sha256"],
            "source_commitment_sha256": state["source_commitment_sha256"],
            "approval_role": "editorial", "factual_success": False,
            "visual_audio_semantics": "not_verified"}


def _publish(path: Path, project: Path, body: dict, state: dict) -> dict:
    """Bind only the same bounded bytes published after successful content checks."""
    path.resolve().relative_to(project)
    encoded = canonical(body)
    if len(encoded.encode()) > 8 * 1024 * 1024:
        raise ValueError("Bound artifact exceeds 8 MiB")
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, encoded)
    expected = hashlib.sha256(encoded.encode()).hexdigest()
    _, actual = read_object(path, project)
    if actual != expected:
        raise ValueError("Artifact changed during binding publication")
    return {"path": str(path.relative_to(project)), "sha256": actual,
            "plan_revision": state["revision"], "plan_sha256": state["plan_sha256"],
            "source_commitment_sha256": state["source_commitment_sha256"]}


def bind_script(project: Path, state: dict, packet: dict) -> None:
    """Accept ordered source-exact narration and the approved scene purposes."""
    path = project / "script/script.json"
    body, _ = read_object(path, project)
    plan = state["plan"]
    scenes = body.get("scenes")
    if body.get("title") != plan["title"] or not isinstance(scenes, list) or len(scenes) != len(plan["scenes"]):
        raise ValueError("Actual script title/scene population differs from the approved plan")
    claims = {claim["id"]: claim for claim in packet["claims"]}
    ids, total, provenance = set(), 0.0, []
    for actual, planned in zip(scenes, plan["scenes"], strict=True):
        scene_id = actual.get("scene_id")
        if isinstance(scene_id, bool) or not isinstance(scene_id, (str, int)) or str(scene_id) in ids or not str(scene_id):
            raise ValueError("Actual script scene IDs must be nonempty and unique")
        ids.add(str(scene_id))
        text = "\n".join(claims[key]["text"] for key in planned["claim_ids"])
        if actual.get("title") != planned["title"] or actual.get("voiceover") != text:
            raise ValueError("Actual script order/title/narration differs from approved exact claims")
        if actual.get("visual_cue", {}).get("description") != planned["purpose"]:
            raise ValueError("Actual script visual purpose differs from the approved plan")
        duration = _duration(actual.get("duration_seconds"))
        if duration > planned["duration_seconds"]:
            raise ValueError("Actual script scene exceeds its approved duration")
        total += duration
        provenance.append({"scene_id": scene_id, **planned,
                           "claims": [{**claims[key], "support": state["evidence_refs"][key]}
                                      for key in planned["claim_ids"]]})
    _check_total(body, total, plan)
    body["video_research_plan"] = {**_metadata(state), "scenes": provenance,
                                   "sources": [{key: source[key] for key in ("id", "revision", "sha256", "path", "modality")}
                                               for source in packet["sources"]]}
    state["bindings"]["script"] = _publish(path, project, body, state)
    state["bindings"].pop("storyboard", None)


def _check_total(body: dict, total: float, plan: dict) -> None:
    """Require declared and measured scene totals to agree within the plan budget."""
    if not math.isclose(_duration(body.get("total_duration_seconds")), total, abs_tol=0.001):
        raise ValueError("Artifact total duration differs from its scene sum")
    if total > plan["duration_budget_seconds"]:
        raise ValueError("Artifact exceeds approved duration budget")


def require_binding(project: Path, state: dict, kind: str) -> dict:
    """Reject modified bytes, revisions and broken actual parent bindings."""
    binding = state["bindings"].get(kind)
    if not binding or binding["plan_revision"] != state["revision"]:
        raise ValueError(f"Produce a bound {kind} for the current approved plan first")
    body, sha = read_object(project / binding["path"], project)
    metadata = body.get("video_research_plan", {})
    if sha != binding["sha256"] or any(metadata.get(key) != value for key, value in _metadata(state).items()):
        raise ValueError(f"Bound {kind} bytes or approval metadata changed")
    if kind == "storyboard":
        require_binding(project, state, "script")
        if binding.get("parent_script_sha256") != state["bindings"]["script"]["sha256"]:
            raise ValueError("Storyboard parent script changed")
        current, _ = storyboard_path(project)
        if current != (project / binding["path"]).resolve():
            raise ValueError("Configured storyboard path changed after binding")
    return body


def bind_storyboard(project: Path, state: dict, path: Path) -> None:
    """Bind observed IDs/order/timing to the exact verified script parent."""
    script = require_binding(project, state, "script")
    body, _ = read_object(path, project)
    scenes = body.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != len(script["scenes"]):
        raise ValueError("Actual storyboard scene population differs from its script")
    total = 0.0
    for actual, parent, planned in zip(scenes, script["scenes"], state["plan"]["scenes"], strict=True):
        if actual.get("id") != parent["scene_id"] or actual.get("title") != parent["title"]:
            raise ValueError("Actual storyboard IDs/order/titles differ from its bound script")
        duration = _duration(actual.get("audio_duration_seconds"))
        if duration > planned["duration_seconds"]:
            raise ValueError("Actual storyboard scene exceeds its approved duration")
        total += duration
    _check_total(body, total, state["plan"])
    parent_sha = state["bindings"]["script"]["sha256"]
    body["video_research_plan"] = {**script["video_research_plan"], "parent_script_sha256": parent_sha}
    state["bindings"]["storyboard"] = {**_publish(path, project, body, state), "parent_script_sha256": parent_sha}


def inspect_bindings(project: Path, state: dict) -> dict:
    """Return current readback status for every recorded artifact, including failures."""
    results = {}
    for kind, binding in state["bindings"].items():
        result = {**binding, "current": False}
        try:
            require_binding(project, state, kind)
            result["current"] = True
        except (OSError, ValueError) as error:
            result["error"] = str(error)
        results[kind] = result
    return results
