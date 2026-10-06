"""Source/config admission for independently implemented bounded memory lifecycle.

Protocol reference: QwenLM/Qwen-MM-Plugins@07736672525443c7f8a3f6405eed37d2236f023f,
Apache-2.0; no upstream code, prompts, runtime or assets are imported.
"""

import hashlib
import math

from ..media_local_io import _copy_hash
from ..models.av_events import CaptionEventsRequest
from ..models.video_memory_av import ArtifactReceipt, WINDOW_SECONDS
from ..models.video_memory_lifecycle import Checkpoint, PlannedSegment
from . import av_build, av_store


class LifecycleFailure(ValueError):
    """A classified failure with bounded diagnostics and retained attempted-call receipts."""

    def __init__(self, message: str, failure: str, **report):
        super().__init__(message)
        self.report = {"failure": failure, **report}


def classify(error: Exception) -> str:
    """Classify structured endpoint errors without exposing provider-controlled messages."""
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(getattr(error, "response", None), "status_code", None)
    if status == 429:
        return "rate"
    if status in {401, 403, 404} or isinstance(error, PermissionError):
        return "config"
    if isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower():
        return "timeout"
    report = getattr(error, "report", {})
    for call in report.get("costs", {}).get("route_calls", []):
        detail = call.get("error") or {}
        if not isinstance(detail, dict):
            continue
        category = detail.get("category")
        if category in {"API_QUOTA_EXCEEDED", "S2_RATE_LIMITED"}:
            return "rate"
        if category in {"API_PERMISSION_DENIED", "PERMISSION_DENIED", "DEPENDENCY_MISSING"}:
            return "config"
        label = f"{detail.get('hint') or ''} {detail.get('error') or ''}".lower()
        if category == "NETWORK_ERROR" and any(marker in label for marker in
                                                ("timed out", "timeouterror", "readtimeout", "connecttimeout")):
            return "timeout"
    return "reject"


def config_digest(config) -> str:
    """Commit to the complete typed semantic profile, including any optional AV route."""
    return hashlib.sha256(av_store.canonical(config.model_dump(mode="json"))).hexdigest()


def commit(root, state, retained) -> dict:
    """Guard canonical storage children against symlink escapes before using the shared publisher."""
    artifacts = root / "artifacts"
    if artifacts.is_symlink() or av_store.local_path(str(root)) != root:
        raise PermissionError("Canonical memory storage path changed or redirects through a symlink")
    if any((artifacts / f"{digest}.json").is_symlink() for digest in retained):
        raise PermissionError("Retained artifact address is a symlink")
    return av_store.commit(root, state, retained)


def verify_source(segment) -> None:
    """Hash bounded regular bytes through the existing secured, deadline-bound local reader."""
    try:
        path = av_store.local_path(segment.file_path)
        digest, size = _copy_hash(path, max_bytes=segment.expected_source_bytes)
    except (OSError, ValueError) as error:
        raise LifecycleFailure("Source commitment is unavailable or changed; reuse is forbidden",
                               classify(error), stale=True, segment_id=segment.segment_id,
                               error_type=type(error).__name__) from error
    if digest != segment.expected_source_sha256 or size != segment.expected_source_bytes:
        raise LifecycleFailure("Source commitment changed; stale reuse is forbidden", "reject",
                               stale=True, segment_id=segment.segment_id)


def plan(segments, existing=()) -> list[PlannedSegment]:
    """Freeze end-to-end source order, bounded count and caller-declared clock positions."""
    result = list(existing)
    ids = {s.source.segment_id for s in result}
    digests = {s.source.expected_source_sha256 for s in result}
    offset = result[-1].offset_seconds + result[-1].source.duration_seconds if result else 0.0
    for source in segments:
        if source.segment_id in ids or source.expected_source_sha256 in digests:
            raise ValueError("A source digest or segment ID is already planned")
        windows = av_build.window_count(source.duration_seconds)
        if any(c.window >= windows for c in source.clips):
            raise ValueError("Retained clip window lies outside the declared source clock")
        result.append(PlannedSegment(source=source, offset_seconds=offset, planned_windows=windows))
        ids.add(source.segment_id)
        digests.add(source.expected_source_sha256)
        offset += source.duration_seconds
    if len(result) > 16 or sum(s.planned_windows for s in result) > 512:
        raise ValueError("Lifecycle plan exceeds 16 sources or 512 windows")
    return result


