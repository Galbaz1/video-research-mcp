"""Offline licensed local narration/music/SFX mix: rights, snapshots, FFmpeg recipe, cache and WAV QA.

Only caller-supplied local files are mixed. No music/SFX generation, provider, download or
existing optional sound wrapper is invoked. Measured QA is signal-level only; listening quality
remains UNQUALIFIED until separately qualified.
"""

import array
from datetime import datetime, timezone
import hashlib
import math
from pathlib import Path
import tempfile
import wave

from .evidence import atomic_write
from .file_io import open_regular
from .materials import discard_published, pinned_object, publish, snapshot
from .media_process import run_media_process
from .models.audio_mix import AudioCue, AudioMixRequest, AudioRights
from .planning import plan_transaction
from .planning_sources import canonical, project_directory
from .render_storyboard_sources import confined_path, file_pin, project_object
from .render_validation import codec_executables

TIMEOUT = 120
MAX_OUTPUT_BYTES = 64 * 1024 * 1024
ROLES = ("narration", "music", "sfx")


def rights_receipt(project: Path, cue: AudioCue, principal: str, commercial: bool) -> dict:
    """Refuse absent, stale, foreign, non-permissive or non-commercial rights for these exact bytes."""
    rights = AudioRights.model_validate(pinned_object(project, cue.rights))
    now = datetime.now(timezone.utc)
    if (rights.source_sha256 != cue.source.sha256 or rights.principal != principal or not rights.use_allowed
            or not rights.retrieved_at <= now < rights.valid_until):
        raise ValueError(f"{cue.cue_id}: audio rights are absent, stale or do not authorize these bytes/caller")
    if commercial and not rights.commercial_use:
        raise ValueError(f"{cue.cue_id}: rights do not allow commercial use")
    return {"cue_id": cue.cue_id, "role": cue.role, "source_path": cue.source.path, "source_sha256": cue.source.sha256,
            "rights_path": cue.rights.path, "rights_sha256": cue.rights.sha256,
            "license": rights.license, "license_url": rights.license_url, "credit": rights.credit,
            "commercial_use": rights.commercial_use, "authority_basis": "caller_declared_unverified"}


def storyboard_windows(project: Path, request: AudioMixRequest) -> dict:
    """Scene windows from the pinned storyboard's sequential audio_duration_seconds; cues must fit them."""
    body = pinned_object(project, request.storyboard)
    windows, start = {}, 0.0
    for scene in body.get("scenes") or []:
        duration = float(scene["audio_duration_seconds"])
        scene_id = str(scene["id"])
        if not math.isfinite(duration) or duration <= 0 or scene_id in windows:
            raise ValueError("Storyboard scene durations must be positive and scene IDs unique")
        windows[scene_id] = (start, start + duration)
        start += duration
    if not windows or abs(start - float(body["total_duration_seconds"])) > 0.001 or abs(start - request.total_seconds) > 0.001:
        raise ValueError("Storyboard scenes/total do not match the mix total_seconds")
    for cue in request.cues:
        end = cue.start_seconds + cue.duration_seconds
        if cue.scene_id is None:
            continue
        if cue.scene_id not in windows:
            raise ValueError(f"{cue.cue_id}: scene {cue.scene_id} is absent from the storyboard")
        low, high = windows[cue.scene_id]
        if cue.start_seconds < low - 0.001 or end > high + 0.001 or (cue.role == "narration" and abs(cue.start_seconds - low) > 0.001):
            raise ValueError(f"{cue.cue_id}: cue interval does not match storyboard scene {cue.scene_id}")
    return {"path": request.storyboard.path, "sha256": request.storyboard.sha256,
            "method": "sequential storyboard audio_duration_seconds; narration starts at its scene start; music spans caller interval",
            "scenes": {k: list(v) for k, v in windows.items()}}


def _sources_current(project: Path, request: AudioMixRequest) -> None:
    for cue in request.cues:
        if file_pin(confined_path(project, cue.source.path), 64 * 1024 * 1024)["sha256"] != cue.source.sha256:
            raise ValueError(f"{cue.cue_id}: source bytes changed")


def _chain(cue: AudioCue, index: int, request: AudioMixRequest) -> str:
    end = cue.source_offset_seconds + cue.duration_seconds
    steps = [f"atrim={cue.source_offset_seconds}:{end}", "asetpts=PTS-STARTPTS", f"aresample={request.sample_rate}",
             "aformat=channel_layouts=stereo", f"volume={cue.gain_db}dB"]
    if cue.fade_in_seconds:
        steps.append(f"afade=t=in:d={cue.fade_in_seconds}")
    if cue.fade_out_seconds:
        steps.append(f"afade=t=out:st={cue.duration_seconds - cue.fade_out_seconds}:d={cue.fade_out_seconds}")
    delay = round(cue.start_seconds * 1000)
    steps += [f"adelay={delay}|{delay}", f"apad=whole_dur={request.total_seconds}"]
    return f"[{index}:a]" + ",".join(steps) + f"[c{index}]"


