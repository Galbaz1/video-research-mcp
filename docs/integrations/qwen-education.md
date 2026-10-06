# A bounded educational lesson component

For an installed Claude workflow, select an explicit Python interpreter with the
accepted core wheel installed and run `<skill directory>/scripts/lesson.py` with
`-I -B`. Read `importlib.metadata.version("video-research-mcp")` in that interpreter
and compare its normalized version with the selected installer manifest: for
example, `0.8.0rc3` corresponds to npm `0.8.0-rc.3`. Bind the accepted candidate
wheel receipt too: a matching version alone does not identify same-version
development bytes.
Even `--help` imports the core package. The `uv run --no-sync --locked` examples
below require the source checkout; unpacked npm supplies workflow/helper files,
not a Python environment.

The first-party `education` component produces one concrete lesson, **Verifying a
diagram against its rule**: a right 3-4-5 triangle, an input-reflected square and a
closed battery/resistor series loop. It validates a strict source/analysis/script/
storyboard ledger, creates a self-contained interactive page, composes a bounded
12 fps video with explicitly supplied WAV audio, and checks the complete decoded
output against source-derived geometry and glyphs. It has no public MCP tool,
provider call, foreign renderer or automatic installer.

Component checks do not establish a spoken teaching lesson, multilingual glyph
correctness, arbitrary mathematics or physics, learner understanding or human
acceptance. The programme's required actual narration and applicable multilingual
journeys remain unverified. Synthetic tones can exercise file/sample contracts;
they cannot fulfil spoken narration acceptance.

## Exact caller workflow

Use the installed package's skill CLI with a regular local JSON specification and
regular supplied WAVs. Capture the full source and audio hashes independently.
The source file is at most 128 KiB, and audio at most 8 MiB. No source path may use a
URI, symlink or traversal. The output directory must be absent and its regular
parent must already exist. Prior outputs are preserved and never overwritten.

```sh
# Retained schema1 caller: one exact six-second WAV.
uv run --no-sync --locked python skills/educational-explainer/scripts/lesson.py validate \
  --spec lesson.json --spec-sha256 EXPECTED_SPEC_SHA256 \
  --audio narration.wav --audio-sha256 EXPECTED_AUDIO_SHA256
uv run --no-sync --locked python skills/educational-explainer/scripts/lesson.py build \
  --spec lesson.json --spec-sha256 EXPECTED_SPEC_SHA256 \
  --audio narration.wav --audio-sha256 EXPECTED_AUDIO_SHA256 --output new-lesson
uv run --no-sync --locked python skills/educational-explainer/scripts/lesson.py check \
  new-lesson --receipt-sha256 EXTERNALLY_RETAINED_BUILD_RECEIPT_SHA256
```

For the measured route, use a **schema2** source containing the three segment
commitments described below. Omit the legacy `--audio`/`--audio-sha256` arguments:

```sh
uv run --no-sync --locked python skills/educational-explainer/scripts/lesson.py validate \
  --spec measured-lesson.json --spec-sha256 EXPECTED_SPEC_SHA256
uv run --no-sync --locked python skills/educational-explainer/scripts/lesson.py build \
  --spec measured-lesson.json --spec-sha256 EXPECTED_SPEC_SHA256 --output new-lesson
uv run --no-sync --locked python skills/educational-explainer/scripts/lesson.py check \
  new-lesson --receipt-sha256 EXTERNALLY_RETAINED_BUILD_RECEIPT_SHA256
```

`validate` performs complete local source/WAV admission without native execution.
`build` uses operator-installed FFmpeg/ffprobe and lazy optional Pillow raster
support. A missing image dependency names `video-research-mcp[images]`; no action
installs it. `check` repeats source and output checks after restart. Its expected
receipt hash must come from the retained build result, rather than being recomputed
from an editable local receipt. A hash commits exact bytes; it does not authenticate
the caller, source authority or a human review.

The async APIs retain `validate_lesson(spec_path, expected_spec_sha256, audio_path,
expected_audio_sha256, timeout_seconds=120)` and the original positional
`build_lesson(spec_path, expected_spec_sha256, audio_path, expected_audio_sha256,
output_directory, timeout_seconds=120)` schema1 journeys. Schema2 uses
`validate_lesson(spec_path, expected_spec_sha256, timeout_seconds=120)` and
`build_lesson(spec_path, expected_spec_sha256, output_directory=..., timeout_seconds=120)`.
`check_lesson(directory, expected_receipt_sha256, timeout_seconds=120)` handles both
receipt versions. Mixing schema2 with legacy audio arguments is refused.
Refusals raise concrete exceptions; the CLI returns failed
JSON and a nonzero exit. Native work is serialized under one caller deadline,
including lock waiting. Failed/cancelled builds retain a separate bounded
`.education-attempt-<UUID>.json` in the output parent and clean their exclusive
staging after workers/processes join. They do not retry or replace prior results.

## The admitted ledger

