"""Captions-first exact-source transcription with durable partial/error/restart evidence."""

import asyncio
from contextlib import AsyncExitStack
import os
from pathlib import Path

from .media_snapshot import checked_path, copy_hash, snapshot
from .models.transcript import TranscriptFailure, TranscriptRequest, TranscriptResult
from .transcript_audio import extract_embedded, prepared_audio, retained_window, source_clock
from .transcript_captions import parse_captions, preferred_caption
from .transcript_formats import artifact_record, encoded, export_bytes, read_receipt, verify_artifacts, write_artifact
from .transcript_provider import ASRRefusal, execution_report, infer_audio, provider_plan, task_contract
from .transcript_timing import digest, merge_exact, project_answer, select_captions
from .vision_preparation import read_payload


def _initial(request) -> dict:
    return {"operation": "audio_transcribe", "status": "planned", "outcome": "planned", "source": None,
        "request_sha256": digest({"request": request.model_dump(mode="json"), "task_contract": task_contract(request)}), "selection": None, "captions": [],
        "segments": [], "untimed_text": [], "windows": [], "attempts": [], "exports": [], "artifacts": [],
        "provenance": {"speech_accuracy_verified": False, "word_alignment_verified": False,
            "speaker_identity_verified": False, "diarization_verified": False,
            "coordinate_basis": "absolute_source_seconds", "physical_speaker_identity": "unverified",
            "deduplication": [], "cross_window_physical_identity_merge": False,
            "requested_backend": request.backend, "fallback_backend": request.fallback_backend,
            "language": request.language, "glossary": request.glossary},
        "warnings": [], "execution": {}, "receipt": None}


def _journal(directory: Path, result: dict) -> None:
    """Persist dispatch/terminal progress atomically before another charged attempt is possible."""
    checked_path(str(directory))
    temporary = directory / ".run-state.pending"
    with temporary.open("xb") as stream:
        temporary.chmod(0o600)
        stream.write(encoded({"status": result["status"], "windows": result["windows"], "attempts": result["attempts"]}))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, directory / "run-state.json")


async def _caption_run(request, owned, directory, stack, result, chosen):
    records = []
    for item in request.caption_sources:
        records.append({"origin": item.origin, "format": item.format, "source_sha256": item.source_sha256,
            "selected": item == chosen, "status": "not_selected_unread", "language": item.language})
    result["captions"] = records
    selected = next(r for r in records if r["selected"])
    if chosen.embedded_track is not None:
        data = await extract_embedded(owned, chosen, directory)
        artifact = artifact_record(directory, directory / "embedded.srt", "embedded_caption_assertions")
        selected.update(track=chosen.embedded_track, extraction="explicit_track_file_only_ffmpeg")
    else:
        caption = await stack.enter_async_context(snapshot(chosen.file_path, chosen.expected_sha256))
        data = read_payload({"path": str(caption.path), "sha256": caption.sha256, "bytes": caption.size})
        artifact = write_artifact(directory, "selected-caption." + chosen.format, data, "provided_caption_assertions")
        selected.update(original={"path": str(caption.original), "sha256": caption.sha256, "bytes": caption.size})
    result["artifacts"].append(artifact)
    extent = result["source"]["presentation_end_seconds"]
    cues, provenance = parse_captions(data, chosen.format, extent)
    selected.update(status="admitted", artifact=artifact, provenance=provenance)
    cues, population = select_captions(cues, result["selection"]["start_seconds"], result["selection"]["end_seconds"])
    if request.require_word_alignment and any(not c.words for c in cues):
        raise ASRRefusal("Selected captions lack required supplied word alignment")
    result.update(status="complete", outcome="captions" if cues else "empty", segments=cues)
    result["provenance"].update(evidence="caption_source_assertions", population=population,
        speaker_status="source_assertion_if_supplied; unknown otherwise", word_status="source_assertion_if_supplied; absent otherwise")
    result["warnings"].append("Existing captions are source assertions, not verified speech or acoustic alignment")


async def _audio_run(request, owned, directory, result, holder):
    plan = None
    holder.append(None)
    async with prepared_audio(request) as (source, windows, verify):
        if (source["sha256"], source["bytes"], source["path"]) != (owned.sha256, owned.size, str(owned.original)):
            raise ValueError("Measured audio preparation differs from the admitted original")
        result["windows"] = [{k: v for k, v in w.items() if k != "parts"} | {"status": "planned"} for w in windows]
        for window, public in zip(windows, result["windows"]):
            artifact, pcm = retained_window(window, directory, write_artifact)
            public.update(artifact=artifact, pcm_observation=pcm)
            result["artifacts"].append(artifact)
        if request.dry_run:
            result["warnings"].append("Dry run: no speech inference submitted")
            return
        if any(not w["pcm_observation"]["all_samples_exact_zero"] for w in result["windows"]):
            if not request.authorize_submission:
                raise ASRRefusal("ASR submission requires authorize_submission=true")
            plan = provider_plan(request)
            holder[0] = plan
        await _infer_windows(request, windows, verify, owned, directory, result, plan)
    result["execution"] = execution_report(plan)


