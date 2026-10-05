"""Content joins, same-speaker grouping and technical/listening delivery checks."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from .dubbing_client import audio_bytes, bounded_bytes, DubbingError, MAX_AUDIO_BYTES, MAX_JSON_BYTES, pcm_metadata
from .media_snapshot import checked_path
from .models.video_dubbing import ListeningReview, Project, Transcript, TranslationPlan, VadEvidence

def read_json(path: Path) -> dict:
    """Read a fenced, bounded JSON object without echoing untrusted inputs."""
    data = bounded_bytes(path, MAX_JSON_BYTES, "evidence_missing_or_too_large")
    try:
        value = json.loads(data)
    except (ValueError, UnicodeError):
        raise DubbingError("evidence_json_invalid") from None
    if not isinstance(value, dict):
        raise DubbingError("evidence_object_required")
    return value


def artifact(path: Path) -> dict:
    """Hash every byte of an actual local regular file under the existing fence."""
    path = checked_path(str(path))
    if not path.is_file() or path.stat().st_size <= 0:
        raise DubbingError("artifact_missing_or_empty")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "bytes": path.stat().st_size}


def verify_artifact(value, root: Path) -> Path:
    """Require a project-local file whose full current identity matches its join."""
    record = value.model_dump() if hasattr(value, "model_dump") else value
    path = checked_path(record["path"])
    if not path.is_relative_to(root) or artifact(path) != record:
        raise DubbingError("artifact_hash_or_locality_mismatch")
    return path


def _ordered(intervals, duration: float) -> None:
    previous = 0.0
    for interval in intervals:
        if interval.start_sec < previous or interval.end_sec > duration + 0.05:
            raise DubbingError("evidence_intervals_invalid")
        previous = interval.end_sec


def _analysis_windows(windows, duration: float) -> None:
    """Require complete source coverage while permitting reconciled overlaps."""
    if (windows[0].start_sec != 0 or abs(windows[-1].end_sec - duration) > 0.05
            or (duration <= 600 and len(windows) != 1)):
        raise DubbingError("source_analysis_coverage_incomplete")
    for index, window in enumerate(windows):
        if window.end_sec > duration + 0.05 or (duration > 600 and window.end_sec - window.start_sec > 600):
            raise DubbingError("source_analysis_window_invalid")
        if index and (window.start_sec < windows[index - 1].start_sec
                      or window.start_sec - windows[index - 1].end_sec > 0.05):
            raise DubbingError("source_analysis_coverage_incomplete")


def project(root: Path) -> Project:
    """Revalidate original and locally held source/stem/VAD bytes on every use."""
    root = checked_path(str(root))
    try:
        manifest = Project.model_validate(read_json(root / "project.json"))
    except ValueError:
        raise DubbingError("project_contract_invalid") from None
    if artifact(Path(manifest.source_movie))["sha256"] != manifest.source_sha256:
        raise DubbingError("original_source_changed")
    if manifest.source.sha256 != manifest.source_sha256:
        raise DubbingError("project_source_hash_mismatch")
    for value in (manifest.source, manifest.source_audio, manifest.vocals, manifest.no_vocals, manifest.vad):
        verify_artifact(value, root)
    for value in (manifest.source_audio, manifest.vocals, manifest.no_vocals):
        if value.bytes > MAX_AUDIO_BYTES:
            raise DubbingError("stem_too_large")
        metadata = pcm_metadata(audio_bytes(Path(value.path)))
        if abs(metadata["duration_sec"] - manifest.duration_sec) > 0.35:
            raise DubbingError("stem_duration_mismatch")
    return manifest


def slots(plan: TranslationPlan, duration: float) -> list[dict]:
    """Borrow at most 0.3 seconds and half each neighboring silent gap."""
    result = []
    for index, group in enumerate(plan.segments):
        previous = plan.segments[index - 1].end_sec if index else 0.0
        following = plan.segments[index + 1].start_sec if index + 1 < len(plan.segments) else duration
        start = max(0.0, group.start_sec - min(0.3, (group.start_sec - previous) / 2))
        end = min(duration, group.end_sec + min(0.3, (following - group.end_sec) / 2))
        if end <= start or (result and start < result[-1]["end_sec"] - 1e-6):
            raise DubbingError("render_slots_invalid")
        result.append({"segment_id": group.segment_id, "start_sec": start,
                       "end_sec": end, "duration_sec": end - start})
    return result


def _reference(group, transcript: Transcript, by_id: dict) -> None:
    reference = group.reference
    ids = reference.source_segment_ids
    if len(set(ids)) != len(ids) or any(key not in by_id for key in ids):
        raise DubbingError("reference_source_ids_invalid")
    items = [by_id[key] for key in ids]
    if any(item.speaker != group.speaker for item in items):
        raise DubbingError("reference_speaker_mismatch")
    for left, right in zip(items, items[1:]):
        if right.start_sec < left.end_sec or right.start_sec - left.end_sec > 1.2:
            raise DubbingError("reference_gap_or_order_invalid")
    if (reference.start_sec < items[0].start_sec - 0.15
            or reference.end_sec > items[-1].end_sec + 0.15):
        raise DubbingError("reference_outside_evidence")
    overlaps = [item for item in transcript.segments
                if item.start_sec < reference.end_sec and item.end_sec > reference.start_sec]
    if not overlaps or any(item.speaker != group.speaker for item in overlaps):
        raise DubbingError("reference_contains_other_or_no_speaker")


def _groups(plan: TranslationPlan, transcript: Transcript, duration: float) -> None:
    _ordered(plan.segments, duration)
    by_id = {item.segment_id: item for item in transcript.segments}
    if len(by_id) != len(transcript.segments):
        raise DubbingError("transcript_ids_duplicated")
    consumed = []
    for index, group in enumerate(plan.segments, 1):
        if group.segment_id != f"DUB_{index:04d}":
            raise DubbingError("dub_ids_not_contiguous")
        if any(key not in by_id for key in group.source_segment_ids):
            raise DubbingError("dub_source_ids_unknown")
        items = [by_id[key] for key in group.source_segment_ids]
        if any(item.speaker != group.speaker for item in items):
            raise DubbingError("dub_group_crosses_speakers")
        if len(items) > 1 and not group.merge_reason.strip():
            raise DubbingError("dub_merge_reason_missing")
        if (abs(group.start_sec - items[0].start_sec) > 0.05
                or abs(group.end_sec - items[-1].end_sec) > 0.05
                or " ".join(group.source_text.split()) != " ".join(" ".join(x.source_text for x in items).split())):
            raise DubbingError("dub_source_text_or_interval_mismatch")
        _reference(group, transcript, by_id)
        consumed.extend(group.source_segment_ids)
    if consumed != [item.segment_id for item in transcript.segments]:
        raise DubbingError("dub_groups_require_exact_ordered_coverage")


def estimated_seconds(text: str, language: str) -> float:
    """Provide a language-aware diagnostic, never a speech or meaning verdict."""
    language = language.lower().split("-")[0]
    if language in {"zh", "ja"}:
        count = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff]", text))
        if count:
            return max(0.25, count / 4.2)
    return max(0.25, len(re.findall(r"[\w']+", text)) / (3.2 if language == "ko" else 2.6))


def validate_plan(root: Path, plan_path: Path) -> tuple[Project, TranslationPlan, dict]:
    """Join exact source/VAD/transcript hashes, speakers, groups and timing slots.

    Args:
        root: Durable project directory holding all analysis and render inputs.
        plan_path: Agent-authored plan inside this project.

    Returns:
        Revalidated project and plan plus timing and evidence diagnostics.

    Raises:
        DubbingError: Any missing, changed, unresolved or contradictory evidence.
    """
    root, plan_path = checked_path(str(root)), checked_path(str(plan_path))
    if not plan_path.is_relative_to(root):
        raise DubbingError("plan_outside_project")
    manifest = project(root)
    transcript_path = root / "analysis/transcript.json"
    try:
        plan = TranslationPlan.model_validate(read_json(plan_path))
        transcript = Transcript.model_validate(read_json(transcript_path))
        vad = VadEvidence.model_validate(read_json(Path(manifest.vad.path)))
    except ValueError:
        raise DubbingError("plan_or_evidence_contract_invalid") from None
    for evidence in (plan, transcript, vad):
        if (evidence.source_movie != manifest.source_movie
                or evidence.source_sha256 != manifest.source_sha256):
            raise DubbingError("source_hash_join_mismatch")
    if (plan.vad_sha256 != manifest.vad.sha256 or transcript.vad_sha256 != manifest.vad.sha256
            or plan.transcript_sha256 != artifact(transcript_path)["sha256"]
            or vad.audio_sha256 != manifest.vocals.sha256
            or abs(vad.duration_sec - manifest.duration_sec) > 0.35):
        raise DubbingError("vad_or_transcript_hash_join_mismatch")
    if (plan.source_language != transcript.source_language or transcript.source_language == "auto"
            or (manifest.source_language != "auto" and plan.source_language != manifest.source_language)
            or plan.target_language != manifest.target_language or transcript.unresolved_issues):
        raise DubbingError("language_or_unresolved_transcript_mismatch")
    _ordered(vad.segments, manifest.duration_sec)
    _ordered(transcript.segments, manifest.duration_sec)
    _analysis_windows(transcript.evidence_windows, manifest.duration_sec)
    _groups(plan, transcript, manifest.duration_sec)
    actual_slots = slots(plan, manifest.duration_sec)
    diagnostics = []
    for group, slot in zip(plan.segments, actual_slots):
        overlap = sum(max(0, min(group.end_sec, x.end_sec) - max(group.start_sec, x.start_sec)) for x in vad.segments)
        ratio = overlap / (group.end_sec - group.start_sec)
        diagnostics.append({**slot, "vad_overlap_ratio": ratio,
                            "estimated_spoken_sec": estimated_seconds(group.translated_text, plan.target_language),
                            "flags": ["low_vad_overlap"] if ratio < 0.35 else []})
    return manifest, plan, {"valid": True, "plan_sha256": artifact(plan_path)["sha256"],
                            "segment_count": len(plan.segments), "slots": diagnostics}


def listening_status(root: Path, output_sha256: str, plan_sha256: str, ids: list[str]) -> dict:
    """Retain absent, failed or partial listening reviews as unresolved evidence."""
    path = root / "full/listening_review.json"
    checks = {key: {name: "UNRESOLVED" for name in
                   ("translation", "timing", "voice_reference", "natural_delivery", "mix")} for key in ids}
    if not path.exists():
        return {"status": "UNRESOLVED", "segments": checks, "issues": ["listening_review_missing"]}
    try:
        review = ListeningReview.model_validate(read_json(path))
    except ValueError:
        return {"status": "UNRESOLVED", "segments": checks, "issues": ["listening_review_invalid"]}
    if review.output_sha256 != output_sha256 or review.plan_sha256 != plan_sha256:
        return {"status": "UNRESOLVED", "segments": checks, "issues": ["listening_review_hash_mismatch"]}
    for key, required in checks.items():
        required.update({name: review.segment_checks.get(key, {}).get(name, "UNRESOLVED") for name in required})
    passed = (set(review.segment_checks) == set(ids) and not review.issues
              and all(value == "PASS" for group in checks.values() for value in group.values()))
    return {"status": "PASS" if passed else "UNRESOLVED", "segments": checks,
            "issues": review.issues, "reviewer": review.reviewer, "evidence": "supplied_review"}
