"""Revision-bound sentence WAV runs with durable outcomes and contained previews.

This owned entrypoint produces audio artifacts; external renderer consumption
and spoken semantic truth remain separate, unverified boundaries.
"""

import asyncio
import hashlib
from pathlib import Path
import re

from .evidence import atomic_write
from .models.narration import NarrationRequest
from .narration_pcm import artifact, atomic_bytes, concatenate, contained, qualify, snapshot
from .narration_provider import ProviderError, public_selection, selection, synthesize
from .plan_artifacts import require_binding
from .planning import require_approved
from .planning_sources import canonical, digest, read_object


def admission(project: Path, state: dict, script: dict) -> dict:
    """Read original commitments and actual bound script rather than trusting the caller."""
    require_approved(project, state)
    actual = require_binding(project, state, "script")
    if canonical(actual) != canonical(script):
        raise ValueError("Supplied script differs from the actual current binding")
    return {"plan_revision": state["revision"], "plan_sha256": state["plan_sha256"],
            "source_commitment_sha256": state["source_commitment_sha256"],
            "parent_script_sha256": state["bindings"]["script"]["sha256"]}


def split_sentences(text: str) -> list[str]:
    """Partition punctuation boundaries while retaining every original character."""
    pieces, start = [], 0
    pattern = r'''(?:[。！？]+|[.!?]+(?=["”’']*(?:\s|$)))["”’']*\s*'''
    for match in re.finditer(pattern, text):
        pieces.append(text[start:match.end()])
        start = match.end()
    if start < len(text):
        pieces.append(text[start:])
    if not pieces or "".join(pieces) != text or any(not piece.strip() for piece in pieces):
        raise ValueError("Approved narration must partition into nonempty exact sentences")
    return pieces


def scene_selection(script: dict, request: NarrationRequest) -> list[dict]:
    """Preview exactly one approved scene; generate/custom retain the full scene population."""
    scenes = script["scenes"]
    if request.action != "preview":
        return scenes
    selected = str(request.scene_id) if request.scene_id is not None else str(scenes[0]["scene_id"])
    matches = [scene for scene in scenes if str(scene["scene_id"]) == selected]
    if len(matches) != 1:
        raise ValueError("Selected preview scene does not exist")
    return matches


def sentence_population(scenes: list[dict], *, custom=False) -> list[dict]:
    """Keep failed and unrun sentences in the exact required denominator."""
    rows, offset = [], 0
    for scene in scenes:
        for text in split_sentences(scene["voiceover"]):
            rows.append({"index": len(rows), "scene_id": scene["scene_id"], "text": text,
                         "text_begin": offset, "text_end": offset + len(text), "status": "unrun"})
            offset += len(text)
    if custom:
        return [{"index": 0, "scene_id": None, "text": "".join(row["text"] for row in rows),
                 "text_begin": 0, "text_end": offset, "status": "unrun", "scene_timing": "absent_custom_audio"}]
    return rows


def save(context: dict) -> None:
    """Fsync an owned artifact receipt independently of the caller's plan transaction."""
    path = contained(context["project"], str(context["receipt_path"].relative_to(context["project"])))
    atomic_write(path, canonical(context["receipt"]))


def result(context: dict, *, cached=False) -> dict:
    """Return inspectable measured artifacts without promoting incomplete audio."""
    receipt = context["receipt"]
    accepted = receipt["status"] == "accepted"
    value = {**receipt, "success": accepted, "cache_hit": cached,
             "receipt": {"path": str(context["receipt_path"].relative_to(context["project"])),
                         "sha256": read_object(context["receipt_path"], context["project"])[1]}}
    if accepted:
        value["binding"] = {**value["receipt"], **context["commitment"],
                            "audio_path": receipt["artifact"]["path"], "audio_sha256": receipt["artifact"]["sha256"]}
    return value


def cached_result(context: dict) -> dict:
    """Reuse only the same commitment/configuration and exact qualified WAV bytes."""
    stored, sha = read_object(context["receipt_path"], context["project"])
    expected = context["receipt"]
    if any(stored.get(key) != expected[key] for key in ("cache_key", "configuration", "commitment", "transcript", "script_transcript", "action")):
        raise ValueError("Narration cache receipt differs from current authority")
    context["receipt"] = stored
    if stored["status"] != "accepted":
        return {**result(context, cached=True), "reason": "existing_run_unaccepted; regeneration_refused"}
    if context["state"].get("narration_cache", {}).get(stored["cache_key"]) != sha:
        raise ValueError("Accepted narration cache receipt differs from its trusted plan digest")
    selected = stored["artifact"]
    path = contained(context["project"], selected["path"])
    measured = artifact(path, context["project"], snapshot(path))
    if measured != selected:
        raise ValueError("Cached audio bytes or measurements changed")
    for row in stored["sentences"]:
        child = row["artifact"]
        child_path = contained(context["project"], child["path"])
        if artifact(child_path, context["project"], snapshot(child_path)) != child:
            raise ValueError("Cached sentence artifact changed")
    return result(context, cached=True)


