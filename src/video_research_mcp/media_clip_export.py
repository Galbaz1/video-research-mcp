"""Short, byte-bounded local source clips with exact original-PTS lineage."""

from __future__ import annotations

from fractions import Fraction

from .config import get_config
from .media_clip_timing import decoded_output, source_audio, source_frames, verify_output
from .media_frames import _source_clock
from .media_image_read import MAX_ARTIFACT_BYTES, decode_command, geometry
from .media_probe import FORMATS, binary, probe_snapshot
from .media_process import run_media_process
from .media_snapshot import copy_hash, snapshot
from .models.media_export import ClipExportRequest, ClipExportResult
from .models.scene_assets import ClipSelectionRequest


def _bounds(source: dict, request: ClipExportRequest) -> tuple:
    """Preflight observable clocks, display coordinates, declared rate and audio allocation."""
    duration, offset = _source_clock(source)
    if request.start_seconds >= duration or request.end_seconds > duration:
        raise ValueError("Clip interval is outside the source presentation extent")
    video = next(s for s in source["streams"] if s["index"] == source["stream_index"])
    for field in ("avg_frame_rate", "r_frame_rate"):
        if video.get(field) and video[field] != "0/0":
            rate = Fraction(video[field])
            if rate <= 0 or rate > 30:
                raise ValueError("Clip declared video rate must be at most 30 FPS")
            if rate * (request.end_seconds - request.start_seconds) > 256:
                raise ValueError("Clip declared rate/window exceeds the 256 frame budget")
    width, height, transform = geometry(source, request.max_pixels, request.crop_box)
    unrounded = [width, height]
    width, height = width - width % 2, height - height % 2
    if width < 2 or height < 2:
        raise ValueError("H264 clip dimensions must be at least two pixels")
    transform = transform.replace(f"scale={unrounded[0]}:{unrounded[1]}", f"scale={width}:{height}")
    scale = {"unrounded_dimensions": unrounded, "output_dimensions": [width, height],
             "rounding": "floor_to_even_without_padding"}
    audio = next((s for s in source["streams"] if s.get("codec_type") == "audio"), None)
    if request.include_audio and audio:
        if not 1 <= int(audio.get("sample_rate", 0)) <= 48000 or not 1 <= audio.get("channels", 0) <= 2:
            raise ValueError("Clip audio must have at most 48 kHz and two channels")
    else:
        audio = None
    return offset, width, height, transform, audio, scale


def _window(request: ClipExportRequest, offset: float) -> tuple[list[str], str]:
    """Seek locally, then select exact original decoded PTS rather than relabeling seek time."""
    start, end = request.start_seconds + offset, request.end_seconds + offset
    options = ["-ss", str(request.start_seconds), "-t", str(request.end_seconds - request.start_seconds + 1)]
    expression = f"gte(t,{start:.12f})*lt(t,{end:.12f})"
    return options, expression


async def _selected(owned, source: dict, request: ClipExportRequest, offset: float) -> list[dict]:
    """Bound the selection pass at 257 frames so overflow fails before encoding."""
    options, expression = _window(request, offset)
    command = decode_command(owned, source, before_input=options)
    command.extend(["-vf", f"select='{expression}',showinfo", "-frames:v", "257",
                    "-fps_mode", "passthrough", "-f", "null", "-"])
    _, stderr = await run_media_process(command, owned.remaining())
    return source_frames(stderr, source, request.start_seconds, request.end_seconds)


