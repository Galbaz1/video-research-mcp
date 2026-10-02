---
name: footage-edit
description: Prepare and assemble short edits from exact local source footage using measured frame lineage, scene revision approvals, contact previews and final technical gates.
---

Use `media_edit_footage` for a bounded local linear edit. Keep the existing external companion renderer separate. Read [FOOTAGE_EDIT.md](../../docs/integrations/FOOTAGE_EDIT.md) for the public fields, limits and evidence boundaries.

Prepare a chosen brief and one to eight unique scenes from at most two regular local sources. Bind each complete source SHA256, half-open source interval, declared FPS and explicit contiguous timeline start. Select only the required bounded crop, neutral-default grade and source-audio preservation/attenuation or explicit mute. This route supports hard cuts and compatible source grids/audio formats; do not claim unsupported compositing, music, transitions, fonts, SFX or external render engines.

Choose `beats.mode: none` when no music grid is asserted, `declared` with BPM/origin and an explicit cut tolerance, or `offbeat` to disclose an intentional mismatch. A declared grid is not detected musical timing.

Call `action: prepare`. Inspect the exact returned scene PNGs/contact evidence and the full original-PTS timeline ledger in the scope authorized by the caller. `prepared` means scene evidence exists; it does not mean a final was delivered. Preserve complete artifact and prepared-manifest hashes when communicating scene decisions.

For assembly, use the exact prepared manifest path/SHA and one approval per scene: `scene_id`, full `scene_sha256`, `prepared_manifest_sha256` equal to that prepared revision, and `locked: true`. Use approval assertions supported by the current caller's intent and inspection; label their actual source. These integrity commitments do not authenticate the caller or establish human visual acceptance. Changes to the brief, source, treatment, timing or prepared evidence require approval of the new revision.

Call `action: assemble` only with the complete assertions. Report delivery only when the returned status is `delivered`; black spans, missing audio, failed full decode, clock/population mismatch, undefined measurements or failed hard loudness/peak bounds are terminal refusals. No automatic fallback or rerender retry is implied. Existing prepared/prior views survive final refusal or cancellation.

Finish with `image_manifest_read` using the exact returned manifest path/SHA. This rechecks original and actual artifact bytes after restart without rerendering. Native preview inclusion and text-only metadata refer to the same artifacts. Distinguish technical delivery, source integrity and the actual scope of visual/semantic/human review. Do not infer model/provider/native-isolation or standards qualification from ready/success status.
