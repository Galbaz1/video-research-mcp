"""Durable source analysis preparation, executable dubbing and delivery validation."""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
from pathlib import Path
import shutil
import time

from . import dubbing_client as client
from . import dubbing_render as render
from .dubbing_contracts import (
    artifact, listening_status, project, read_json, validate_plan, verify_artifact,
)
from .media_snapshot import checked_path, snapshot
from .models.video_dubbing import Project, VadEvidence


@contextmanager
def operation(root: Path):
    """Exclude simultaneous writers to one project; never remove another lock."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock = root / ".dubbing-operation.lock"
    try:
        with lock.open("xb"):
            pass
    except FileExistsError:
        raise client.DubbingError("project_operation_occupied") from None
    try:
        yield
    finally:
        lock.unlink()


async def prepare(source_movie: str, project_dir: str, source_language: str,
                  target_language: str, expected_source_sha256: str,
                  target: str = "full", style_brief: str = "") -> dict:
    """Prepare exact local source, stems and VAD before agent source analysis.

    Args:
        source_movie: Approved local video input.
        project_dir: Exclusive durable output directory within the local fence.
        source_language: Source language or auto for agent language detection.
        target_language: Requested spoken translation language.
        expected_source_sha256: Exact approved source revision.
        target: Requested analysis, translation, full or resumed workflow.
        style_brief: User-approved spoken translation and delivery style.

    Returns:
        Terminal readiness evidence or a prepared project and next analysis step.
    """
    root = checked_path(project_dir)
    if not source_language.strip() or not target_language.strip() or target_language == "auto":
        raise client.DubbingError("project_languages_invalid")
    with operation(root):
        readiness = await client.health()
        client.write_json(root / "readiness.json", readiness)
        if readiness["terminal"]:
            return {"status": "readiness_terminal", "readiness": readiness,
                    "feature_acceptance": "UNQUALIFIED", "project_dir": str(root)}
        if (root / "project.json").exists():
            existing = project(root)
            if (existing.source_movie != str(checked_path(source_movie))
                    or existing.source_sha256 != expected_source_sha256
                    or existing.source_language != source_language or existing.target_language != target_language
                    or existing.style_brief != style_brief or (target != "resume" and existing.target != target)):
                raise client.DubbingError("existing_project_request_mismatch")
            return state(project_dir)
        await _prepare_media(root, source_movie, source_language, target_language,
                             expected_source_sha256, target, style_brief)
        return state(project_dir)


async def _prepare_media(root, source_movie, source_language, target_language,
                         expected_source_sha256, target, style_brief) -> None:
    """Prepare and publish source evidence only after exact snapshot readback."""
    source = checked_path(source_movie)
    if source.is_relative_to(root):
        raise client.DubbingError("source_must_be_outside_project")
    async with snapshot(source_movie, expected_source_sha256) as owned:
        observed = await render.inspect_media(str(owned.path))
        duration = observed["duration_seconds"]
        if (duration is None or not 0 < duration <= (client.MAX_AUDIO_BYTES - 4096) / (48000 * 2 * 2)
                or not any(s.get("codec_type") == "video" for s in observed["streams"])
                or not any(s.get("codec_type") == "audio" for s in observed["streams"])):
            raise client.DubbingError("source_video_audio_duration_or_pcm_bound_invalid")
        local_source = root / "work/source" / ("source" + source.suffix.lower())
        local_source.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if not local_source.exists():
            shutil.copyfile(owned.path, local_source)
        if artifact(local_source)["sha256"] != owned.sha256:
            raise client.DubbingError("local_source_changed")
        audio = await render.extract_audio(local_source, local_source.parent / "source.wav")
        stems = await client.separate(Path(audio["path"]), local_source.parent)
        speech = await client.vad(Path(stems["vocals"]["path"]), root / "analysis")
        evidence = VadEvidence(source_movie=str(source), source_sha256=owned.sha256,
                               audio_sha256=stems["vocals"]["sha256"], **speech,
                               parameters=client.VAD_PARAMETERS)
        client.write_json(root / "analysis/vad.json", evidence.model_dump())
        manifest = Project(source_movie=str(source), source_sha256=owned.sha256,
                           source_language=source_language, target_language=target_language,
                           target=target, style_brief=style_brief,
                           duration_sec=duration, source=artifact(local_source), source_audio=audio,
                           vocals={k: stems["vocals"][k] for k in ("path", "sha256", "bytes")},
                           no_vocals={k: stems["no_vocals"][k] for k in ("path", "sha256", "bytes")},
                           vad=artifact(root / "analysis/vad.json"))
        await owned.verify()
        client.write_json(root / "project.json", manifest.model_dump())


def state(project_dir: str) -> dict:
    """Derive the next workflow from actual content identities, never filenames."""
    root = checked_path(project_dir)
    if not (root / "project.json").exists():
        readiness = read_json(root / "readiness.json") if (root / "readiness.json").exists() else None
        return {"status": "unprepared", "readiness": readiness, "feature_acceptance": "UNQUALIFIED"}
    manifest = project(root)
    plan_path = root / "plan/translation_plan.json"
    next_action = "reconcile_source_transcript"
    validation = None
    if plan_path.exists():
        _, _, validation = validate_plan(root, plan_path)
        next_action = "render_validated_plan"
        if manifest.target == "translation_only":
            next_action = "translation_only_complete"
    if manifest.target == "analysis_only":
        next_action = "review_source_transcript_and_stop"
    if (root / "full/current.json").exists():
        next_action = "validate_and_listen_to_current_delivery"
    return {"status": "prepared", "project_dir": str(root), "source": manifest.source.model_dump(),
            "source_movie": manifest.source_movie, "source_sha256": manifest.source_sha256,
            "duration_sec": manifest.duration_sec,
            "target": manifest.target, "style_brief": manifest.style_brief,
            "analysis_mode": "single_full_video" if manifest.duration_sec <= 600 else "bounded_windows",
            "vad": manifest.vad.model_dump(), "plan_validation": validation,
            "next_action": next_action, "feature_acceptance": "UNQUALIFIED"}


async def render_project(project_dir: str, plan_path: str, background_mode: str,
                         regenerate_segment_ids: list[str] | None = None) -> dict:
    """Render a validated plan with journaled service and bounded local execution."""
    root = checked_path(project_dir)
    if background_mode not in {"include", "omit"}:
        raise client.DubbingError("background_mode_invalid")
    with operation(root):
        manifest, plan, validation = validate_plan(root, Path(plan_path))
        regenerate = set(regenerate_segment_ids or [])
        if regenerate - {group.segment_id for group in plan.segments}:
            raise client.DubbingError("regenerate_segment_id_unknown")
        readiness = await client.health()
        client.write_json(root / "readiness.json", readiness)
        if readiness["terminal"]:
            return {"status": "readiness_terminal", "readiness": readiness, "feature_acceptance": "UNQUALIFIED"}
        key = hashlib.sha256(client.canonical({"plan": validation["plan_sha256"],
                                             "project": manifest.model_dump(), "background_mode": background_mode})).hexdigest()
        destination = root / "renders" / key
        voices = []
        try:
            for group, slot in zip(plan.segments, validation["slots"]):
                voices.append(await render.synthesize_group(root, manifest, plan, group, slot,
                                                            group.segment_id in regenerate))
            key = hashlib.sha256(client.canonical({"base": key, "voices": [v["audio"] for v in voices]})).hexdigest()
            destination = root / "renders" / key
            premix, mixed, stem_mix = await render.mix(destination, manifest, voices, background_mode)
            output = await render.remux(destination, manifest, mixed)
            qa = await render.technical_qa(root, manifest, output, mixed, voices)
            final_manifest, _, final_validation = validate_plan(root, Path(plan_path))
            if final_manifest != manifest or final_validation != validation:
                raise client.DubbingError("render_inputs_changed")
            report = {"schema_version": "vrm/video-dubbing-render/v1", "project": manifest.model_dump(),
                      "plan": artifact(Path(plan_path)), "output": output, "premix": premix,
                      "mix": mixed, "stem_mix": stem_mix, "segments": voices, "qa": qa}
            client.write_json(destination / "full/render_report.json", report)
            client.write_json(destination / "full/final_qa.json", qa)
            if not qa["technical_pass"]:
                raise client.DubbingError("technical_qa_failed")
            client.write_json(root / "full/current.json", {"render_dir": str(destination),
                                                         "report": artifact(destination / "full/render_report.json"),
                                                         "qa": artifact(destination / "full/final_qa.json")})
        except Exception as exc:
            client.write_json(destination / f"render_failure_{time.time_ns()}.json",
                              {"status": "FAILED", "reason": str(exc) if isinstance(exc, client.DubbingError) else "render_boundary_failed",
                               "plan_sha256": validation["plan_sha256"], "completed_segments": voices,
                               "timing": "FAIL" if isinstance(exc, client.DubbingError) and str(exc).startswith("timing_failed") else "UNKNOWN",
                               "listening": "UNRESOLVED", "feature_acceptance": "UNQUALIFIED"})
            raise
        return _delivery_result(destination, report, plan, validation, qa)


def _process_record(value: dict, root: Path) -> dict:
    """Check executed command custody, current inputs and current output bytes."""
    path = verify_artifact(value, root)
    record = read_json(path.with_suffix(path.suffix + ".process.json"))
    for item in record.get("inputs", []):
        verify_artifact(item, root)
    signature = hashlib.sha256(client.canonical({"argv": record.get("argv"),
                                                 "inputs": record.get("inputs")})).hexdigest()
    if (record.get("state") != "complete" or record.get("output") != value
            or record.get("signature") != signature):
        raise client.DubbingError("render_process_record_invalid")
    return record


async def validate_delivery(project_dir: str) -> dict:
    """Re-execute technical QA; report supplied listening evidence independently.

    Args:
        project_dir: Prepared project with a current content-addressed render.

    Returns:
        Exact output/report identities, measured checks and unresolved segments.
    """
    root = checked_path(project_dir)
    pointer = read_json(root / "full/current.json")
    report_path = verify_artifact(pointer["report"], root)
    qa_path = verify_artifact(pointer["qa"], root)
    report = read_json(report_path)
    manifest, plan, validation = validate_plan(root, Path(report["plan"]["path"]))
    destination = checked_path(pointer["render_dir"])
    if not destination.is_relative_to(root) or report_path != destination / "full/render_report.json":
        raise client.DubbingError("render_directory_mismatch")
    if (report.get("schema_version") != "vrm/video-dubbing-render/v1"
            or report["project"] != manifest.model_dump() or artifact(Path(report["plan"]["path"])) != report["plan"]
            or report["qa"] != read_json(qa_path)):
        raise client.DubbingError("render_report_hash_join_mismatch")
    voices = report["segments"]
    if len(voices) != len(plan.segments):
        raise client.DubbingError("render_segment_accounting_mismatch")
    for voice, group, slot in zip(voices, plan.segments, validation["slots"]):
        if (any(voice.get(k) != slot[k] for k in ("segment_id", "start_sec", "end_sec", "duration_sec"))
                or voice.get("translated_text") != group.translated_text or voice.get("speaker") != group.speaker):
            raise client.DubbingError("render_segment_plan_mismatch")
        _process_record(voice["audio"], root)
        _process_record(voice["reference"], root)
        verify_artifact({k: voice["raw"][k] for k in ("path", "sha256", "bytes")}, root)
    premix = _process_record(report["premix"], root)
    _process_record(report["mix"], root)
    _process_record(report["output"], root)
    stem_mix = report["stem_mix"]
    if (stem_mix["background_mode"] not in {"include", "omit"}
            or stem_mix["background"] != (manifest.no_vocals.model_dump() if stem_mix["background_mode"] == "include" else None)
            or stem_mix["voices"] != [v["audio"] for v in voices]
            or premix["inputs"] != ([manifest.no_vocals.model_dump()] if stem_mix["background_mode"] == "include" else []) + [v["audio"] for v in voices]):
        raise client.DubbingError("stem_mix_accounting_mismatch")
    qa = await render.technical_qa(root, manifest, report["output"], report["mix"], voices)
    qa["checks"]["segment_count"] = len(voices) == len(plan.segments)
    qa["technical_pass"] = all(qa["checks"].values())
    return _delivery_result(destination, report, plan, validation, qa)


def _delivery_result(destination, report, plan, validation, qa) -> dict:
    """Join measured technical results with the separately supplied review."""
    voices = report["segments"]
    listening = listening_status(destination, report["output"]["sha256"], validation["plan_sha256"],
                                 [g.segment_id for g in plan.segments])
    reviewed = listening["status"] == "PASS"
    return {"status": "rendered" if qa["technical_pass"] else "technical_failed",
            "valid": qa["technical_pass"] and reviewed, "technical_qa": qa,
            "output": report["output"], "render_report": artifact(destination / "full/render_report.json"),
            "qa": artifact(destination / "full/final_qa.json"),
            "listening": listening, "listening_acceptance": "SUPPLIED_REVIEW" if reviewed else "UNRESOLVED",
            "service_acceptance": "UNQUALIFIED", "native_acceptance": "UNQUALIFIED",
            "review_segments": [{k: v[k] for k in ("segment_id", "start_sec", "end_sec", "translated_text", "flags", "timing", "listening")} for v in voices],
            "feature_acceptance": "UNQUALIFIED", "next_action": "Root qualification and listening review"}