def graph(request: AudioMixRequest) -> str:
    """Per-cue trims/levels/fades/placement, role buses, sidechain ducking of music under narration."""
    parts = [_chain(cue, i, request) for i, cue in enumerate(request.cues)]
    buses = {}
    for role in ROLES:
        labels = [f"[c{i}]" for i, cue in enumerate(request.cues) if cue.role == role]
        if labels:
            parts.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0:duration=longest[{role}]")
            buses[role] = f"[{role}]"
    if "narration" in buses and "music" in buses and request.duck_db > 0:
        ratio = round(1 + request.duck_db / 2, 2)
        parts.append("[narration]asplit=2[voice][key]")
        parts.append(f"[music][key]sidechaincompress=threshold=0.02:ratio={ratio}:attack={request.duck_attack_ms}"
                     f":release={request.duck_release_ms}[ducked]")
        buses.update(narration="[voice]", music="[ducked]")
    parts.append("".join(buses[r] for r in ROLES if r in buses)
                 + f"amix=inputs={len(buses)}:normalize=0:duration=longest,atrim=0:{request.total_seconds}[out]")
    return ";".join(parts)


def recipe(request: AudioMixRequest, inputs: list[str], target: str, binary: str) -> list[str]:
    """Exact argument list; the output is never an input, so a retry cannot layer a previous mix."""
    command = [binary, "-nostdin", "-hide_banner", "-v", "error", "-xerror"]
    for path in inputs:  # offline boundary: local files only, WAV demuxer only (no playlists/network)
        command += ["-protocol_whitelist", "file,pipe", "-f", "wav", "-i", path]
    return command + ["-filter_complex", graph(request), "-map", "[out]", "-c:a", "pcm_s16le",
                      "-ar", str(request.sample_rate), "-ac", "2", "-t", str(request.total_seconds), "-f", "wav", "-n", target]