def prepare(project: Path, state: dict, script: dict, request: NarrationRequest, selected: dict) -> dict:
    """Create one exclusive configuration/script/text-bound staging directory."""
    commitment = admission(project, state, script)
    scenes = scene_selection(script, request)
    custom = snapshot(contained(project, request.custom_audio)) if request.action == "custom" else None
    if custom is not None:
        qualify(custom)
    config = {"request": request.model_dump(), "provider": public_selection(selected),
              "pcm": "PCM16 mono", "pause_policy": "quantized_each_sentence_including_final",
              "custom_sha256": hashlib.sha256(custom).hexdigest() if custom is not None else None}
    transcript = "".join(scene["voiceover"] for scene in scenes)
    key = digest({"configuration": config, "commitment": commitment, "transcript": transcript})
    directory = contained(project, f".narration/{key}")
    receipt = {"schema_version": 1, "cache_key": key, "action": request.action, "configuration": config,
               "commitment": commitment, "transcript": transcript,
               "script_transcript": [{"scene_id": s["scene_id"], "text": s["voiceover"]} for s in script["scenes"]],
               "status": "pending", "sentences": sentence_population(scenes, custom=custom is not None),
               "word_alignment": "pending", "artifact": None,
               "video_research_plan": {"revision": state["revision"], "plan_sha256": state["plan_sha256"],
               "source_commitment_sha256": state["source_commitment_sha256"], "approval_role": "editorial",
               "factual_success": False, "visual_audio_semantics": "not_verified",
               "parent_script_sha256": commitment["parent_script_sha256"]},
               "renderer_consumption": "unverified", "spoken_semantics": "unverified"}
    return {"project": project, "state": state, "directory": directory, "receipt_path": directory / "receipt.json",
            "receipt": receipt, "commitment": commitment, "custom": custom, "scenes": scenes}