async def _infer_windows(request, windows, verify, owned, directory, result, plan):
    outcomes = []
    for window, public in zip(windows, result["windows"]):
        if public["pcm_observation"]["all_samples_exact_zero"]:
            public.update(status="complete", outcome="empty", inference="skipped_exact_zero_full_pcm")
            outcomes.append("empty")
            result["warnings"].append(f"Window{window['index']} has a complete exact-zero PCM population; no inference call")
            continue
        public["status"] = "dispatching"
        _journal(directory, result)
        try:
            await owned.verify()
            response = await infer_audio(request, window, plan, result["attempts"], verify)
            await owned.verify()
            _admit_answer(request, window, public, response, result)
            outcomes.append(public["outcome"])
            _journal(directory, result)
        except BaseException:
            public["status"] = "failed_or_interrupted"
            result["status"] = "partial" if any(w["status"] == "complete" for w in result["windows"]) else "failed"
            result["outcome"] = result["status"]
            raise
    result.update(status="complete", outcome="inferred" if result["segments"] or result["untimed_text"] else
                  "abstained" if "abstained" in outcomes else "empty")
    result["provenance"].update(evidence="model_inference_or_measured_zero_pcm", word_status="inferred_if_supplied; absent otherwise",
        speaker_status="model_inferred_label_if_supplied; unknown otherwise")


def _admit_answer(request, window, public, response, result):
    answer = response["answer"]
    public.update(status="complete", actual_backend=response["backend"], declared_model=response["model"],
                  model_identity_verified=False)
    public.update({key: response[key] for key in ("inference_contract_sha256", "runtime_qualification_status", "profile_sha256") if key in response})
    if answer is not None:
        cues = project_answer(answer, window, result["source"]["sha256"])
        if request.require_word_alignment and any(not c.words for c in cues):
            raise ASRRefusal("Backend answer lacks required inferred word intervals")
        merge_exact(result["segments"], cues, window["index"], result["provenance"]["deduplication"])
        public.update(outcome=answer.outcome, record_ids=[c.id for c in cues], abstentions=answer.abstentions)
    else:
        public.update(outcome="transcript" if response["untimed"] else "empty", record_ids=[],
                      timing_status="absent; Qwen service returned untimed text")
        for text in response["untimed"]:
            result["untimed_text"].append({"text": text, "window_index": window["index"],
                "audio_sha256": public["artifact"]["sha256"], "selected_window": public["audio"]["selected_window"],
                "start_seconds": None, "end_seconds": None, "speaker_id": None, "words": []})
    result["warnings"].append("Model words and speaker labels are inference; accuracy, alignment and identity are unverified")


def _observations(directory, result):
    """Refresh the mutable journal while preserving immutable export commitments."""
    _journal(directory, result)
    result["artifacts"] = [r for r in result["artifacts"] if r["path"] != "run-state.json"]
    known = {r["path"] for r in result["artifacts"]}
    for path in sorted(directory.rglob("*")):
        if path.is_file() and path.relative_to(directory).as_posix() not in known:
            result["artifacts"].append(artifact_record(directory, path))


async def _prepare_receipt(directory, request, result):
    if result["status"] in {"complete", "partial"}:
        for kind in request.export_formats:
            data, loss = export_bytes(kind, result["segments"], result["provenance"], result["untimed_text"])
            artifact = write_artifact(directory, "transcript." + ("txt" if kind == "text" else kind), data, "transcript_export")
            result["exports"].append({**artifact, **loss})
            result["artifacts"].append(artifact)
    await verify_artifacts(directory, result["artifacts"])
    try:
        await _rejoin_originals(result)
    except ValueError:
        result.update(status="failed", outcome="failed")
        result["warnings"].append("Original transcript source/caption changed before receipt promotion")
    _observations(directory, result)
    await verify_artifacts(directory, result["artifacts"])


async def _persist(directory, request, result, deadline):
    """Gate complete proof by caller time; join failed finalization for at most10 seconds."""
    try:
        async with asyncio.timeout_at(deadline):
            await _prepare_receipt(directory, request, result)
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError
    except (TimeoutError, asyncio.CancelledError) as error:
        result.update(status="failed", outcome="failed")
        result["warnings"].append("Transcript persistence cancelled" if isinstance(error, asyncio.CancelledError)
                                  else "Transcript caller deadline expired before receipt promotion")
        async with asyncio.timeout(10):
            _observations(directory, result)
            await verify_artifacts(directory, result["artifacts"])
    # No cancellable await remains between the committed result and its receipt.
    result["segments"] = [c.model_dump(mode="json") if hasattr(c, "model_dump") else c for c in result["segments"]]
    result_record = write_artifact(directory, "transcript-result.json", encoded(result), "complete_result_state")
    if artifact_record(directory, directory / result_record["path"], result_record["role"]) != result_record:
        raise ValueError("Retained result changed before receipt promotion")
    receipt = {"schema_version": 1, "operation": "audio_transcribe", "status": result["status"],
        "source": result["source"], "request_sha256": result["request_sha256"],
        "caption_originals": [c["original"] for c in result["captions"] if "original" in c],
        "artifacts": [*result["artifacts"], result_record]}
    record = write_artifact(directory, "receipt.json", encoded(receipt), "externally_bound_restart_receipt")
    result["receipt"] = {**record, "directory": str(directory)}
    return TranscriptResult.model_validate(result).model_dump(mode="json")


