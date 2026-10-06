"""Exact source-event captions and conservative bounds for explicit local TTF fonts."""

import hashlib
import re
import struct

from .file_io import open_regular
from .render_storyboard_sources import confined_path
from .storyboard_timing import validated_words


def font_metrics(project, ref) -> dict:
    """Read a finite TrueType header/cmap; refuse unsupported fonts before rendering."""
    with open_regular(confined_path(project, ref.path)) as (stream, info):
        if not 0 < info.st_size <= 8 * 1024 * 1024:
            raise ValueError("TTF exceeds8MiB or is empty")
        data = stream.read(8 * 1024 * 1024 + 1)
    if len(data) != info.st_size or hashlib.sha256(data).hexdigest() != ref.sha256:
        raise ValueError("Font bytes changed")
    if data[:4] != b"\x00\x01\x00\x00" or len(data) < 12:
        raise ValueError("Only standalone TrueType fonts are supported")
    count = struct.unpack_from(">H", data, 4)[0]
    if not 1 <= count <= 64 or len(data) < 12 + 16 * count:
        raise ValueError("Malformed TTF directory")
    tables = {}
    for i in range(count):
        tag, _, offset, size = struct.unpack_from(">4sIII", data, 12 + i * 16)
        if tag in tables or offset + size > len(data):
            raise ValueError("Malformed TTF table bounds")
        tables[tag] = data[offset:offset + size]
    if not {b"head", b"hhea", b"cmap", b"glyf", b"maxp", b"hmtx"} <= tables.keys():
        raise ValueError("Unsupported TTF tables")
    head, hhea, maxp = tables[b"head"], tables[b"hhea"], tables[b"maxp"]
    if len(head) < 54 or len(hhea) < 36 or len(maxp) < 6:
        raise ValueError("Incomplete TTF metrics")
    units = struct.unpack_from(">H", head, 18)[0]
    xmin, ymin, xmax, ymax = struct.unpack_from(">hhhh", head, 36)
    advance = struct.unpack_from(">H", hhea, 10)[0]
    glyphs, advances = struct.unpack_from(">H", maxp, 4)[0], struct.unpack_from(">H", hhea, 34)[0]
    if not 1 <= advances <= glyphs or len(tables[b"hmtx"]) < 4 * advances + 2 * (glyphs - advances):
        raise ValueError("Incomplete TTF glyph advances")
    if max(struct.unpack_from(">H", tables[b"hmtx"], i * 4)[0] for i in range(advances)) > advance:
        raise ValueError("TTF advance maximum is inconsistent")
    if not 16 <= units <= 16384 or not advance or xmax <= xmin or ymax <= ymin:
        raise ValueError("Invalid TTF metrics")
    return {"units": units, "advance": advance, "box_width": xmax - xmin, "box_height": ymax - ymin,
            "cmap": tables[b"cmap"], "sha256": ref.sha256, "glyphs": glyphs}


def glyph_available(cmap: bytes, char: str, glyphs: int) -> bool:
    """Support only bounded format4 BMP cmaps and nonzero glyph mappings."""
    if len(cmap) < 4:
        return False
    count = struct.unpack_from(">H", cmap, 2)[0]
    if count > 32 or len(cmap) < 4 + count * 8:
        return False
    for i in range(count):
        offset = struct.unpack_from(">I", cmap, 8 + i * 8)[0]
        if offset + 16 > len(cmap) or struct.unpack_from(">H", cmap, offset)[0] != 4:
            continue
        length, segments = struct.unpack_from(">H", cmap, offset + 2)[0], struct.unpack_from(">H", cmap, offset + 6)[0] // 2
        table = cmap[offset:offset + length]
        if not 1 <= segments <= 512 or len(table) != length or length < 16 + 8 * segments:
            continue
        for n in range(segments):
            end = struct.unpack_from(">H", table, 14 + 2 * n)[0]
            start = struct.unpack_from(">H", table, 16 + 2 * segments + 2 * n)[0]
            if start <= ord(char) <= end:
                delta = struct.unpack_from(">h", table, 16 + 4 * segments + 2 * n)[0]
                location = 16 + 6 * segments + 2 * n
                distance = struct.unpack_from(">H", table, location)[0]
                address = location + distance + 2 * (ord(char) - start)
                if not distance:
                    return 0 < (ord(char) + delta) % 65536 < glyphs
                if address + 2 <= len(table):
                    glyph = struct.unpack_from(">H", table, address)[0]
                    return glyph != 0 and 0 < (glyph + delta) % 65536 < glyphs
    return False


