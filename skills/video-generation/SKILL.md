---
name: video-generation
description: Generate AI video clips with an available provider, including image-to-video, reference assets, or extensions. Use for generation requests, not video analysis or FFmpeg editing.
---

# Video Generation

This plugin packages production guidance; it does not bundle a Veo MCP server or a video-generation script. Discover the connected provider and read its current tool schema before calling it. If none is available, preserve a generation-ready brief and identify the missing provider.

## Workflow

1. **Fix the brief.** Record subject, motion, camera, duration, aspect ratio, audio, destination, and supplied assets. Use an anchor image when continuity matters; text-only generation is also supported where the provider permits it. Completion: one bounded shot specification with explicit acceptance criteria.
2. **Verify capability.** Read [provider-details.md](references/provider-details.md) for the current provider snapshot, then check live model availability, input constraints, pricing, and the actual tool/API schema. Do not translate a provider feature into an invented MCP tool name. Completion: a supported request and an authorized spend/attempt limit.
3. **Generate one draft.** Keep its prompt, model, settings, reference paths, operation ID, and output together. A running operation is pending; poll that operation rather than launching a duplicate. Completion: terminal result or preserved provider failure.
4. **Inspect the artifact.** Download the successful output, probe duration/resolution/audio with `ffprobe`, inspect a contact sheet and motion playback. Check subject identity, object integrity, timing, and audio against the brief. Completion: evidence for every acceptance criterion, including failures.
5. **Repair only a measured defect.** Change one variable, retain the earlier output, and use at most one repair attempt within the existing budget. Stop on a repeated infrastructure failure, exhausted budget, or terminal refusal. Completion: an accepted local clip or a precise unresolved defect.

For an approved draft, generate a final only if the requested delivery settings require it. Re-check the final artifact; a winning draft does not prove the final has the same quality. For multi-shot continuity and assembly, use `video-production`; for encoding use `ffmpeg-production`.

## Prompt Template

> [Subject and setting]. [One primary action over the requested duration]. Camera [movement and framing]. Light comes from [physical source]. Maintain [specific reference features]. Audio: [dialogue, ambience, or intended silence]. Deliver [aspect ratio and supported resolution].

Include exact spoken words when dialogue matters. Preserve the user's exclusions using a supported negative-prompt field or clear instructions. Reference images guide appearance; they do not guarantee identity or text fidelity.

## Delivery

Return the playable clip path, inspected properties, provider/model, reference provenance, and remaining defects. Distinguish `prepared`, `pending`, `failed`, and `verified local output`. Publication requires the user's destination authority.
