# Qualification: renderer, education and spatial follow-ups

**Owner and dates.** Assignment VRM-QUAL-RENDER/r2, dated 2026-10-03. It continues r1, which was
interrupted after its primary diagnostics. The lane ran with zero children.

**Checkout.** `codex/programme-goal-command` at `8166be5b3e3c9ceb268b7a987c220550653f0602`.

**Scope.** Diagnosis and qualification only. The lane made no Beads or Git mutations, no
installs, downloads or runtime activations, no provider calls and no renders. It did not change
the evaluator or any denominator, and it did not create a third cohort or profile. All three
parents remain **blocked**.

Private receipts are stored under
`~/.local/state/video-research-mcp/capability-programme/2026-09-30/open-task-execution-2026-10-03/render/<bead>/`.

| Bead (validates) | Result | Receipt SHA256 (the receipt binds its report's SHA256) |
|---|---|---|
| `vrm-0e8.8.19` (`.8.9`) | COMPLETE_WITH_RETAINED_BLOCKERS | `ee30a0a5c87f11ad79380f0f10721cd59227aa5ffdb8204338629d1bfedd20c0` |
| `vrm-0e8.8.20` (`.8.7`) | COMPLETE_WITH_RETAINED_BLOCKERS | `777f65191d45b4c56d6c5544a0835f40a2f4b0a7090316d3757b431a9933823b` |
| `vrm-0e8.9.10` (`.9.3`) | COMPLETE_WITH_RETAINED_BLOCKERS | `3f40176b1c706d6b86acf33f32cc6784260929d9ec40bbabe0be7c70d73acdd2` |

These are the lane's original return labels. The coordinator does not treat them
as acceptance: `.8.20` still lacks the required rights-cleared speech references.
The original `.9.10` packet lacked a complete permitted replacement or exact grants.
The subsequent [spatial replacement design](spatial-replacement.md) supplies a
caller map and an exact, granted source-default DejaVu Sans asset. It establishes
preparation eligibility; implementation, parity and native acceptance remain unrun.
The renderer plan repair below addresses independent review findings; the original
private report and its incomplete plan remain retained.

## Renderer (`vrm-0e8.8.19`)

**Observed.** The upstream pin `c033e28` has no LICENSE, COPYING or NOTICE file among its 269
files, although `README.md:353` cites a LICENSE file. A read-only GitHub lookup (a source lookup,
not a qualification) found no license on the repository and no commit that ever added a LICENSE.
The pin is also the current default-branch head. The local Remotion environment is incomplete:

- `remotion/node_modules` and the headless-shell browser 123.0.6312.86 are absent.
- `EXPLAINER_PATH` is unset.
- Node is v26.9.0, and its compatibility with Remotion 4.0.242 is unknown.

The lockfile declares `@remotion/transitions` as `UNLICENSED`. The compositor package and
`webgl-constants` declare no license, and seven packages use the custom Remotion License. That
license is free only for individuals, for-profits with at most three employees, nonprofits and
evaluation.

The render script has two further runtime dependencies. `remotion/src/Root.tsx:2-5,13-16` loads
four Google fonts at module scope; that this fetches them over the network is inferred, not
verified. `render.mjs` sets no `browserExecutable`, so the system browser caches are not used.
The static render import path does not load the upstream venv's AGPL `pymupdf` or LGPL `edge-tts`.

**Blockers.**

- B1: an applicable upstream rights-holder grant; an operator's approval cannot
  supply the missing foreign-source grant.
- B2: Remotion eligibility for the user or organization (a human decision).
- B3: package-body grants.
- B4: module install authority.
- B5: browser download authority.
- B6: Node 26 compatibility.
- B7: font egress.
- B8: configuration.

**Plan.** A frozen one-scene, 30-frame, 1280×720 first-party fixture is defined: a frame-pure
`SolidCard` with an authored 1 s WAV. It runs through the existing `render PROJECT -r 720p`
adapter to `output/final-720p.mp4` in an isolated copy. Its assertions cover:

- freshness of the output;
- H.264 codec and dimensions;
- 30 frames, a duration of 1.000 s ± 1/30 s, and a full decode;
- that the recorded hash is not a golden hash;
- the negative controls.

The plan is not executed. The fixed10 component receipt `93363dc0…`, which passed as component
evidence only, stays separate. The repaired prospective plan is specified in
[renderer-plan.md](renderer-plan.md); it makes playback mandatory and binds the
30-frame duration to the actual composition metadata and duration helper.

## Education (`vrm-0e8.8.20`)

**Observed.** Two source constraints block a real spoken lesson:

- The source gate fixes the audio at 288,000 samples and each scene/caption to an exact 2 s
  window (`education_domain.py:91-101`). Timing is therefore caller-declared, and
  `speech_alignment_verified` is always false, so actual narration durations cannot drive the
  lesson.
- Glyphs are English ASCII only (`education_glyphs.py:1`).

The lesson video is H.264 High 4:4:4 Predictive (profile_idc 244) RGB with ALAC audio, and the
page contains no `<video>` element. Browser MP4 playback was never exercised; that browsers cannot
decode this format is inferred.

The selected Qwen/MiniMax narration routes are disabled and their keys are absent.
An ElevenLabs key name was observed, but its foreign CLI route remains blocked on
the missing upstream grant; key presence does not qualify narration. Both attempts are preserved:

- `8e6a62a7…`: 1 passed, 1 failed (E02), 15 unrun.
- `daab658e…`: 17/17 passed, with synthetic tones.

**Proposed supplemental controls.** These do not replace the original 17-control cohort.

- **S-EDU-1:** a measured-duration timeline built from rights-cleared per-caption speech, verified
  by ASR (`vrm-0e8.4.1`) or a human audit.
- **S-EDU-2:** a declared second language, rendered with project-authored glyphs. CJK remains
  blocked until a per-file font grant exists.
- **S-EDU-3:** an H.264 High yuv420p + AAC-LC delivery derivative of the lossless master, with
  actual browser `<video>` playback.

## Spatial (`vrm-0e8.9.10`)

**Observed.** The opencv-python-headless 4.13.0.92 macOS arm64 wheel bundles a `libavutil` whose
configuration starts with `--prefix=/opt/homebrew/Cellar/ffmpeg/7.1.1_3 … --enable-gpl
--enable-version3`. The library reports GPL v3 or later, which contradicts the LGPL-2.1 notice in
the wheel. The cause is supported: Homebrew's GPL FFmpeg is bundled. The provenance of the other
dylibs is unknown.

The rebound font map covers 98 members:

- 38 TTF files and 14 core-14 AFM files are granted.
- 5 Computer Modern AFM files are candidates whose AMS correspondence is unattested.
- 41 legacy Adobe AFM files lack an applicable grant. By fontname they are the 35 standard
  PostScript fonts, 2 Helvetica Light and 4 Utopia; this grouping is inferred.

The original 12-wheel and narrow 10-wheel profiles remain rejected. All 28 frozen controls are
still unrun, and the 19 actual tools and 16 mandatory tools are preserved.

**Original routes and gaps.**

- **R1:** an authoritative grant covering the exact AFM bytes, plus a CM attestation.
- **R2:** a replacement payload, as a candidate only. It needs a caller-import map of the 19
  tools, which is missing, a new freeze, and coordinator authority.
- **R3:** keep OpenCV excluded.

**Subsequent static diagnosis.** The original packet proposed these two checks:

1. A stdlib enumeration of the wheel's `.dylibs/*`.
2. A static caller-import map of the spatial tools.

Both were subsequently inspected statically in the
[replacement design](spatial-replacement.md): 93 dylib entries and eight causal
caller seams, comprising six raster and two motion boundaries. These observations
support a bounded replacement design. They provide no import, rendering, pixel
parity or geometry result; all 28 frozen native controls remain unrun.

## Retained failed or partial checks

- **Nested AGENTS files not read.** The `src/AGENTS.md` and `tests/AGENTS.md` read failed on a
  shell `=====` token error and was not rerun.
- **First renderer probe truncated.** Run 1 truncated the tree listing (114 entries instead of
  269). Its output `7c499dca…` was removed and the probe was corrected in place. The defect is
  recorded in the receipt.
- **Lookup not performed.** The AFM grant lookup did not happen: r1 was interrupted, and r2
  prohibits further lookups.
- **Handoff not fully read.** The canonical handoff was read only in its session-start preview.
- **Tests.** NOT_RUN, because no source changed.
