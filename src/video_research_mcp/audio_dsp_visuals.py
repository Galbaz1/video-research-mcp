"""Decode only the pinned Ferrous PNG fields into bounded attributed file artifacts."""

import base64
import hashlib
import json
import os
from pathlib import Path

from .audio_dsp_native import read_png
from .image_preprocessing import check_worker
from .media_local_io import _open_regular


def export_native_views(record, selection, directory, cancelled, deadline):
    """Require all three source-defined visuals, with actual PNG decode and exact1920x600 grids."""
    check_worker(cancelled, deadline)
    with _open_regular(Path(record["path"])) as reader:
        body = reader.read(4 * 1024 * 1024 + 1)
    if len(body) > 4 * 1024 * 1024 or hashlib.sha256(body).hexdigest() != record["sha256"]:
        raise ValueError("Native visual response changed before PNG export")
    payload = json.loads(body)
    texts = payload["result"]["content"]
    if len(texts) != 1:
        raise ValueError("Ferrous visual workflow requires one native JSON text block")
    visuals = json.loads(texts[0]["text"])["visuals"]
    artifacts = []
    for name in ("waveform", "spectrogram", "power_curve"):
        encoded = visuals.get(name)
        if not isinstance(encoded, str) or len(encoded) > 1024 * 1024:
            raise ValueError("Native visual workflow has a missing or oversized PNG")
        data = base64.b64decode(encoded, validate=True)
        path = directory / ("ferrous-" + name + ".png")
        with path.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            writer.write(data)
        artifact = read_png(path, (1920, 600), cancelled, deadline)
        artifacts.append(
            {
                **artifact,
                "role": "native_ferrous_" + name,
                "source_reference": selection["source_reference"],
                "selected_pcm_sha256": selection["pcm_sha256"],
                "native_response_sha256": record["sha256"],
                "source": record["source"],
                "pixels_verified": True,
                "native_axis_numerical_correctness_verified": False,
                "native_zero_absolute_source_seconds": selection["source_clock"]["first_seconds"],
            }
        )
    check_worker(cancelled, deadline)
    return artifacts
