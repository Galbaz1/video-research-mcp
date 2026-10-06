"""Deterministic local reference, timing, stem mix, remux and measured FFmpeg QA."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import time

from . import dubbing_client as client
from .dubbing_contracts import artifact, read_json, verify_artifact
from .media_probe import binary, FORMATS, inspect_media
from .media_process import run_media_process
from .media_snapshot import checked_path


def command(inputs: list[Path], arguments: list[str]) -> list[str]:
    """Build a file-only, bounded FFmpeg invocation from locally held inputs."""
    result = [binary("ffmpeg"), "-nostdin", "-hide_banner", "-v", "error", "-xerror"]
    for path in inputs:
        result.extend(["-max_alloc", "67108864", "-threads", "1", "-protocol_whitelist", "file",
                       "-format_whitelist", FORMATS, "-i", str(checked_path(str(path)))])
    return result + arguments


async def produce(inputs: list[Path], arguments: list[str], output: Path) -> dict:
    """Reuse only verified completed process outputs; retain interrupted intent."""
    output = checked_path(str(output))
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    argv = command(inputs, arguments + ["-n", str(output)])
    input_records = [artifact(p) for p in inputs]
    signature = hashlib.sha256(client.canonical({"argv": argv, "inputs": input_records})).hexdigest()
    journal = output.with_suffix(output.suffix + ".process.json")
    if journal.exists():
        record = read_json(journal)
        if record.get("signature") != signature or record.get("state") != "complete":
            raise client.DubbingError("process_requires_reconciliation")
        verify_artifact(record["output"], output.parent)
        return record["output"]
    client.write_json(journal, {"state": "intent", "signature": signature, "argv": argv})
    await run_media_process(argv, 900)
    value = artifact(output)
    client.write_json(journal, {"state": "complete", "signature": signature, "argv": argv,
                               "inputs": input_records, "output": value})
    return value


async def extract_audio(source: Path, output: Path) -> dict:
    """Extract the full source audio to a 48 kHz stereo PCM service input."""
    return await produce([source], ["-map", "0:a:0", "-vn", "-ar", "48000", "-ac", "2",
                                    "-c:a", "pcm_s16le"], output)


def _voice_folder(root: Path, group_id: str, key: str, regenerate: bool) -> Path:
    """Keep unknown effects occupied even when a plan or generation name changes."""
    group_root = root / "work/voices" / group_id
    pointer = group_root / "active.json"
    if pointer.exists():
        previous = read_json(pointer)
        folder = checked_path(previous["folder"])
        if not folder.is_relative_to(group_root):
            raise client.DubbingError("voice_generation_path_invalid")
        for path in folder.glob("candidate-*.intent.json"):
            intent = read_json(path)
            if (intent.get("state") != "response_saved" or not 200 <= intent.get("http_status", 0) < 300
                    or hashlib.sha256(client.bounded_bytes(path.with_suffix(".response.json"),
                            client.MAX_RESPONSE_BYTES, "service_response_cache_changed")).hexdigest() != intent.get("response_sha256")):
                raise client.DubbingError("service_effect_requires_reconciliation")
            client.audio_bytes(path.with_suffix("").with_suffix(".wav"))
        for path in folder.glob("*.process.json"):
            process = read_json(path)
            if process.get("state") != "complete":
                raise client.DubbingError("process_requires_reconciliation")
            verify_artifact(process["output"], root)
            for item in process["inputs"]:
                verify_artifact(item, root)
        if regenerate and previous["key"] == key and not any(folder.glob("fitted*.wav")):
            raise client.DubbingError("timing_failed_shorten_translation")
        if previous["key"] == key and not regenerate:
            return folder
    folder = group_root / key
    if regenerate:
        folder = folder / "regenerations" / str(time.time_ns())
    client.write_json(pointer, {"key": key, "folder": str(folder)})
    return folder


async def synthesize_group(root: Path, manifest, plan, group, slot: dict,
                           regenerate: bool = False) -> dict:
    """Cut evidenced references, reuse exact TTS, and bound overlong candidates."""
    key = hashlib.sha256(client.canonical({"source": manifest.source_sha256,
                                         "vocals": manifest.vocals.sha256,
                                         "language": plan.target_language,
                                         "group": group.model_dump()})).hexdigest()
    folder = _voice_folder(root, group.segment_id, key, regenerate)
    fit_key = hashlib.sha256(client.canonical(slot)).hexdigest()
    reference = folder / "reference.wav"
    await produce([Path(manifest.vocals.path)],
                  ["-ss", str(group.reference.start_sec), "-t",
                   str(group.reference.end_sec - group.reference.start_sec), "-ar", "48000",
                   "-ac", "2", "-c:a", "pcm_s16le"], reference)
    from .dubbing_contracts import estimated_seconds

    attempts = 3 if estimated_seconds(group.translated_text, plan.target_language) / slot["duration_sec"] <= 1.35 else 1
    candidates = []
    for attempt in range(1, attempts + 1):
        raw = folder / f"candidate-{attempt}.wav"
        result = await client.tts(group.translated_text, reference, raw)
        candidates.append({"attempt": attempt, "audio": result,
                           "fits": result["duration_sec"] <= slot["duration_sec"] * 1.18 + 1e-6})
        client.write_json(folder / "candidates.json", {"candidates": candidates})
        if candidates[-1]["fits"]:
            return await fit_voice(raw, folder / f"fitted-{fit_key}.wav", group, slot, result, candidates, reference)
    raise client.DubbingError("timing_failed_shorten_translation")


async def fit_voice(raw: Path, output: Path, group, slot: dict, result: dict,
                    candidates: list[dict], reference: Path) -> dict:
    """Preserve short speech pace, bound acceleration and center padding/fades."""
    duration = client.pcm_metadata(client.audio_bytes(raw))["duration_sec"]
    speed = max(1.0, duration / slot["duration_sec"])
    if speed > 1.18 + 1e-6:
        raise client.DubbingError("timing_failed_shorten_translation")
    spoken = duration / speed
    padding = max(0.0, (slot["duration_sec"] - spoken) / 2)
    # Buffered identity tempo can invalidate the leading delay timestamps.
    tempo = f"atempo={speed}," if speed > 1.0 else ""
    filters = (f"{tempo}afade=t=in:st=0:d=0.015,"
               f"afade=t=out:st={max(0, spoken - 0.015)}:d=0.015,"
               f"adelay={round(padding * 1000)}:all=1,apad=whole_dur={slot['duration_sec']},"
               f"atrim=duration={slot['duration_sec']}")
    audio = await produce([raw], ["-af", filters, "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le"], output)
    actual = client.pcm_metadata(client.audio_bytes(output))
    if abs(actual["duration_sec"] - slot["duration_sec"]) > 0.002:
        raise client.DubbingError("fitted_voice_duration_invalid")
    flags = list(slot["flags"])
    if speed > 1.12:
        flags.append("acceleration_above_1.12x")
    if spoken / slot["duration_sec"] < 0.60:
        flags.append("speech_fill_below_0.60")
    if group.reference.end_sec - group.reference.start_sec < 1.5:
        flags.append("short_voice_reference")
    if len(group.source_segment_ids) > 1:
        flags.append("merged_source_segments")
    if padding * 2 > 0.4:
        flags.append("large_boundary_silence")
    if len(candidates) > 1:
        flags.append("tts_retry")
    return {**slot, "audio": audio, "raw": result, "reference": artifact(reference),
            "speed": speed, "speech_fill_ratio": spoken / slot["duration_sec"], "flags": flags,
            "tts_generated_attempts": len(candidates), "timing": "PASS",
            "listening": "UNRESOLVED", "translated_text": group.translated_text,
            "speaker": group.speaker}


async def mix(root: Path, manifest, voices: list[dict], background_mode: str) -> tuple[dict, dict, dict]:
    """Assemble unnormalized stems, then normalize the whole mix in two passes."""
    inputs = [Path(manifest.no_vocals.path)] if background_mode == "include" else []
    labels, filters = [], []
    if inputs:
        filters.append("[0:a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo[bg]")
        labels.append("[bg]")
    for voice in voices:
        index = len(inputs)
        inputs.append(Path(voice["audio"]["path"]))
        filters.append(f"[{index}:a]adelay={round(voice['start_sec'] * 1000)}:all=1[v{index}]")
        labels.append(f"[v{index}]")
    filters.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0,apad,"
                   f"atrim=duration={manifest.duration_sec}[mix]")
    premix = root / "full/premix.wav"
    premix_record = await produce(inputs, ["-filter_complex", ";".join(filters), "-map", "[mix]",
                                          "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le"], premix)
    measured = await measure_loudness(premix)
    norm = ("loudnorm=I=-16:TP=-1.5:LRA=11:linear=true:"
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}")
    normalized = await produce([premix], ["-af", norm, "-ar", "48000", "-ac", "2",
                                          "-c:a", "pcm_s16le"], root / "full/mix.wav")
    bus = client.pcm_metadata(client.audio_bytes(Path(normalized["path"])))
    if bus["sample_rate"] != 48000 or bus["channels"] != 2 or abs(bus["duration_sec"] - manifest.duration_sec) > 0.002:
        raise client.DubbingError("mix_bus_format_or_duration_invalid")
    return premix_record, normalized, {"background_mode": background_mode,
                                      "background": manifest.no_vocals.model_dump() if background_mode == "include" else None,
                                      "voices": [v["audio"] for v in voices], "normalization": measured}


async def measure_loudness(path: Path) -> dict:
    """Require actual finite FFmpeg EBU R128 measurements before normalization."""
    argv = command([path], ["-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json", "-f", "null", "-"])
    argv[argv.index("error")] = "info"
    _, stderr = await run_media_process(argv, 900)
    matches = re.findall(rb"\{[^{}]*\}", stderr)
    try:
        data = json.loads(matches[-1])
        fields = {key: float(data[key]) for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")}
        if not all(math.isfinite(value) for value in fields.values()):
            raise ValueError("nonfinite")
    except (IndexError, KeyError, ValueError, TypeError):
        raise client.DubbingError("loudness_measurement_invalid") from None
    return fields


async def remux(root: Path, manifest, mixed: dict) -> dict:
    """Copy every video/subtitle stream and replace original audio with the bus."""
    observed = await inspect_media(manifest.source.path)
    if any(s.get("codec_type") not in {"video", "audio", "subtitle"} for s in observed["streams"]):
        raise client.DubbingError("source_stream_type_unsupported")
    maps = []
    for stream in observed["streams"]:
        if stream["codec_type"] in {"video", "subtitle"}:
            maps.extend(["-map", f"0:{stream['index']}"])
    return await produce([Path(manifest.source.path), Path(mixed["path"])],
                         maps + ["-map", "1:a:0", "-map_metadata", "0",
                          "-map_chapters", "0", "-c:v", "copy", "-c:s", "copy",
                          "-c:a", "flac", "-sample_fmt", "s16"], root / "full/translated.mkv")


async def stream_hash(path: Path, index: int, *, decoded: bool = False) -> str:
    """Hash full encoded streams or lossless decoded stereo PCM through FFmpeg."""
    options = ["-map", f"0:{index}"]
    options += ["-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2"] if decoded else ["-c", "copy"]
    stdout, _ = await run_media_process(command([path], options + ["-f", "hash", "-hash", "sha256", "-"]), 900)
    match = re.fullmatch(rb"SHA256=([a-f0-9]{64})\s*", stdout)
    if not match:
        raise client.DubbingError("stream_hash_invalid")
    return match[1].decode()


async def technical_qa(root: Path, manifest, output: dict, mixed: dict, voices: list[dict]) -> dict:
    """Execute all-stream, duration, full-decode, stream identity and mix checks."""
    source_path, output_path = Path(manifest.source.path), Path(output["path"])
    source, final = await inspect_media(str(source_path)), await inspect_media(str(output_path))
    source_preserved = [s for s in source["streams"] if s.get("codec_type") in {"video", "subtitle"}]
    final_preserved = [s for s in final["streams"] if s.get("codec_type") in {"video", "subtitle"}]
    audios = [s for s in final["streams"] if s.get("codec_type") == "audio"]
    checks = {"output_hash": artifact(output_path) == output, "all_streams": len(source_preserved) == len(final_preserved) and len(audios) == 1
              and len(final["streams"]) == len(final_preserved) + 1 and any(s.get("codec_type") == "video" for s in final_preserved),
              "duration": final["duration_seconds"] is not None and abs(final["duration_seconds"] - manifest.duration_sec) <= 0.35,
              "segment_count": len(voices) > 0, "video_subtitle_preserved": True,
              "timing": all(v["timing"] == "PASS" for v in voices)}
    for left, right in zip(source_preserved, final_preserved):
        checks["video_subtitle_preserved"] &= (left.get("codec_type") == right.get("codec_type")
                                               and left.get("codec_name") == right.get("codec_name")
                                               and await stream_hash(source_path, left["index"]) == await stream_hash(output_path, right["index"]))
    await run_media_process(command([output_path], ["-map", "0:v", "-map", "0:a", "-f", "null", "-"]), 900)
    for stream in final_preserved:
        if stream["codec_type"] == "subtitle":
            await run_media_process(command([output_path], ["-map", f"0:{stream['index']}", "-f", "ass", "-"]), 900)
    checks["full_decode"] = True
    bus = client.pcm_metadata(client.audio_bytes(Path(mixed["path"])))
    checks["mix_bus"] = bus["sample_rate"] == 48000 and bus["channels"] == 2 and abs(bus["duration_sec"] - manifest.duration_sec) <= 0.002
    checks["stem_mix"] = await stream_hash(output_path, audios[0]["index"], decoded=True) == await stream_hash(Path(mixed["path"]), 0, decoded=True) if len(audios) == 1 else False
    originals = [s for s in source["streams"] if s.get("codec_type") == "audio"]
    checks["audio_replaced"] = bool(originals and audios) and await stream_hash(source_path, originals[0]["index"], decoded=True) != await stream_hash(output_path, audios[0]["index"], decoded=True)
    return {"checks": checks, "technical_pass": all(checks.values()),
            "source_streams": source["streams"], "streams": final["streams"],
            "duration_sec": final["duration_seconds"]}
