"""Project-owned timing repair from accepted narration sample events, without inference."""

from fractions import Fraction
import hashlib
import math
from pathlib import Path

from .evidence import atomic_write
from .models.timing import TimingManifest, TimingRequest, TimingResult
from .narration_pcm import atomic_bytes, qualify, snapshot, wav
from .narration_timing import provider_words
from .plan_artifacts import bind_storyboard, require_binding
from .planning import plan_transaction, require_approved, save_plan
from .planning_sources import canonical, digest, project_directory
from .render_storyboard import _board_controls, _frames, _timeline
from .render_storyboard_sources import confined_path, project_object

MANIFEST = ".timing/manifest.json"
LIMIT = 1024 * 1024


def previous(project: Path) -> dict | None:
    """Read only a bounded typed prior manifest; source freshness is checked separately."""
    if not confined_path(project, MANIFEST).exists():
        return None
    value, _ = project_object(project, MANIFEST)
    return TimingManifest.model_validate(value).model_dump()


def current_inputs(project: Path, state: dict) -> tuple[dict, dict, bytes, dict]:
    """Reuse actual plan/script/narration admission and measured complete PCM."""
    require_approved(project, state)
    script = require_binding(project, state, "script")
    narration = require_binding(project, state, "narration")
    if narration["status"] != "accepted" or narration["action"] == "preview":
        raise ValueError("Timing requires accepted full narration, not a preview")
    expected = [{"scene_id": s["scene_id"], "text": s["voiceover"]} for s in script["scenes"]]
    if narration["script_transcript"] != expected or narration["transcript"] != "".join(s["voiceover"] for s in script["scenes"]):
        raise ValueError("Narration transcript differs from the bound script")
    pcm, measured = qualify(snapshot(confined_path(project, narration["artifact"]["path"])))
    if any(measured[k] != narration["artifact"][k] for k in ("frames", "sample_rate", "channels", "sample_width")):
        raise ValueError("Narration measurement differs from its accepted receipt")
    if measured["duration_seconds"] > 1800:
        raise ValueError("Timing exceeds the production1800-second ceiling")
    return script, narration, pcm, measured


def validated_words(narration: dict, measured: dict) -> list[dict] | None:
    """Revalidate existing provider/synthetic sample events; never invent missing alignment."""
    values = narration.get("words")
    if values is None:
        return None
    if not isinstance(values, list) or not 1 <= len(values) <= 4096:
        raise ValueError("Timing requires1..4096 source words, or explicit missing alignment")
    rate, frames, text = measured["sample_rate"], measured["frames"], narration["transcript"]
    events = []
    for word in values:
        if word.get("alignment") not in ("provider_declared", "synthetic_event"):
            raise ValueError("Unsupported source word timestamp method")
        if any(type(word[k]) is not int for k in ("start_frame", "end_frame", "text_begin", "text_end")):
            raise ValueError("Source word offsets must be integer sample/text frames")
        events.append({"word": word["word"], "word_begin": word["text_begin"], "word_end": word["text_end"],
                       "time_begin": word["start_frame"] * 1000 / rate, "time_end": word["end_frame"] * 1000 / rate})
    checked = provider_words([{"text": text, "text_begin": 0, "text_end": len(text), "time_begin": 0,
                              "time_end": frames * 1000 / rate, "timestamped_words": events}], text, frames, rate)
    if any((a["start_frame"], a["end_frame"]) != (b["start_frame"], b["end_frame"]) for a, b in zip(checked, values, strict=True)):
        raise ValueError("Source timestamps cannot be represented in their original sample clock")
    return values