def load(request, *, verify: bool = True):
    """Load the canonical revision and reject stale configuration, revision or source bytes."""
    root = av_store.local_path(request.memory_dir)
    state = av_store.load(root, request.expected_source_sha256)
    if state is None:
        raise ValueError("No canonical AV memory exists; build first")
    entries = [entry["lifecycle"] for entry in state.history if "lifecycle" in entry]
    if not entries:
        raise ValueError("Memory has no lifecycle checkpoint")
    checkpoint = Checkpoint.model_validate(entries[-1])
    if checkpoint.config_sha256 != config_digest(request.config):
        raise LifecycleFailure("Semantic configuration changed; stale reuse is forbidden", "config", stale=True)
    expected = getattr(request, "expected_revision", state.revision)
    if expected != state.revision:
        raise LifecycleFailure("Canonical memory revision conflict", "reject", current_revision=state.revision)
    if verify:
        for segment in checkpoint.segments:
            verify_source(segment.source)
    return root, state, checkpoint


def supplied(segment) -> tuple[list, dict]:
    """Admit exact existing artifact schemas and their full parent presentation clocks."""
    admitted, retained = [], {}
    source = {"sha256": segment.expected_source_sha256, "bytes": segment.expected_source_bytes}
    for ref in segment.artifacts:
        data, value = av_build.read_artifact(ref)
        duration, result = av_build.admit(ref.kind, value, source)
        if not math.isclose(duration, segment.duration_seconds, abs_tol=av_build.CLOCK_TOLERANCE_SECONDS):
            raise ValueError("Artifact and caller-declared source clocks disagree")
        role = "utterances" if ref.kind == "transcript" else ref.role
        receipt = ArtifactReceipt(kind=ref.kind, role=role, operation=result.operation,
                                  sha256=ref.sha256, bytes=len(data), retained=f"artifacts/{ref.sha256}.json",
                                  origin="supplied")
        admitted.append((receipt, result))
        retained[ref.sha256] = data
        if sum(map(len, retained.values())) > av_build.MAX_TOTAL_BYTES:
            raise ValueError("Supplied artifact payload exceeds 32 MiB")
    return admitted, retained


def admit_route(segment, responses) -> tuple[list, dict]:
    """Admit bounded native-route results without weakening the existing source contract."""
    admitted, retained = [], {}
    source = {"sha256": segment.expected_source_sha256, "bytes": segment.expected_source_bytes}
    for role, value in responses:
        data = av_store.canonical(value)
        if len(data) > av_build.MAX_ARTIFACT_BYTES:
            raise ValueError("AV route artifact exceeds 8 MiB")
        duration, result = av_build.admit("av_events", value, source)
        if not math.isclose(duration, segment.duration_seconds, abs_tol=av_build.CLOCK_TOLERANCE_SECONDS):
            raise ValueError("AV route and declared source clocks disagree")
        digest = hashlib.sha256(data).hexdigest()
        receipt = ArtifactReceipt(kind="av_events", role=role, operation=result.operation, sha256=digest,
                                  bytes=len(data), retained=f"artifacts/{digest}.json", origin="route")
        admitted.append((receipt, result))
        retained[digest] = data
    return admitted, retained


def calls_for_window(route, window: int, duration: float) -> list[dict]:
    """Use the existing bounded AV client for exactly one canonical window per role."""
    return [{"operation": "media_caption_events", "role": role,
             "start_seconds": window * WINDOW_SECONDS,
             "end_seconds": min((window + 1) * WINDOW_SECONDS, duration),
             "window_seconds": WINDOW_SECONDS} for role in route.roles]


async def run_route(route, file_path: str, sha256: str, calls: list[dict]) -> list:
    """Use the existing native client while retaining structured failure categories its old wrapper drops."""
    responses = []
    for call in calls:
        extra = {"instruction": av_build.ENVIRONMENT_INSTRUCTION} if call["role"] == "environment" else {}
        request = CaptionEventsRequest(
            file_path=file_path, expected_source_sha256=sha256, start_seconds=call["start_seconds"],
            end_seconds=call["end_seconds"], window_seconds=WINDOW_SECONDS, dry_run=False,
            authorize_submission=True, thinking_level=route.thinking_level, **extra)
        result = await av_build.caption_events(request)
        responses.append((call["role"], result))
        if result.get("status") != "complete":
            receipts = av_build.route_costs(responses)
            for receipt, (_, value) in zip(receipts, responses):
                receipt["error"] = {key: value.get(key) for key in ("error", "category", "hint", "retryable")}
            error = av_build.ProviderFailure("Native AV client did not complete", {"costs": {"route_calls": receipts}})
            raise LifecycleFailure("Native AV client did not complete", classify(error), **error.report)
    return responses