def _encode_command(owned, source, request, offset, transform, audio, output) -> list[str]:
    """Keep one source clock across streams; strip original metadata from a private MP4."""
    options, expression = _window(request, offset)
    origin = request.start_seconds + offset
    command = [binary("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-v", "info", "-n",
               "-max_alloc", "67108864", "-max_pixels", "8000000", "-threads", "1",
               "-filter_threads", "1", "-protocol_whitelist", "file", "-format_whitelist", FORMATS,
               *options, "-copyts", "-i", str(owned.path), "-map", f"0:{source['stream_index']}",
               "-sn", "-dn", "-map_metadata", "-1", "-map_chapters", "-1",
               "-vf", f"select='{expression}',showinfo,setpts=PTS-{origin:.12f}/TB,{transform}",
               "-frames:v", "256", "-fps_mode", "passthrough", "-c:v", "libx264",
               "-threads", "1", "-preset", "veryfast", "-tune", "zerolatency", "-crf", "18", "-bf", "0",
               "-pix_fmt", "yuv420p", "-enc_time_base:v", "1:1000000", "-video_track_timescale", "1000000"]
    if audio:
        command.extend(["-map", f"0:{audio['index']}", "-af",
                        f"atrim=start={origin:.12f}:end={request.end_seconds + offset:.12f},"
                        f"ashowinfo,asetpts=PTS-{origin:.12f}/TB", "-c:a", "aac", "-b:a", "96k"])
    else:
        command.append("-an")
    command.extend(["-avoid_negative_ts", "disabled", "-flush_packets", "1", "-fs", str(MAX_ARTIFACT_BYTES),
                    "-movflags", "+faststart", str(output)])
    return command


def _audio_result(measured, source_clock, frames, start, requested: bool) -> dict:
    """Report observed A/V endpoint clocks without promoting them to perceptual synchrony."""
    encoded = measured["audio"]
    if source_clock is None:
        if encoded is not None:
            raise ValueError("Encoded clip contains audio absent from the requested source selection")
        return {"included": False, "status": "source_has_no_audio" if requested else "excluded_by_request"}
    if encoded is None:
        raise ValueError("Requested source audio is absent from the decoded encoded clip")
    original_delta = frames[0]["actual_seconds"] - source_clock["first_seconds"]
    output_delta = measured["output"]["first_frame_seconds"] - encoded["first_seconds"]
    return {"included": True, "status": "decoded_timestamps_observed_perceptual_sync_unverified",
            "source_decoded": source_clock, "output_decoded": encoded,
            "source_av_start_delta_seconds": original_delta, "output_av_start_delta_seconds": output_delta,
            "timestamp_start_delta_error_seconds": output_delta - original_delta,
            "output_end_padding_seconds": encoded["end_seconds"] - (source_clock["end_seconds"] - start)}


async def export_clip(request: ClipExportRequest) -> dict:
    """Export a measured source clip, publishing only after source/artifact manifest checks."""
    request = ClipExportRequest.model_validate(request)
    async with snapshot(request.file_path, request.expected_source_sha256) as owned:
        source = await probe_snapshot(owned)
        return await _export(owned, source, request)


async def export_selected_clip(request: ClipSelectionRequest) -> dict:
    """Resolve omitted endpoints from the exact source before applying existing clip gates."""
    request = ClipSelectionRequest.model_validate(request)
    async with snapshot(request.file_path, request.expected_source_sha256) as owned:
        source = await probe_snapshot(owned)
        duration, _ = _source_clock(source)
        selection = request.model_dump()
        selection["end_seconds"] = duration if request.end_seconds is None else request.end_seconds
        return await _export(owned, source, ClipExportRequest.model_validate(selection))


async def _export(owned, source, request) -> dict:
    """Encode and verify one already selected exact-source window."""
    from .image_manifest import write_manifest

    offset, width, height, transform, audio, scale = _bounds(source, request)
    frames = await _selected(owned, source, request, offset)
    output = owned.directory / "clip.mp4"
    command = _encode_command(owned, source, request, offset, transform, audio, output)
    _, stderr = await run_media_process(command, owned.remaining())
    encoded_sources = source_frames(stderr, source, request.start_seconds, request.end_seconds)
    if encoded_sources != frames:
        raise ValueError("Encoding did not visit exactly the selected original frames")
    if not 0 < output.stat().st_size <= MAX_ARTIFACT_BYTES:
        raise ValueError("Encoded clip exceeds the 8 MiB artifact byte budget")
    measured = await decoded_output(output, owned)
    verify_output(measured, frames, request.start_seconds, width, height)
    audio_clock = source_audio(stderr, offset, request.start_seconds, request.end_seconds) if audio else None
    digest, size = await copy_hash(output)
    output.chmod(0o600)
    metadata = _metadata(source, request, frames, measured, audio_clock, output, digest, size, scale)
    await owned.verify()
    metadata["manifest"] = await write_manifest(metadata, owned.directory)
    return ClipExportResult.model_validate(metadata).model_dump()


def _metadata(source, request, frames, measured, audio_clock, output, digest, size, scale) -> dict:
    """Keep original frame points, encoded clocks and extraction identity distinct."""
    return {"source": source, "operation": "source_clip_export", "provenance": "extracted_source_clip",
            "coordinate_space": "display_pixels", "crop_box": request.crop_box,
            "requested_interval": {"start_seconds": request.start_seconds, "end_seconds": request.end_seconds},
            "actual_selected_interval": {"first_frame_seconds": frames[0]["actual_seconds"],
                                         "last_frame_seconds": frames[-1]["actual_seconds"],
                                         "end_seconds": None, "last_frame_hold_verified": False},
            "source_frames": frames, "output": measured["output"],
            "audio": _audio_result(measured, audio_clock, frames, request.start_seconds, request.include_audio),
            "artifacts": [{"path": str(output), "sha256": digest, "bytes": size, "mime": "video/mp4",
                           "width": measured["output"]["width"], "height": measured["output"]["height"]}],
            "status": "complete", "watched_intervals": [],
            "limits": {"max_duration_seconds": 60, "max_frames": 256, "max_fps": 30,
                       "max_frame_pixels": 1_000_000, "max_artifact_bytes": MAX_ARTIFACT_BYTES,
                       "max_audio_rate": 48000, "max_audio_channels": 2, "process_output_bytes": 1048576,
                       "operation_timeout_seconds": get_config().media_acquire_timeout_seconds,
                       "ffmpeg_max_alloc_bytes": 67108864, "process_rss_bound": None, "scale": scale,
                       "output_codec": "h264_aac_mp4", "source_last_frame_hold_verified": False,
                       "color_profile_verified": False, "rights_verified": False,
                       "upstream_parity": "programme_derived_clip_scope"}}
