"""Separate finite source-domain predicates from authored diagram and caption geometry."""

import math
import textwrap

from .education_glyphs import display_text

BACKGROUND = (24, 32, 48)
FOREGROUND = (238, 244, 250)
DIAGRAM = (72, 204, 188)
DIAGRAM_BOX = [48, 54, 592, 258]
CAPTION_BOX = [24, 282, 616, 342]
IDS = ["triangle", "curve", "circuit"]
TERMINALS = {"battery.p": (160, 140), "battery.n": (160, 220), "resistor.a": (300, 140), "resistor.b": (380, 140)}


def curve_value(x, reflected, shift):
    """The one admitted expression is f(sign*(x-h)) with f(t)=t*t; never eval caller code."""
    return ((-1 if reflected else 1) * (x - shift)) ** 2


def curve_equation(reflected, shift):
    """Parentheses preserve input reflection inside the square operator."""
    inner = "x" if shift == 0 else f"x {'-' if shift > 0 else '+'} {abs(shift):g}"
    if reflected:
        inner = "-x" if shift == 0 else f"-({inner})"
    return "y = " + ("x" if inner == "x" else f"({inner})") + "^2"


def geometry_gate(scene):
    """Verify actual numeric vertices, nondegenerate perpendicular edges and3-4-5 lengths."""
    if set(scene.points) != {"A", "B", "C"}:
        raise ValueError("Triangle requires exactly A,B,C")
    a, b, c = (scene.points[k] for k in "ABC")
    ab, bc = (b[0] - a[0], b[1] - a[1]), (c[0] - b[0], c[1] - b[1])
    lengths = [math.dist(a, b), math.dist(b, c), math.dist(a, c)]
    if abs(sum(x * y for x, y in zip(ab, bc))) > 1e-6 or any(abs(x - y) > 1e-6 for x, y in zip(lengths, [4, 3, 5])):
        raise ValueError("Actual triangle violates perpendicular3-4-5 geometry")
    if scene.points != {"A": (0, 0), "B": (4, 0), "C": (4, 3)} or scene.equation != "3^2 + 4^2 = 5^2":
        raise ValueError("Triangle coordinates or displayed equation differ from the bounded lesson")
    return {"status": "passed", "lengths": lengths, "dot_product": sum(x * y for x, y in zip(ab, bc))}


def curve_gate(scene):
    """Check every provided numeric sample and the displayed reflected-square equation."""
    if scene.shift != 0 or not scene.input_reflection or scene.equation != curve_equation(True, 0):
        raise ValueError("Initial curve must display y = (-x)^2 with input reflection inside parentheses")
    for i, (x, y) in enumerate(scene.samples):
        if abs(x - (-2 + i / 8)) > 1e-6 or abs(y - curve_value(x, True, 0)) > 1e-6:
            raise ValueError("Actual curve samples do not match the reflected square rule")
    return {"status": "passed", "samples": [list(p) for p in scene.samples], "expression": "f(sign*(x-h))"}


def circuit_gate(scene):
    """Require exact unique components, real terminals and one degree-two connected cycle."""
    if sorted(scene.components) != ["battery", "resistor"] or scene.terminals != TERMINALS:
        raise ValueError("Circuit has missing/duplicate components or incorrect terminal positions")
    expected = {frozenset(("battery.p", "resistor.a")), frozenset(("resistor.b", "battery.n"))}
    if len({frozenset(w) for w in scene.wires}) != 2 or {frozenset(w) for w in scene.wires} != expected:
        raise ValueError("Circuit must contain the two exact unique series wire terminal pairs")
    edges = [*scene.wires, ("battery.p", "battery.n"), ("resistor.a", "resistor.b")]
    adjacency = {key: [] for key in TERMINALS}
    for a, b in edges:
        adjacency[a].append(b)
        adjacency[b].append(a)
    reached, pending = set(), ["battery.p"]
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending.extend(adjacency[node])
    if len(reached) != 4 or any(len(v) != 2 for v in adjacency.values()) or scene.equation != "ONE SERIES LOOP":
        raise ValueError("Circuit graph is not the required single closed series cycle")
    return {"status": "passed", "terminal_degree": {k: len(v) for k, v in adjacency.items()}, "cycles": 1}


