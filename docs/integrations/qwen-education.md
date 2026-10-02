# A bounded educational lesson component

The first-party `education` component produces one concrete lesson, **Verifying a
diagram against its rule**: a right 3-4-5 triangle, an input-reflected square and a
closed battery/resistor series loop. It validates a strict source/analysis/script/
storyboard ledger, creates a self-contained interactive page, composes 72 local
video frames with an explicitly supplied WAV, and checks the complete decoded
output against source-derived geometry and glyphs. It has no public MCP tool,
provider call, foreign renderer or automatic installer.

Component checks do not establish a spoken teaching lesson, multilingual glyph
correctness, arbitrary mathematics or physics, learner understanding or human
acceptance. The programme's required actual narration and applicable multilingual
journeys remain unverified. Synthetic tones can exercise file/sample contracts;
they cannot fulfil spoken narration acceptance.

## Exact caller workflow

Use the installed package's skill CLI with a regular local JSON specification and
a regular supplied WAV. Capture the full source and audio hashes independently.
The source file is at most 128 KiB, and audio at most 8 MiB. No source path may use a
URI, symlink or traversal. The output directory must be absent and its regular
parent must already exist. Prior outputs are preserved and never overwritten.

```sh
uv run --no-sync --locked python skills/educational-explainer/scripts/lesson.py validate \
  --spec lesson.json --spec-sha256 EXPECTED_SPEC_SHA256 \
  --audio narration.wav --audio-sha256 EXPECTED_AUDIO_SHA256
uv run --no-sync --locked python skills/educational-explainer/scripts/lesson.py build \
  --spec lesson.json --spec-sha256 EXPECTED_SPEC_SHA256 \
  --audio narration.wav --audio-sha256 EXPECTED_AUDIO_SHA256 --output new-lesson
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

The async APIs are `validate_lesson(spec_path, expected_spec_sha256, audio_path,
expected_audio_sha256, timeout_seconds=120)`, `build_lesson` with the same arguments
plus `output_directory`, and `check_lesson(directory, expected_receipt_sha256,
timeout_seconds=120)`. Refusals raise concrete exceptions; the CLI returns failed
JSON and a nonzero exit. Native work is serialized under one caller deadline,
including lock waiting. Failed/cancelled builds retain a separate bounded
`.education-attempt-<UUID>.json` in the output parent and clean their exclusive
staging after workers/processes join. They do not retry or replace prior results.

## The admitted ledger

[LessonSpec](../../src/video_research_mcp/models/education.py) rejects extra fields,
nonfinite numbers, boolean numeric coordinates, unsupported domains and incomplete
populations. Protocol version is the exact integer 1. Required sections are:

- `source`: preserved `problem` and caller-asserted `authority` text.
- `analysis`: the exact triangle, square-input-reflection and single-cycle rules.
- `script`: exact `transcript`, plus three ordered captions with scene IDs, text,
  start and end. The transcript equals caption texts joined by one space.
- `storyboard`: exactly `triangle`, `curve`, `circuit` scenes in that order, each
  covering its declared two-second interval at 0..2, 2..4 and 4..6 seconds.

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

The producer requires a supplied complete 48 kHz mono PCM16 RIFF WAV containing
exactly 288,000 samples/six seconds. It creates no default voice, synthetic speech
or estimated alignment. Original bytes, PCM hashes and sample count are measured.
The caller's transcript and timing remain declared; `speech_semantics_verified`
and `caption_speech_alignment_verified` are always false here.

## Separate source and finished-output gates

Successful output contains `source.json`, `narration.wav`, `page.html`, `video.mp4`,
`frame-000.png` through `frame-071.png`, `decoded.rgb`, `decoded.wav` and
`receipt.json`. The receipt binds full original source/audio revisions and each
encoded artifact, all 72 source-to-scene/frame clock rows, source predicates,
finished measurements and selected native executable hashes. Source and encoded
video identities are bound before QA and rejoined after measurements/promotion.

The compositor selects lossless RGB H264 (`libx264rgb`, CRF 0) and lossless ALAC audio.
It applies no gain, resampling, default narration, external music or font assets.
Complete decoded video must be 640×360 at 12 fps, 72 frames and six seconds. Each actual
RGB frame is compared with source-derived shapes/glyphs/captions at zero tolerance.
Decoded audio must retain every supplied PCM sample exactly. Output is bounded to
8MiB, decoded RGB to 64 MiB, receipt to 128 KiB, and native stdout/stderr to 1 MiB.
Large raw evidence goes to bounded owned files, not stdout.

The existing complete native review also requires successful full decode, no
detected black span, and finite terminal loudness within −24..−10 LUFS and true peak
at most −1.5 dBFS. These are technical observations, without standards certification,
spoken-content truth or perceptual synchrony claims. Actual operator-installed
FFmpeg/ffprobe bytes are observed and rehashed for every command. That observation
does not qualify their complete source/build/library grants or provide an OS sandbox.

Restart rereads the externally hash-bound receipt, exact originals, staged source/
audio, actual page/PNG pixels, encoded video and full raw evidence. It regenerates
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