async def _joined_persist(directory, request, result, deadline):
    """Keep one finalizer owned through caller cancellation before propagating it."""
    task = asyncio.create_task(_persist(directory, request, result, deadline))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.cancel()
        while not task.done():
            try:
                await asyncio.shield(task)
            except (asyncio.CancelledError, Exception):
                continue
        if not task.cancelled():
            task.result()
        raise


async def _rejoin_originals(result):
    """Recheck original revisions at promotion, separately from earlier snapshot completion."""
    if result["status"] not in {"complete", "planned"}:
        return
    for original in [result["source"], *[c["original"] for c in result["captions"] if "original" in c]]:
        if await copy_hash(checked_path(original["path"])) != (original["sha256"], original["bytes"]):
            raise ValueError("Original transcript source/caption changed before receipt promotion")


async def transcribe(request: TranscriptRequest) -> dict:
    """Transcribe/plan one exact source, or reverify a separately hash-bound retained run."""
    request = TranscriptRequest.model_validate(request.model_dump(mode="json") if isinstance(request, TranscriptRequest) else request)
    if request.action == "readback":
        return await read_transcript(request.output_directory, request.expected_receipt_sha256,
            file_path=request.file_path, expected_source_sha256=request.expected_source_sha256)
    deadline = asyncio.get_running_loop().time() + request.limits.timeout_seconds
    directory = checked_path(request.output_directory)
    directory.mkdir(mode=0o700)
    result, holder, error = _initial(request), [], None
    _journal(directory, result)
    try:
        async with asyncio.timeout_at(deadline), AsyncExitStack() as stack:
            owned = await stack.enter_async_context(snapshot(request.file_path, request.expected_source_sha256))
            source, windows = await source_clock(owned, request, directory)
            result.update(source=source, selection={"start_seconds": windows[0]["start_seconds"],
                "end_seconds": windows[-1]["end_seconds"], "planned_windows": windows})
            chosen = preferred_caption(request)
            if chosen:
                await _caption_run(request, owned, directory, stack, result, chosen)
            else:
                await _audio_run(request, owned, directory, result, holder)
            await owned.verify()
    except BaseException as exc:
        error = exc
        if result["status"] not in {"partial", "failed"}:
            result.update(status="failed", outcome="failed")
        reason = str(exc) if isinstance(exc, ASRRefusal) else "Transcription source, timing, preparation or backend admission failed"
        if isinstance(exc, ImportError):
            reason = "Native caption/audio preparation requires separately installed FFmpeg/ffprobe; no runtime is installed automatically"
        result["warnings"].append(reason)
    result["execution"] = execution_report(holder[0] if holder else None)
    try:
        final = await _joined_persist(directory, request, result, deadline)
    except BaseException:
        _journal(directory, result | {"status": "failed"})
        raise
    if isinstance(error, asyncio.CancelledError):
        raise error
    if final["status"] == "failed" and error is None:
        error = ASRRefusal(final["warnings"][-1])
    if error:
        return TranscriptFailure(error=result["warnings"][-1], category="DEPENDENCY_MISSING" if isinstance(error, ImportError) else "SCHEMA_VALIDATION_FAILED",
            hint="Inspect retained evidence; use a fresh absent namespace after correcting the explicit request",
            retryable=False, metadata=final).model_dump(mode="json")
    return final


async def read_transcript(directory: str, expected_receipt_sha256: str, *, file_path=None, expected_source_sha256=None) -> dict:
    """Rejoin every original and retained file; a changed receipt cannot authenticate itself."""
    root, receipt, result = await read_receipt(directory, expected_receipt_sha256)
    source = receipt["source"]
    if not source:
        raise ValueError("Retained run has no admitted source identity")
    if file_path is not None and str(checked_path(file_path)) != source["path"]:
        raise ValueError("Readback caller source path differs from the retained exact source")
    if expected_source_sha256 is not None and expected_source_sha256 != source["sha256"]:
        raise ValueError("Readback caller source SHA differs from the retained exact source")
    for original in [source, *receipt["caption_originals"]]:
        if await copy_hash(checked_path(original["path"])) != (original["sha256"], original["bytes"]):
            raise ValueError("Retained transcript original source/caption changed")
    await verify_artifacts(root, receipt["artifacts"])
    if (await copy_hash(root / "receipt.json"))[0] != expected_receipt_sha256:
        raise ValueError("Retained receipt changed during source readback")
    result["receipt"] = {"path": "receipt.json", "sha256": expected_receipt_sha256,
        "bytes": (root / "receipt.json").stat().st_size, "role": "externally_bound_restart_receipt", "directory": str(root)}
    return TranscriptResult.model_validate(result).model_dump(mode="json")