def caption_lines(text):
    """Bound actual cell geometry without editing the preserved transcript."""
    value = display_text(text)
    lines = textwrap.wrap(value, width=38, break_long_words=False, break_on_hyphens=False)
    if not lines or len(lines) > 2 or any(len(line) > 38 for line in lines):
        raise ValueError("Caption exceeds two lines or38 authored glyph cells per line")
    return lines


def source_gate(spec, audio):
    """Admit every required scene and caption; missing/failed/skipped domains cannot pass."""
    scenes, captions = spec.storyboard.scenes, spec.script.captions
    if [s.id for s in scenes] != IDS or [c.scene_id for c in captions] != IDS:
        raise ValueError("Lesson requires all three scenes/captions in exact storyboard order")
    if audio["frames"] != 288000 or audio["duration_seconds"] != 6:
        raise ValueError("Lesson requires exactly288000 measured48kHz mono PCM16 samples")
    if spec.script.transcript != " ".join(c.text for c in captions):
        raise ValueError("Preserved transcript must equal the exact caption texts joined by one space")
    display_text(spec.title)
    gates = {"geometry": geometry_gate(scenes[0]), "curve": curve_gate(scenes[1]), "circuit": circuit_gate(scenes[2])}
    for i, (scene, caption) in enumerate(zip(scenes, captions)):
        if (scene.start_seconds, scene.end_seconds) != (i * 2, (i + 1) * 2):
            raise ValueError("Every scene must cover its exact two-second storyboard interval")
        if (caption.start_seconds, caption.end_seconds) != (scene.start_seconds, scene.end_seconds):
            raise ValueError("Caption is overlapping, outside audio or does not cover its exact scene")
        caption_lines(caption.text)
    gates["captions"] = {"status": "passed", "box": CAPTION_BOX, "diagram_box": DIAGRAM_BOX,
                          "spatial_overlap": False, "timing_basis": "caller_declared_within_measured_audio", "speech_alignment_verified": False}
    return {"status": "passed", "gates": gates, "source_authority": "caller_assertion_unverified",
            "display_transform": "ASCII lowercase to authored uppercase cells; original transcript preserved"}


def primitives(scene):
    """Derive visible paths from the same vertices, samples and terminals that were checked."""
    if scene.kind == "geometry":
        p = {key: [80 + 60 * x, 240 - 60 * y] for key, (x, y) in scene.points.items()}
        return [{"kind": "line", "points": [p["A"], p["B"], p["C"], p["A"]]},
                {"kind": "line", "points": [[308, 240], [308, 228], [320, 228]]}]
    if scene.kind == "curve":
        return [{"kind": "line", "points": [[160, 240], [480, 240]]},
                {"kind": "line", "points": [[320, 80], [320, 240]]},
                {"kind": "curve", "points": [[320 + 80 * x, 240 - 40 * y] for x, y in scene.samples]}]
    t = {key: list(value) for key, value in scene.terminals.items()}
    return [{"kind": "line", "points": [t["battery.p"], t["resistor.a"]]},
            {"kind": "line", "points": [t["resistor.b"], [460, 140], [460, 220], t["battery.n"]]},
            {"kind": "line", "points": [t["battery.p"], [160, 172]]},
            {"kind": "line", "points": [[140, 172], [180, 172]]},
            {"kind": "line", "points": [[150, 190], [170, 190]]},
            {"kind": "line", "points": [[160, 190], t["battery.n"]]},
            {"kind": "line", "points": [t["resistor.a"], [310, 140], [310, 130], [370, 130], [370, 150], [310, 150], [310, 140]]},
            {"kind": "line", "points": [[370, 140], t["resistor.b"]]}]