def source_cues(narration: dict, timing: dict, scenes: list) -> list[dict]:
    """Keep accepted word sample spans and transcript text, never infer alignment."""
    words = validated_words(narration, {"sample_rate": timing["sample_rate"], "frames": timing["total_samples"]})
    if not words:
        raise ValueError("Missing caption alignment")
    first, last, rate = scenes[0]["start_sample"], scenes[-1]["end_sample"], timing["sample_rate"]
    cues = [{"text": w["word"], "start_sample": w["start_frame"] - first,
             "end_sample": w["end_frame"] - first, "method": w["alignment"], "sample_rate": rate}
            for w in words if first <= w["start_frame"] < w["end_frame"] <= last]
    if not cues or len(cues) > 256:
        raise ValueError("Captions require1..256 existing words")
    for cue in cues:
        if not re.fullmatch(r"[ -~]{1,64}", cue["text"]) or any(c in cue["text"] for c in "{}\\"):
            raise ValueError("Supported captions require1..64 plain printable ASCII characters")
    return cues


def srt_text(cues: list) -> str:
    """Export strict monotonic source milliseconds; reject precision lost by SRT."""
    result, end = [], 0
    for i, cue in enumerate(cues, 1):
        a, b = (cue[k] * 1000 // cue["sample_rate"] for k in ("start_sample", "end_sample"))
        if not end <= a < b:
            raise ValueError("Source word precision cannot form monotonic SRT intervals")
        def stamp(ms):
            return f"{ms // 3600000:02}:{ms // 60000 % 60:02}:{ms // 1000 % 60:02},{ms % 1000:03}"
        result.append(f"{i}\n{stamp(a)} --> {stamp(b)}\n{cue['text']}\n")
        end = b
    return "\n".join(result)


def check_srt(project, ref, expected: str) -> None:
    """Accept only an exact timestamp/text export of current admitted word events."""
    with open_regular(confined_path(project, ref.path)) as (stream, info):
        if info.st_size > 65536:
            raise ValueError("SRT exceeds64KiB")
        data = stream.read(65537)
    if len(data) > 65536 or hashlib.sha256(data).hexdigest() != ref.sha256:
        raise ValueError("SRT bytes changed")
    if data.decode("utf-8").replace("\r\n", "\n").strip() != expected.strip():
        raise ValueError("SRT text/timestamps differ from current source words")


def caption_layout(cues: list, metrics: dict, width: int, height: int) -> dict:
    """Conservatively fit every glyph/advance inside explicit caption safe margins."""
    margin, size = max(24, width // 20), 24
    largest = max(len(c["text"]) for c in cues)
    bound = (largest * metrics["advance"] + 2 * metrics["box_width"]) / metrics["units"]
    size = min(size, int((width - 2 * margin) / bound), int((height // 4) * metrics["units"] / metrics["box_height"]))
    if size < 12 or any(not glyph_available(metrics["cmap"], c, metrics["glyphs"]) for cue in cues for c in cue["text"] if c != " "):
        raise ValueError("Font lacks caption glyphs or safe readable bounds")
    return {"font_size": size, "margin": margin, "max_width": bound * size,
            "max_height": metrics["box_height"] * size / metrics["units"], "method": "conservative_ttf_bounds_v1"}