`LessonSpec` in the installed Python module `video_research_mcp.models.education` rejects extra fields,
nonfinite numbers, boolean numeric coordinates, unsupported domains and incomplete
populations. Protocol versions are exact integers. The retained **schema1**
required sections are:

- `source`: preserved `problem` and caller-asserted `authority` text.
- `analysis`: the exact triangle, square-input-reflection and single-cycle rules.
- `script`: exact `transcript`, plus three ordered captions with scene IDs, text,
  start and end. The transcript equals caption texts joined by one space.
- `storyboard`: exactly `triangle`, `curve`, `circuit` scenes in that order, each
  covering its declared two-second interval at 0..2, 2..4 and 4..6 seconds.

**Schema2** retains exactly the same title, source, analysis, numeric diagram
fields, transcript and three ordered caption texts. Remove `start_seconds` and
`end_seconds` from every scene and caption; declared times are refused in this
route. Add this required top-level field with independently captured full hashes:

```json
"narration_segments": [
  {"scene_id": "triangle", "path": "triangle.wav", "sha256": "FULL_SHA256"},
  {"scene_id": "curve", "path": "curve.wav", "sha256": "FULL_SHA256"},
  {"scene_id": "circuit", "path": "circuit.wav", "sha256": "FULL_SHA256"}
]
```

Paths may be absolute or relative to the source JSON's directory. All three must
be regular local complete 48 kHz mono PCM16 RIFF WAVs, in exact scene order. The
source hash binds their path/hash commitments; admission measures every supplied
sample and records separate original-WAV and PCM hashes. The WAV population is
at most 8 MiB, each segment is nonempty, and the combined PCM is at most 1,440,000
samples/30 seconds. The producer concatenates their PCM in order into a canonical
`narration.wav` and preserves each original WAV's exact bytes separately. It never
trims, pads, mixes, changes gain or resamples supplied PCM.

For measured counts N1,N2,N3, the scene and whole-caption boundaries are the
half-open sample intervals `[0,N1)`, `[N1,N1+N2)`, `[N1+N2,N1+N2+N3)`. These are
file boundaries, without inferred word timing or a speech/text alignment claim.
The page uses these integer sample clocks for scene selection, scene-button seek,
sample-by-sample seek and reset; audio seconds are converted to sample position.
At the exact total duration it keeps the final scene visible.

Video samples the scene at each frame's start sample, `frame_index * 4000`.
Transitions therefore round up to the next 12 fps frame, with an explicit
`visual_delay_samples` of 0..3999. The frame count is `ceil(total_samples/4000)`;
the last frame may extend by 0..3999 samples beyond the exact audio end. The
receipt records this `video_tail_samples` separately from narration duration.
Audio ends at its exact measured sample count. Every scene must cover at least
one scheduled video frame; a segment whose interval contains none is refused
instead of silently losing a scene. Scene lengths need not be integer seconds
or multiples of a frame, and no audio is changed to satisfy this visual grid.

Triangle vertices are `A=[0,0]`, `B=[4,0]`, `C=[4,3]`. Actual differences and distances
must establish perpendicular edges and lengths 4, 3, 5; coincident or changed points
fail. The displayed equation is exactly `3^2 + 4^2 = 5^2`, and the vertices map to
pixels `[80+60*x,240-60*y]`. Those actual numbers drive the displayed paths.

The initial curve is `y = (-x)^2`, with reflection enabled and shift 0. All 33 supplied
samples at x=-2..2 in steps of 0.125 must match the expression. They drive the visible
curve at `[320+80*x,240-40*y]`. Interactive states use the explicitly defined
`f(sign*(x-h))`, with f(t)=t*t, reflection on/off and h=-1,0,1. Parentheses keep
reflection inside the square. The fixed viewport is x=-2..2,y=0..4; changed curves
may clip. Current equation and the numeric values at x=-1,0,1 remain visible and
inspectable even when a curve extends outside that viewport.

The circuit requires unique `battery` and `resistor` components, exact terminals
`battery.p=[160,140]`, `battery.n=[160,220]`, `resistor.a=[300,140]`,
`resistor.b=[380,140]`, and wires connecting battery.p→resistor.a and
resistor.b→battery.n. Component/internal edges plus wires must form one connected
degree-two cycle. The rendered wire endpoints use those same terminal coordinates;
open, missing or duplicate components/wires fail. This checks the concrete idealized
diagram graph, without asserting electrical behavior of arbitrary real circuits.

## Text, interaction and supplied audio

An independently authored 5x7 ASCII uppercase/digit/operator cell set, under this
project's MIT license, supplies page/video equations, labels and captions. There
is no imported font, font file, KaTeX, GSAP or CDN. Lowercase ASCII is displayed as
uppercase cells while exact transcript/caption text remains in the committed
ledger and accessible DOM data. Unsupported glyphs, including CJK and accented
letters, fail explicitly. Captions have at most two lines of 38 cells, inside the
fixed pixel box `[24,282,616,342]`, separate from diagram box `[48,54,592,258]`.
Caption intervals must exactly cover their scenes, stay within measured audio and
avoid overlap. This binds declared timing and visible layout, not speech meaning.