async def sentences(context: dict, selected: dict) -> list[bytes]:
    """Persist dispatch before every POST and preserve returned bytes before local checks."""
    clips = []
    for row in context["receipt"]["sentences"]:
        row["status"] = context["receipt"]["status"] = "dispatching"
        save(context)
        path = context["directory"] / f"sentence-{row['index']:04d}.returned.wav"

        def returned(body, details):
            row.update(provider_outcome="accepted", provider=details)
            if body is not None:
                atomic_bytes(path, body)
                row["returned_audio"] = {"path": str(path.relative_to(context["project"])),
                                         "sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            row["status"] = "provider_returned"
            save(context)

        outcome = await synthesize(row["text"], selected, returned)
        body = outcome["audio"]
        qualify(body)
        if snapshot(path) != body:
            raise ValueError("Returned sentence bytes changed before measurement")
        row.update(status="accepted", artifact=artifact(path, context["project"], body),
                   words=outcome["words"], alignment=outcome["alignment"], usage=outcome["usage"])
        clips.append(body)
        save(context)
    return clips


def timings(context: dict, intervals: list[dict], rate: int) -> None:
    """Offset real provider/synthetic events using decoded frames rather than text lengths."""
    words = []
    for row, bounds in zip(context["receipt"]["sentences"], intervals, strict=True):
        row.update(**bounds, start_seconds=bounds["start_frame"] / rate,
                   audio_end_seconds=bounds["audio_end_frame"] / rate, end_seconds=bounds["end_frame"] / rate)
        for word in row.get("words") or []:
            first, last = bounds["start_frame"] + word["start_frame"], bounds["start_frame"] + word["end_frame"]
            words.append({**word, "text_begin": row["text_begin"] + word["text_begin"],
                          "text_end": row["text_begin"] + word["text_end"], "start_frame": first,
                          "end_frame": last, "start_seconds": first / rate, "end_seconds": last / rate})
    context["receipt"].update(words=words if all(row.get("words") is not None for row in context["receipt"]["sentences"]) else None,
                               word_alignment="synthetic_event; tones are not speech" if context["receipt"]["configuration"]["provider"]["provider"] == "mock" else
                               "provider_declared; semantic correctness unverified" if words else "absent")


def within_budget(context: dict, state: dict) -> None:
    """Reject measured over-budget performances without rewriting script/storyboard timing."""
    receipt = context["receipt"]
    budgets = {str(s["scene_id"]): p["duration_seconds"] for s, p in zip(
        receipt["script_transcript"], state["plan"]["scenes"], strict=True)}
    if receipt["action"] == "custom":
        if receipt["artifact"]["duration_seconds"] > min(sum(budgets.values()), state["plan"]["duration_budget_seconds"]):
            raise ValueError("Custom audio exceeds the approved duration budget")
        return
    for scene in context["scenes"]:
        duration = sum((r["end_frame"] - r["start_frame"]) / r["artifact"]["sample_rate"]
                       for r in receipt["sentences"] if r["scene_id"] == scene["scene_id"])
        if duration > budgets[str(scene["scene_id"])]:
            raise ValueError("Measured narration scene exceeds its approved duration budget")
    if receipt["artifact"]["duration_seconds"] > state["plan"]["duration_budget_seconds"]:
        raise ValueError("Measured narration exceeds the approved total duration budget")


def promote(context: dict, state: dict, script: dict, body: bytes) -> dict:
    """Promote only after exact approval/script/custom readback and measured budget checks."""
    project, receipt = context["project"], context["receipt"]
    if admission(project, state, script) != context["commitment"]:
        raise ValueError("Narration parent commitments changed during production")
    if context["custom"] is not None and snapshot(contained(project, receipt["configuration"]["request"]["custom_audio"])) != context["custom"]:
        raise ValueError("Custom audio changed during production")
    path = context["directory"] / "narration.wav"
    receipt["artifact"] = artifact(path, project, body)
    within_budget(context, state)
    atomic_bytes(path, body)
    if artifact(path, project, snapshot(path)) != receipt["artifact"] or admission(project, state, script) != context["commitment"]:
        raise ValueError("Narration changed during artifact promotion")
    receipt["status"] = "accepted"
    save(context)
    value = result(context)
    state.setdefault("narration_cache", {})[receipt["cache_key"]] = value["receipt"]["sha256"]
    return value


async def produce_narration(project: Path, state: dict, script: dict, request: NarrationRequest) -> dict:
    """Produce a measured WAV under the caller's current real plan transaction."""
    try:
        selected = selection(request)
    except ValueError as error:
        return {"success": False, "status": "refused", "reason": "configuration_refused", "detail": str(error)}
    try:
        context = prepare(project, state, script, request, selected)
        if context["directory"].exists():
            cached = cached_result(context)
            if admission(project, state, script) != context["commitment"]:
                raise ValueError("Narration commitments changed during cache readback")
            return cached
        contained(project, ".narration").mkdir(mode=0o700, exist_ok=True)
        context["directory"].mkdir(mode=0o700)
        save(context)
    except (OSError, ValueError, KeyError) as error:
        return {"success": False, "status": "refused", "reason": "admission_or_cache_refused", "error_type": type(error).__name__}
    try:
        if context["custom"] is None:
            body, intervals = concatenate(await sentences(context, selected), request.pause_seconds)
        else:
            body = context["custom"]
            path = context["directory"] / "custom.returned.wav"
            atomic_bytes(path, body)
            row = context["receipt"]["sentences"][0]
            row.update(status="accepted", artifact=artifact(path, project, body), words=None, alignment="absent_custom_audio")
            intervals = [{"start_frame": 0, "audio_end_frame": row["artifact"]["frames"], "end_frame": row["artifact"]["frames"], "pause_frames": 0}]
        _, measured = qualify(body)
        timings(context, intervals, measured["sample_rate"])
        await asyncio.sleep(0)
        return promote(context, state, script, body)
    except asyncio.CancelledError:
        context["receipt"]["status"] = "unknown" if selected["provider"] not in ("mock", "custom") else "cancelled"
        context["receipt"]["reason"] = "cancelled; no accepted artifact promoted"
        for row in context["receipt"]["sentences"]:
            if row["status"] in ("dispatching", "provider_returned"):
                row["status"] = context["receipt"]["status"]
        save(context)
        raise
    except Exception as error:
        receipt = context["receipt"]
        receipt.update(status="unknown" if isinstance(error, ProviderError) and error.outcome == "unknown" else "failed",
                       reason=error.reason if isinstance(error, ProviderError) else "local_audio_or_binding_refused",
                       error_type=type(error).__name__, provider_status=error.status if isinstance(error, ProviderError) else None, artifact=None)
        for row in receipt["sentences"]:
            if row["status"] in ("dispatching", "provider_returned"):
                row.update(status=receipt["status"], provider_outcome=error.outcome if isinstance(error, ProviderError) else row.get("provider_outcome", "not_verified"))
        save(context)
        return result(context)
