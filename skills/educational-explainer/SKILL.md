---
name: educational-explainer
description: Produce and restart-check the bounded first-party Verifying a diagram against its rule lesson as a self-contained interactive page and local video with an exact supplied WAV. Use source/analysis/script/storyboard and complete decoded evidence; arbitrary domains and multilingual/foreign templates remain outside this component.
---

# Verify a diagram against its rule

Read the [component contract](../../docs/integrations/qwen-education.md) before
authoring the required source/analysis/script/storyboard ledger. This skill uses
the installed first-party [lesson CLI](scripts/lesson.py), with no public MCP tool,
foreign renderer, provider generation, font package or automatic installer.

The admitted lesson has three scenes: right 3-4-5 triangle, input-reflected square
and one battery/resistor series cycle. Bind exact source JSON and supplied regular
48kHz mono PCM16 WAV with independent full SHA-256 values. Preserve the exact
transcript. Schema1 retains caller-declared two-second intervals and its exact
six-second WAV. Schema2 requires three ordered hash-bound `narration_segments`
(`triangle`, `curve`, `circuit`) and omits declared scene/caption times. Its
measured sample counts set all whole-scene caption and page boundaries; combined
duration is at most30 seconds. No default voice or synthetic
audio is generated. Supplied tones can check the component's sample contracts;
they do not satisfy actual spoken lesson acceptance.

Run `lesson.py validate` with `--spec` and `--spec-sha256`. Schema1 also requires
`--audio` and `--audio-sha256`; omit both for schema2. Relative segment paths are
resolved beside the source JSON. It checks every required scene, numeric rule, supported glyph,
caption timing/layout and complete audio sample population without native execution.
Failed, missing or skipped applicable gates are refusals, never a source PASS.

Run `lesson.py build` with the same exact inputs and an absent `--output`
directory. The explicit workflow uses optional Pillow and operator-installed
FFmpeg/ffprobe; a missing dependency is reported rather than installed. It writes
the self-contained page, the complete admitted12fps frame population (72 for
schema1, at most360 for schema2), lossless local MP4, complete decoded
RGB/PCM evidence and a committed receipt. One deadline covers the operation.
Cancellation joins owned work and preserves inputs/prior artifacts. Retained
failed-attempt receipts do not authorize regeneration or overwrite.

Schema2 preserves all original WAV bytes and concatenates only their exact PCM.
Page scene/seek/reset controls use the measured sample boundaries. Video chooses
the scene at each frame's start sample; transitions and the video end may round
up by less than one frame. Inspect the recorded `visual_delay_samples` and
`video_tail_samples`; audio stays at its exact sample count. A scene with no
scheduled frame is refused. No word timing is estimated and supplied text/speech
alignment remains unverified. Version2 receipts are bounded to512KiB and full
decoded RGB to256MiB; schema1 receipts and caller artifacts remain supported.

Retain the returned receipt hash outside the mutable output directory. Inspect
the actual page's scene, seek/reset and reflection/shift controls, visible numeric
samples and parenthesized square equation. The fixed x=-2..2,y=0..4 viewport may
clip changed curves; numeric rules remain visible. Page/video text uses the same
authored ASCII uppercase cells, with exact source text preserved. CJK/unsupported
glyphs are explicit refusals.

Run `lesson.py check OUTPUT --receipt-sha256 RETAINED_SHA256` after restart.
Do not derive that expected hash from an edited self-receipt. Checking repeats
source predicates and complete decoded RGB/sample comparisons, including every
frame's source lineage, glyphs and captions. Read back the original and output
byte commitments and report separate source/finished-output states.

Keep spoken semantics, actual speech/caption alignment, physical/arbitrary-domain
correctness, human lesson acceptance and multilingual assets unverified. All 12
upstream templates, HyperFrames/GSAP/KaTeX/fonts, foreign validators, provider
narration and broader scientific animations remain unexecuted/unqualified. A
three-domain component receipt does not close those workflows or the broader leaf.
Native MP4 is a lossless master; browser codec delivery still requires a separate
qualified runtime journey.
