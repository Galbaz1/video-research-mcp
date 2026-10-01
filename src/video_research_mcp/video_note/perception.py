"""Optional admitted AV inference, retaining populations and exact supplied fallback."""

from ..models.media_perception import AVSourceEvidence
from ..models.video_note import VideoNoteStep
from ..redaction import redact_text
from .io import canonical


def supplied_plan(request):
    """Keep caller instructions unchanged and labeled as unreviewed proposals."""
    return [{**step.model_dump(mode="json"), "origin": "caller_proposal", "event": None}
            for step in request.steps]


def _population(value):
    windows = [{"index": window.get("index"), "start_seconds": window.get("start_seconds"),
                "end_seconds": window.get("end_seconds"), "status": window.get("status", "unknown")}
               for window in value.get("windows", [])]
    abstentions = [{"window_index": item.get("window_index"),
                    "reason": "Model abstention retained; raw text withheld"}
                   for item in value.get("abstentions", [])]
    execution = value.get("execution", {})
    counts = {key: execution.get(key) for key in (
        "prepared_windows", "completed_windows", "image_transmissions", "audio_transmissions",
        "prepared_payload_bytes", "serialized_transmission_bytes", "elapsed_seconds")}
    counts.update(failed_windows=sum(window["status"] == "failed" for window in windows),
                  unobserved_windows=sum(window["status"] != "complete" for window in windows),
                  abstentions=len(abstentions), attempts=len(execution.get("attempts", [])))
    return {"windows": windows, "abstentions": abstentions, "counts": counts}


def _inferred(value, source):
    """Admit only the existing exact-source timeline; never repair its coordinates."""
    if value.get("source", {}).get("sha256") != source["sha256"]:
        raise ValueError("Perception source commitment differs from tutorial source")
    events = [AVSourceEvidence.model_validate(event) for event in value.get("timeline", [])]
    if not 1 <= len(events) <= 16:
        raise ValueError("Inferred tutorial requires 1..16 events; full population retained")
    previous, result = 0, []
    for event in events:
        if event.start_seconds < previous or event.end_seconds <= event.start_seconds:
            raise ValueError("Inferred steps overlap or lack a positive source interval")
        previous = event.end_seconds
        step = VideoNoteStep(title=f"Inferred {event.modality} step {len(result) + 1}",
            instruction=redact_text(event.description), start_seconds=event.start_seconds,
            end_seconds=event.end_seconds)
        result.append({**step.model_dump(mode="json"), "origin": "model_inference",
                       "event": {"modality": event.modality, "window_index": event.window_index,
                                 "frame_indices": event.frame_indices}})
    return result


async def plan_steps(request, source):
    """Use optional explicit inference or preserve supplied text on any model failure."""
    fallback = supplied_plan(request)
    report = {"status": "not_requested", "windows": [], "abstentions": [], "counts": {},
              "timeline": [], "source_extent_seconds": None, "factual_correctness_verified": False}
    if request.perception is None:
        return fallback, report, []
    from ..media_perception import perceive_media
    try:
        value = await perceive_media(request.perception)
        if len(canonical(value)) > 256 * 1024:
            raise ValueError("Perception receipt exceeds tutorial metadata bound")
        report.update(_population(value))
        report["status"] = "complete" if value.get("status") == "complete" else "failed"
        report["timeline"] = []
        for event in value.get("timeline", []):
            admitted = AVSourceEvidence.model_validate(event).model_dump(mode="json")
            admitted["description"] = redact_text(admitted["description"])
            report["timeline"].append(admitted)
        observed = value.get("source") or {}
        extent = observed.get("presentation_end_seconds") or observed.get("duration_seconds")
        if type(extent) in (int, float) and 0 < extent <= 86400:
            report["source_extent_seconds"] = extent
        if report["status"] != "complete":
            raise ValueError("Perception incomplete; keep supplied step population")
        return _inferred(value, source), report, []
    except Exception:
        if report["status"] == "not_requested":
            report["status"] = "failed"
        report["fallback"] = "supplied_steps"
        return fallback, report, ["AV inference unavailable or unsuitable; supplied tutorial text retained. "
                                  "Failed, unobserved and abstained windows remain in the receipt."]