def scene_clock(script: dict, narration: dict, pcm: bytes, measured: dict) -> list[dict]:
    """Partition only existing sentence spans; use cumulative30fps quantization without drift."""
    words, rate = validated_words(narration, measured), measured["sample_rate"]
    rows, result, end, text_offset, video_end = narration["sentences"], [], 0, 0, 0
    if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
        raise ValueError("Narration requires1..4096 accepted sentence intervals")
    if len(script["scenes"]) > 64:
        raise ValueError("Production timing supports at most64 scenes")
    for scene in script["scenes"]:
        selected = [r for r in rows if str(r["scene_id"]) == str(scene["scene_id"])]
        if narration["action"] == "custom" and len(script["scenes"]) == 1:
            selected = rows
        if not selected:
            raise ValueError("Missing scene sample timing; custom multi-scene audio cannot be partitioned")
        first, last = selected[0]["start_frame"], selected[-1]["end_frame"]
        if type(first) is not int or type(last) is not int or first != end or not first < last <= measured["frames"]:
            raise ValueError("Scene sample intervals must partition the measured audio monotonically")
        if "".join(r["text"] for r in selected) != scene["voiceover"]:
            raise ValueError("Scene sample population differs from its exact narration")
        cursor = first
        for row in selected:
            if (row.get("status") != "accepted" or type(row["start_frame"]) is not int or type(row["end_frame"]) is not int
                or row["start_frame"] != cursor or not cursor < row["end_frame"] <= last):
                raise ValueError("Sentence intervals must be accepted, contiguous and monotonic")
            cursor = row["end_frame"]
        finish = _frames(Fraction(last, rate))
        if finish <= video_end:
            raise ValueError("Each scene requires at least one production video frame")
        local = []
        for word in words or []:
            if text_offset <= word["text_begin"] < word["text_end"] <= text_offset + len(scene["voiceover"]):
                if not first <= word["start_frame"] < word["end_frame"] <= last:
                    raise ValueError("Word sample interval crosses its narration scene")
                local.append({**{k: word[k] for k in ("word", "alignment")},
                              "text_begin": word["text_begin"] - text_offset, "text_end": word["text_end"] - text_offset,
                              "start_sample": word["start_frame"] - first, "end_sample": word["end_frame"] - first})
        clip = wav(pcm[first * 2:last * 2], rate)
        key = digest({"text": scene["voiceover"], "audio_sha256": hashlib.sha256(clip).hexdigest(), "words": local,
                      "video_frames": finish - video_end})
        result.append({"scene_id": str(scene["scene_id"]), "source_sha256": key, "start_sample": first,
                       "end_sample": last, "from_video_frame": video_end, "video_frames": finish - video_end,
                       "words": local, "word_alignment": "absent" if words is None else narration["word_alignment"],
                       "audio_path": f".timing/audio/{key}.wav"})
        end, video_end, text_offset = last, finish, text_offset + len(scene["voiceover"])
    if (end != measured["frames"] or text_offset != len(narration["transcript"])
        or (words is not None and sum(len(s["words"]) for s in result) != len(words))
        or (narration["action"] != "custom" and any(str(r["scene_id"]) not in {s["scene_id"] for s in result} for r in rows))):
        raise ValueError("Scene population omits required narration samples or text")
    return result


def differences(old: dict | None, scenes: list[dict]) -> tuple[list[str], list[str], list[str]]:
    """Distinguish local regeneration from unchanged sources with shifted global offsets."""
    prior = {s["scene_id"]: s for s in old["scenes"]} if old else {}
    changed, reused, shifted = [], [], []
    for row in scenes:
        before = prior.get(row["scene_id"])
        (reused if before and before["source_sha256"] == row["source_sha256"] else changed).append(row["scene_id"])
        if before and before["start_sample"] != row["start_sample"]:
            shifted.append(row["scene_id"])
    return changed, reused, shifted


