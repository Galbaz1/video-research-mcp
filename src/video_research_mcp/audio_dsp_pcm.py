"""Bounded stereo PCM selections with measured source clocks and full WAV readback."""

import hashlib
import io
import wave

from .audio_assets import audio_command, audio_filter, audio_window, measured_audio, validate_audio
from .image_preprocessing import check_worker, image_worker
from .media_local_io import _open_regular
from .media_process import run_media_process

RATE = 48000
MAX_SECONDS = 30
MAX_BYTES = 8 * 1024 * 1024


def read_pcm(path, channels, cancelled, deadline):
    """Require complete48kHz signed16 WAV samples; bind file and PCM identities."""
    check_worker(cancelled, deadline)
    with _open_regular(path) as reader:
        data = reader.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("DSP WAV exceeds8MiB")
    with wave.open(io.BytesIO(data), "rb") as audio:
        if (
            audio.getnchannels(),
            audio.getsampwidth(),
            audio.getframerate(),
            audio.getcomptype(),
        ) != (channels, 2, RATE, "NONE"):
            raise ValueError("DSP WAV has an incompatible PCM format")
        frames = audio.getnframes()
        if not 2048 <= frames <= RATE * MAX_SECONDS:
            raise ValueError("DSP selection must contain2048 samples through30 seconds")
        pcm = audio.readframes(frames + 1)
        if len(pcm) != frames * channels * 2:
            raise ValueError("DSP WAV has a truncated sample body")
    check_worker(cancelled, deadline)
    return pcm, {
        "path": str(path),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "pcm_sha256": hashlib.sha256(pcm).hexdigest(),
        "frames": frames,
        "sample_rate": RATE,
        "channels": channels,
        "sample_format": "signed16_little_endian",
        "duration_seconds": frames / RATE,
        "mime": "audio/wav",
        "role": "selected_audio",
    }


async def select_pcm(owned, request, source):
    """Decode the requested interval without mixing stereo or exposing original paths to DSP."""
    channels = source["audio_channels"]
    if channels not in (1, 2):
        raise ValueError("DSP supports mono or stereo; multichannel weighting is unqualified")
    end, guarded = audio_window(source, request.start_seconds, request.end_seconds, MAX_SECONDS)
    path = owned.directory / "selected.wav"
    command = audio_command(owned, source["audio_stream_index"]) + [
        "-af",
        audio_filter(source, request.start_seconds, end, RATE, reset=True),
        "-ac",
        str(channels),
        "-ar",
        str(RATE),
        "-c:a",
        "pcm_s16le",
        "-fs",
        str(MAX_BYTES),
        "-f",
        "wav",
        "-n",
        str(path),
    ]
    _, stderr = await run_media_process(command, owned.remaining())
    clock = measured_audio(stderr, source["audio_clock_origin_seconds"], request.start_seconds, end)
    validate_audio(clock, source, request.start_seconds, end, RATE, guarded)
    pcm, selection = await image_worker(read_pcm, path, channels, deadline=owned.deadline)
    if selection["frames"] != clock["sample_count"]:
        raise ValueError("DSP PCM count differs from the observed source clock")
    selection["source_clock"] = clock
    selection["source_reference"] = (
        f"urn:sha256:{source['sha256']}#t={clock['first_seconds']},{clock['end_seconds']}"
    )
    return source, pcm, selection