def measure(path: Path, request: AudioMixRequest) -> dict:
    """Signal-level QA of the produced PCM WAV: format, exact duration, peak, clipping, edge levels."""
    with open_regular(path) as (stream, info):
        if info.st_size > MAX_OUTPUT_BYTES:
            raise ValueError("Mix output exceeds 64 MiB")
        with wave.open(stream, "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (2, 2, request.sample_rate):
                raise ValueError("Mix output is not 16-bit stereo PCM at the requested rate")
            frames = audio.getnframes()
            if frames * 4 > MAX_OUTPUT_BYTES:  # the fstat size can grow after the check; bound the reads themselves
                raise ValueError("Mix PCM header declares more data than the 64 MiB output cap")
            peak = clipped = 0
            edge = round(request.sample_rate * 0.01)
            head = read = 0
            tail_window = array.array("h")
            while chunk := audio.readframes(65536):
                if len(chunk) % 4:
                    raise ValueError("Mix PCM data is not frame aligned")
                if read * 4 + len(chunk) > MAX_OUTPUT_BYTES:
                    raise ValueError("Mix PCM data exceeds the 64 MiB output cap")
                samples = array.array("h", chunk)
                peak = max(peak, max((abs(s) for s in samples), default=0))
                clipped += sum(1 for s in samples if s in (32767, -32768))
                if read < edge:
                    head = max(head, max((abs(s) for s in samples[:2 * (edge - read)]), default=0))
                read += len(samples) // 2
                tail_window = (tail_window + samples)[-2 * edge:]
            if read != frames:
                raise ValueError(f"Mix PCM data is truncated: read {read} frames, header declares {frames}")
            tail = max((abs(s) for s in tail_window), default=0)
    expected = round(request.total_seconds * request.sample_rate)
    if abs(frames - expected) > 1:
        raise ValueError(f"Mix output duration differs: {frames} frames, expected {expected}")
    dbfs = lambda v: round(20 * math.log10(v / 32768), 2) if v else None  # noqa: E731
    return {"frames": frames, "duration_seconds": frames / request.sample_rate, "peak_dbfs": dbfs(peak),
            "clipped_samples": clipped, "clipping": clipped > 0, "head_peak_dbfs": dbfs(head), "tail_peak_dbfs": dbfs(tail),
            "listening_quality": "UNQUALIFIED", "ducking_attenuation": "UNQUALIFIED (level-dependent sidechain)"}


def _cache_key(request: AudioMixRequest, receipts: list, executables: dict, timing: dict) -> str:
    identity = {"request": request.model_dump(mode="json"), "rights": receipts, "graph": graph(request), "timing": timing,
                "ffmpeg_sha256": executables["ffmpeg"].get("sha256")}
    return hashlib.sha256(canonical(identity).encode()).hexdigest()


def _cached(project: Path, name: str, request: AudioMixRequest, metadata: dict) -> dict | None:
    """Revalidate bounded cache metadata and measured output; refuse altered receipts."""
    receipt_path = confined_path(project, name + ".json")
    if not receipt_path.exists():
        return None
    receipt, _ = project_object(project, name + ".json")
    expected_fields = set(metadata) | {"output", "output_sha256", "size_bytes", "qa"}
    if set(receipt) != expected_fields or any(receipt[k] != v for k, v in metadata.items()) or receipt["output"] != name:
        raise ValueError("Cached mix receipt metadata differs from the current request")
    target = confined_path(project, name)
    pin = file_pin(target, MAX_OUTPUT_BYTES)
    qa = measure(target, request)
    if (pin != {"sha256": receipt["output_sha256"], "size_bytes": receipt["size_bytes"]}
            or qa != receipt["qa"] or qa["clipping"] or file_pin(target, MAX_OUTPUT_BYTES) != pin):
        raise ValueError("Cached mix bytes or measured QA differ")
    return {**receipt, "cached": True}
    return None


async def _render(project: Path, request: AudioMixRequest, receipts: list, executables: dict, name: str) -> dict:
    directory = tempfile.TemporaryDirectory(prefix=".audio-mix-", dir=project)
    primary = None
    published = False
    try:
        work = directory.name
        inputs = []
        for i, cue in enumerate(request.cues):
            copy = Path(work) / f"in{i}{Path(cue.source.path).suffix}"
            snapshot(project, cue.source, copy)
            inputs.append(str(copy))
        out = Path(work) / "mix.wav"
        await run_media_process(recipe(request, inputs, str(out), executables["ffmpeg"]["path"]), TIMEOUT)
        qa = measure(out, request)
        if qa["clipping"]:
            raise ValueError("Mix clips; lower cue gains. No final output published")
        _sources_current(project, request)
        if [rights_receipt(project, c, request.principal, request.commercial) for c in request.cues] != receipts:
            raise ValueError("Audio rights changed during mixing")
        if codec_executables() != executables:
            raise ValueError("FFmpeg executable changed during mixing")
        pin = file_pin(out, MAX_OUTPUT_BYTES)
        publish(project, out, name, pin["sha256"])
        published = True
    except BaseException as error:
        primary = error
        raise
    finally:
        try:
            directory.cleanup()
        except OSError as cleanup:
            if primary is not None:
                primary.add_note(f"Audio mix work cleanup liability:{type(cleanup).__name__}")
            else:
                if published:
                    discard_published(project, name, pin["sha256"], cleanup)
                raise
    return {"output": name, "output_sha256": pin["sha256"], "size_bytes": pin["size_bytes"], "qa": qa}


async def mix_audio(project_id: str, request: AudioMixRequest) -> dict:
    """Mix licensed local cues once per source/recipe identity; identical retries return the cached receipt."""
    project = project_directory(project_id)
    with plan_transaction(project, create=True):  # existing fail-fast project admission: no racing retries
        timing = storyboard_windows(project, request)
        receipts = [rights_receipt(project, cue, request.principal, request.commercial) for cue in request.cues]
        _sources_current(project, request)
        executables = codec_executables()
        key = _cache_key(request, receipts, executables, timing)
        name = f"audio-mix-{key[:24]}.wav"
        receipt_path = confined_path(project, name + ".json")
        metadata = {"success": True, "cached": False, "cache_key": key, "sources": receipts, "timing": timing,
                    "recipe": graph(request), "ducking": "sidechain ratio 1+duck_db/2; level-dependent, attenuation UNQUALIFIED",
                    "provider_calls": 0, "generation": "none", "rights_verified": False}
        cached = _cached(project, name, request, metadata)
        if cached:
            return cached
        rendered = await _render(project, request, receipts, executables, name)
        receipt = {**metadata, **rendered}
        try:
            atomic_write(receipt_path, canonical(receipt))
        except BaseException as error:
            discard_published(project, name, rendered["output_sha256"], error)
            raise
        return receipt
