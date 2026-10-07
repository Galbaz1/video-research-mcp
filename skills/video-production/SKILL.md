---
name: video-production
description: Assemble multi-clip AI video projects with reference assets, continuity checks, frame and audio QA, and montage assembly. Use for complete video production, not video analysis or isolated provider settings.
---

# Video Production

Use a bounded production loop: brief → assets → draft → inspect → repair → assemble → verify. This skill supplies the workflow; discover actual generation, image, audio, and filesystem tools before execution. Read `video-generation` for current provider capabilities and `ffmpeg-production` for encoding recipes.

## 1. Brief and Assets

When the creative approach is open, use [creative-concept-design](../creative-concept-design/SKILL.md) to choose a treatment and inspect a narration audition and representative animatic before full production.

Record audience, message, shot list, duration, format, audio, delivery destination, and acceptance criteria. Audit existing footage and supplied images before generating replacements. Keep source assets unchanged. For paid generation, fix the spend limit, maximum attempts, and worker concurrency before starting.

Completion: each shot has a source or supported generation path, and each parallel worker owns a distinct output directory.

## 2. Visual Continuity

When multiple shots share a subject or setting, choose one inspected reference image per visual world. Store it with the prompt and a short identity/lighting descriptor. Use the selected provider's real reference mechanism; character/style consistency is a QA goal, not a promised connector parameter.

Choose one pattern, then read only its section in [workflow-patterns.md](references/workflow-patterns.md):

| Need | Pattern |
|---|---|
| Distinct scenes sharing assets | Animate and propagate |
| Continuous motion | Frame-forward chain |
| Compare moods or treatments | Parallel variants |
| Longer continuous take | Extension, if the provider supports the input |

Completion: references fit the selected input mode and required features are visible in the inspected assets.

## 3. Draft and Inspect

Generate one draft per shot within the agreed budget. For parallel shots, join all required workers before assembly. Retain operation IDs and poll pending jobs; do not duplicate a job because a client timed out.

Probe each returned video and inspect a contact sheet, playback, and audio. Check composition, identity, lighting, text, object permanence, motion, internal cuts, pronunciation, and sync. Sampling at 1 or 10 fps is a diagnostic aid; it does not prove every frame or audio sample is correct.

Completion: every shot has a recorded pass/fail decision and evidence against its acceptance criteria. A failed, refused, empty, or missing output remains part of the record.

## 4. Targeted Repair

For a measured defect, change one variable and allow one repair attempt per shot within the remaining budget. Preserve both outputs and explain the selection. Stop if the same infrastructure failure repeats, the provider refuses, or the budget is exhausted. Simplify the shot or deliver the accepted subset with explicit omissions; never imply a partial film is finished.

Completion: every retained shot passes, or the unresolved shot is named with its smallest next intervention.

## 5. Assemble and Verify

Normalize retained clips to compatible frame rate, dimensions, pixel format, timebase, and timestamps before concat/xfade. Use only necessary denoise/sharpen/grade operations; compare against the source so processing does not hide or introduce defects. Apply grain after denoise and interpolation if desired.

Measure actual durations to compute transition offsets. If clips carry audio, pair video overlap with the intended audio transition; silent clips or a separate soundtrack need a different mapping. See the reference for FFmpeg commands.

Probe the final file and watch/listen through every transition and the ending. Confirm duration, dimensions, fps, audio, readability, source attribution, and all required shots. Return the playable local path and inspection evidence. Keep `preview`, `verified local final`, and `published` distinct; publication requires the authorized destination.

Completion: the delivered artifact exists, is playable, and satisfies the recorded brief, or unresolved criteria are explicitly reported.

## Related Skills

- `image-generation`: reference prompts and edits.
- `video-generation`: current provider constraints and clip requests.
- `tts-production`: narration and alignment.
- `ffmpeg-production`: audio/video processing and export presets.