def timing_props(row: dict, rate: int) -> dict:
    """Build the exact sample-derived props used by both publication and readback."""
    animations = [{"id": f"word:{w['text_begin']}:{w['text_end']}",
                   "from": min(row["video_frames"] - 1, w["start_sample"] * 30 // rate),
                   "to": min(row["video_frames"], _frames(Fraction(w["end_sample"], rate)))} for w in row["words"]]
    return {"sample_rate": rate, "timestamp_method": row["word_alignment"],
            "words": row["words"], "animations": animations}


def check_current(project: Path, state: dict, manifest: dict) -> None:
    """Fail closed on every source, timing/audio clip and storyboard revision before render."""
    script, narration, pcm, measured = current_inputs(project, state)
    scenes = scene_clock(script, narration, pcm, measured)
    expected = {"plan_revision": state["revision"], "plan_sha256": state["plan_sha256"],
                "source_commitment_sha256": state["source_commitment_sha256"],
                "script_sha256": state["bindings"]["script"]["sha256"],
                "narration_sha256": state["bindings"]["narration"]["sha256"],
                "audio": narration["artifact"], "scenes": scenes, "sample_rate": measured["sample_rate"],
                "total_samples": measured["frames"], "timestamp_method": narration["word_alignment"]}
    if any(manifest[k] != value for k, value in expected.items()):
        raise ValueError("Timing manifest is stale for its current narration/source revision")
    board, pin = project_object(project, "storyboard/storyboard.json")
    if pin != manifest["storyboard"]:
        raise ValueError("Timing storyboard bytes changed")
    require_binding(project, state, "storyboard")
    for row in scenes:
        clip = wav(pcm[row["start_sample"] * 2:row["end_sample"] * 2], measured["sample_rate"])
        if snapshot(confined_path(project, row["audio_path"])) != clip:
            raise ValueError("Timed scene audio changed")
    _board_controls(board)
    timeline, count = _timeline(board, project)
    for clock, row in zip(timeline, scenes, strict=True):
        if (clock["id"] != row["scene_id"] or clock["from"] != row["from_video_frame"]
            or clock["durationInFrames"] != row["video_frames"] or clock["audio_src"] != row["audio_path"]
            or clock.get("props", {}).get("timing") != timing_props(row, measured["sample_rate"])):
            raise ValueError("Storyboard timing/audio props differ from source sample events")
    if count != manifest["video_frames"] or abs(count / 30 - measured["duration_seconds"]) > 1 / 30:
        raise ValueError("Storyboard duration differs from measured narration")


def require_current_timing(project: Path, state: dict) -> dict | None:
    """Root pre-render hook: legacy projects pass; a recorded timing manifest must be current."""
    manifest = previous(project)
    if manifest is not None:
        check_current(project, state, manifest)
    return manifest


def verify_render_timing(project: Path, state: dict, request: dict, qualification: dict) -> dict:
    """Root post-qualification hook uses the existing native result, never a fabricated probe."""
    manifest = require_current_timing(project, state)
    if manifest is None:
        return {"timing": "not_managed"}
    props = request["render_contract"]["input_props"]
    board_pin = request["renderer"]["project_sha256"].get("storyboard/storyboard.json")
    if props["fps"] != 30 or props["durationInFrames"] != manifest["video_frames"] or board_pin != manifest["storyboard"]["sha256"]:
        raise ValueError("Qualified render request differs from the current timing storyboard")
    duration = qualification["media"]["duration_seconds"]
    if type(duration) not in (int, float) or not math.isfinite(duration) or abs(duration - manifest["total_samples"] / manifest["sample_rate"]) > 1 / 30:
        raise ValueError("Qualified rendered duration differs from narration by more than1/30second")
    return {"timing": "verified_existing_qualification", "duration_seconds": duration, "tolerance_seconds": 1 / 30}


def prepare_board(project: Path, state: dict, old: dict | None, script: dict, pcm: bytes, measured: dict, scenes: list[dict]) -> str:
    """Preserve authored visuals while validating bounded scene/audio changes before publication."""
    board, pin = project_object(project, "storyboard/storyboard.json")
    if old is None:
        require_binding(project, state, "storyboard")
    elif pin != old["storyboard"] and state["bindings"].get("storyboard", {}).get("sha256") != pin["sha256"]:
        raise ValueError("Storyboard changed outside timing repair; bind it explicitly first")
    _board_controls(board)
    if [str(s["id"]) for s in board["scenes"]] != [s["scene_id"] for s in scenes]:
        raise ValueError("Storyboard scene IDs/order differ from current narration")
    target = confined_path(project, ".timing/audio")
    target.mkdir(parents=True, mode=0o700, exist_ok=True)
    ticks = 0
    for entry, parent, timing in zip(board["scenes"], script["scenes"], scenes, strict=True):
        clip = wav(pcm[timing["start_sample"] * 2:timing["end_sample"] * 2], measured["sample_rate"])
        path = confined_path(project, timing["audio_path"])
        if path.exists():
            if snapshot(path) != clip:
                raise ValueError("Existing timed clip differs from admitted source samples")
        else:
            atomic_bytes(path, clip)
        duration_ticks = timing["video_frames"] * 1000000000 // 30
        ticks += duration_ticks
        entry.update(title=parent["title"], audio_file=timing["audio_path"],
                     audio_duration_seconds=duration_ticks / 1000000000, visual_padding_seconds=0, scene_buffer_seconds=0)
        entry["props"] = {**entry.get("props", {}), "timing": timing_props(timing, measured["sample_rate"])}
    board["total_duration_seconds"] = ticks / 1000000000
    if board["total_duration_seconds"] > state["plan"]["duration_budget_seconds"] or any(
        entry["audio_duration_seconds"] > planned["duration_seconds"]
        for entry, planned in zip(board["scenes"], state["plan"]["scenes"], strict=True)
    ):
        raise ValueError("Quantized storyboard exceeds the approved duration budget")
    _timeline(board, project)
    encoded = canonical(board)
    if len(encoded.encode()) > LIMIT:
        raise ValueError("Timed storyboard exceeds1MiB")
    return encoded


def publish(project: Path, state: dict, old: dict | None, script: dict, narration: dict, pcm: bytes, measured: dict, scenes: list[dict]) -> dict:
    """Publish real storyboard binding and a durable CAS revision; interrupted stages fail closed."""
    encoded = prepare_board(project, state, old, script, pcm, measured, scenes)
    fresh_script, fresh_narration, _, _ = current_inputs(project, state)
    if fresh_script != script or fresh_narration != narration:
        raise ValueError("Narration sources changed during timing repair")
    atomic_write(confined_path(project, "storyboard/storyboard.json"), encoded)
    bind_storyboard(project, state, project / "storyboard/storyboard.json")
    _, board_pin = project_object(project, "storyboard/storyboard.json")
    manifest = TimingManifest(revision=(old["revision"] if old else 0) + 1,
        plan_revision=state["revision"], plan_sha256=state["plan_sha256"],
        source_commitment_sha256=state["source_commitment_sha256"],
        script_sha256=state["bindings"]["script"]["sha256"], narration_sha256=state["bindings"]["narration"]["sha256"],
        audio=narration["artifact"], sample_rate=measured["sample_rate"], total_samples=measured["frames"],
        video_frames=scenes[-1]["from_video_frame"] + scenes[-1]["video_frames"],
        timestamp_method=narration["word_alignment"], scenes=scenes, storyboard=board_pin).model_dump()
    encoded = canonical(manifest)
    if len(encoded.encode()) > LIMIT:
        raise ValueError("Timing manifest exceeds1MiB")
    atomic_write(confined_path(project, MANIFEST), encoded)
    check_current(project, state, manifest)
    return manifest


def manage_timing(project_id: str, request: TimingRequest) -> dict:
    """Inspect/repair within the existing project plan critical section and explicit CAS."""
    project = project_directory(project_id)
    with plan_transaction(project) as (connection, state):
        if state is None:
            raise ValueError("Timing requires an approved managed plan")
        old = previous(project)
        revision = old["revision"] if old else 0
        if request.action == "repair" and request.expected_revision != revision:
            raise ValueError("Timing revision conflict")
        issues, scenes = [], []
        try:
            script, narration, pcm, measured = current_inputs(project, state)
            scenes = scene_clock(script, narration, pcm, measured)
        except (OSError, ValueError, KeyError) as error:
            issues.append(str(error))
        changed, reused, shifted = differences(old, scenes)
        current = False
        if old and not issues:
            try:
                check_current(project, state, old)
                current = True
            except (OSError, ValueError, KeyError) as error:
                issues.append(str(error))
        status = "current" if current else "stale"
        manifest = old
        if request.action == "repair":
            if not scenes:
                state["bindings"].pop("storyboard", None)
                save_plan(connection, state)
                missing = any("Missing scene sample timing" in error for error in issues)
                return TimingResult(project_id=project_id, status="missing_scene_timing" if missing else "stale", revision=revision,
                                    current=False, affected_scenes=[s["scene_id"] for s in old["scenes"]] if old else [],
                                    issues=issues, manifest=old).model_dump()
            manifest = publish(project, state, old, script, narration, pcm, measured, scenes)
            save_plan(connection, state)
            revision, current, status, issues = manifest["revision"], True, "repaired", []
        if scenes and any(s["word_alignment"] == "absent" for s in scenes) and current:
            status = "missing_alignment"
        return TimingResult(project_id=project_id, status=status, revision=revision, current=current,
                            affected_scenes=changed if scenes else [s["scene_id"] for s in old["scenes"]] if old else [],
                            reused_scenes=reused, shifted_scenes=shifted, issues=issues, manifest=manifest).model_dump()