`page.html` embeds its admitted WAV and source data. Scene buttons, seek/reset,
reflection and shift controls redraw from the current state. The visible equation,
position and numeric sample values have ARIA/data readback. Reset updates controls,
audio position and scene state together. Browser interaction acceptance remains a
separate actual journey; source text or unit mocks do not supply that acceptance.

Schema1 requires a supplied complete 48 kHz mono PCM16 RIFF WAV containing
exactly 288,000 samples/six seconds. Schema2 measures and assembles its three
supplied segments as described above. The producer creates no default voice, synthetic speech
or estimated alignment. Original bytes, PCM hashes and sample count are measured.
The caller's transcript and timing remain declared; `speech_semantics_verified`
and `caption_speech_alignment_verified` are always false here.

## Separate source and finished-output gates

Successful output contains `source.json`, `narration.wav`, `page.html`, `video.mp4`,
the complete scheduled `frame-NNN.png` population, `decoded.rgb`, `decoded.wav` and
`receipt.json`. The receipt binds full original source/audio revisions and each
encoded artifact, all source-to-scene/frame clock rows, source predicates,
finished measurements and selected native executable hashes. Source and encoded
video identities are bound before QA and rejoined after measurements/promotion.
Schema1 retains its 72 frames and version1 receipts. Schema2 adds
`segment-triangle.wav`, `segment-curve.wav`, `segment-circuit.wav`, exact segment
commitments and the measured sample/quantization timeline in version2 receipts.

The compositor selects lossless RGB H264 (`libx264rgb`, CRF 0) and lossless ALAC audio.
It applies no gain, resampling, default narration, external music or font assets.
Complete decoded video must be 640×360 at 12 fps, with exactly the admitted frame
count and clocks (72/six seconds for schema1, at most 360/30 seconds for schema2).
One complete education-specific ffprobe inspects every video/audio frame; the
shared footage 256-frame guard remains intact. Each actual
RGB frame is compared with source-derived shapes/glyphs/captions at zero tolerance.
Decoded audio must retain every supplied PCM sample exactly. Output is bounded to
8 MiB, authored PNGs to 8 MiB in aggregate, decoded RGB to 256 MiB, decoded WAV to
8 MiB, page to 8 MiB, source to 128 KiB, receipt to 128 KiB for schema1 or 512 KiB
for schema2, and native stdout/stderr to 1 MiB. The full 360-frame RGB population
is 248,832,000 bytes. Raw evidence extraction does not truncate at a frame cap;
extra and missing frames/samples are terminal refusals. Container duration
metadata may round to milliseconds; schema2 allows at most 1.001 ms deviation
from its quantized video end, while exact decoded PTS and PCM populations remain
required. Native output is a lossless master; browser codec delivery remains an
unfinished acceptance gate.
Large raw evidence goes to bounded owned files, not stdout.

The existing complete native review also requires successful full decode, no
detected black span, and finite terminal loudness within −24..−10 LUFS and true peak
at most −1.5 dBFS. These are technical observations, without standards certification,
spoken-content truth or perceptual synchrony claims. Actual operator-installed
FFmpeg/ffprobe bytes are observed and rehashed for every command. That observation
does not qualify their complete source/build/library grants or provide an OS sandbox.

Restart rereads the externally hash-bound receipt, exact originals, staged source/
audio (including all schema2 segments), actual page/PNG pixels, encoded video and
full raw evidence. It regenerates
source-derived expectations and repeats complete decode in separate owned scratch.
Missing or skipped applicable source gates, edited self-receipts, changed artifacts,
truncated populations and modified final diagram/caption pixels cannot confer
acceptance. Sources and prior committed outputs are never rewritten by checking.

## Upstream reference and unfinished workflows

Requirements were informed by
[QwenLM/Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f),
revision `07736672525443c7f8a3f6405eed37d2236f023f`, under the complete
[Apache-2.0 grant](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/LICENSE).
The joined gate read 22 full bodies, 684,766 bytes/11,702 lines, with 47 exact artifact
bindings. Its 20 original static findings and cap-extension history remain retained.
Thirty-nine direct helper bodies remain unread; foreign execution is unqualified.
This component imports or copies no foreign renderer, script, template, font or asset.

All 12 upstream templates remain **unexecuted/unqualified**: Problem Display Card,
Formula Derivation Panel, Geometry Canvas, Step Indicator, Conclusion Panel,
Flame Color Display, Title Opening, Experiment Equipment Cards, Operation Flow
Panel, Comparison Panel, Science Principle Diagram and Circuit Wiring Operation
Panel. Independent checks for this three-domain lesson do not complete those
templates. HyperFrames production, GSAP/KaTeX/font packaging, foreign validators,
provider narration, multilingual teaching, actual spoken lesson semantics,
biological/other scientific process animations, learner/human and comparative
acceptance also remain separate unfinished workflows.
