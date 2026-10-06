---
name: movie-commentary
description: Turn one fixed local movie into a source-linked narrated commentary cut through a durable project, a validated plan, immutable frozen shards, explicitly approved per-shard host execution and verified full-cut delivery. Use for movie or long-video commentary projects, resuming them, or diagnosing why delivery is refused.
---

# Movie commentary

The video-explainer server provides seven `commentary_*` tools. They prepare projects, check plans, freeze
shards, record approvals, assemble the cut and validate delivery. They never write narration, interpret
the film or render a shard, and no tool spawns an agent. The full contract is in
[movie-commentary.md](../video-research-resources/docs/integrations/movie-commentary.md)
in the installed support tree (`docs/integrations/movie-commentary.md` in the source package).

## Route by state

Call `commentary_inspect` first and follow `recommended_stage`.

| Stage | Action |
|---|---|
| no project | `commentary_prepare` with the movie path and its exact SHA256 |
| `analyze_source` | write watch notes under `plan/watch_notes/*.md` from evidence you actually observed |
| `author_plan` | write `plan/editing_plan.json` and `plan/narration_script.md`, run `commentary_validate_plan` until it is valid, then `commentary_freeze_shards` |
| `approve_execute_or_assemble` | get explicit approval for each shard, then execute exactly that scope |
| all shards reported | `commentary_assemble`, then `commentary_validate_delivery` |
| `blocked_source_changed` | stop; the project is bound to bytes that changed, so start a new project |

## Plan

`editing_plan.json` has schema `vrm/movie-commentary-plan/v1` and the project's `source_sha256`.
Its `segments` are numbered `SEG_0001` onward. Each segment has:

- `narration.text`, repeated verbatim with its ID in the narration script;
- `visual_plan.rough_interval_sec`, which must lie within `source_cut_max_sec`;
- `visual_plan.movie_locator.evidence_refs`, existing files under `plan/watch_notes/` only;
- `audio_plan.source_audio_mode`: `ducked_bed` or `muted`;
- `audio_plan.bgm_mode`: `none`, or `licensed` only when the execution facts name a BGM manifest.

## Approval and execution

1. Run a shard only after an explicit approval from the person or authority responsible for the source media.
2. Pass that approval to `commentary_approve_shard` with the exact shard and source SHA256.
3. Record the caller's media authority and the exact execution scope. Existing explicit
   approval persists for those frozen bytes; changed source or scope requires a new approval.
4. Execute only the returned scope: the shard manifest, the execution facts and the source. Do not change
   narration, segment order or creative intent.
5. Write `<shard_id>.mp4` and `exec_report.json` at the returned paths.
6. Measured failures stay failures. An unresolved segment or a failed QA check blocks delivery.

## Delivery

`commentary_assemble` concatenates the approved shard MP4s with the pinned ffmpeg, fully decodes the cut and
compares its duration with the summed shard durations. `commentary_validate_delivery` refuses delivery
when any of these is missing or changed:

- the source, plan, script, evidence or execution facts;
- a frozen shard, an approval or a report;
- a shard MP4, the final MP4 or the final QA.

A blocked project is better than a false pass.
