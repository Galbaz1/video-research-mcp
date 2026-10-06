# Storyboard timing

`explainer_timing(project_id, request)` inspects or repairs a managed, approved project using its existing bound script and accepted full narration receipt. It invokes no provider or aligner. The source companion server mounts this route; the current private installed journey still requires qualification.

```json
{"action": "inspect"}
```

```json
{"action": "repair", "expected_revision": 0}
```

Repair requires the revision returned by inspection (zero before the first manifest). Unknown parameters and write requests without an exact revision are refused. Errors use the companion server's structured tool-error contract.

The input project needs `config.json` with `paths.storyboard` equal to `storyboard/storyboard.json`, an approved plan, a bound script, a complete accepted narration receipt and an existing bound storyboard. Scene IDs and order must match. Caller scene types and visual props are retained. A new script/narration may invalidate the previous storyboard binding; subsequent repair accepts only the exact previously timed board bytes or an explicitly rebound board.

Timing uses narration sentence sample boundaries, measured PCM16 mono sample counts and the existing word validation helper. Sample intervals partition the complete narration including pauses. Word events retain their declared source method. Provider-declared timestamps remain semantically unverified; synthetic events and caller-authored fixtures do not establish speech. Missing alignment returns `missing_alignment`, leaves word/animation lists empty and still permits measured scene-duration repair when scene boundaries exist. Multi-scene custom audio without scene sample boundaries returns `missing_scene_timing` and removes the storyboard binding. No scene or word timing is inferred from text length.

The production clock is the existing 30 fps contract. Cumulative sample boundaries are rounded upward to video frames. Each scene receives the difference between adjacent cumulative boundaries, so rounding does not accumulate independently across scenes. A scene shorter than a frame after cumulative quantization is refused. The existing one-frame (1/30 second) duration tolerance is retained. Word animation `from`/`to` values are half-open local video-frame intervals in `scene.props.timing.animations`; a late subframe word is clamped to the final available frame while its original sample interval remains intact. Video-frame intervals are an approximation and may overlap; they do not claim word-level caption precision beyond the supplied source events. The caller's scene component must consume these props to animate them. These values alone do not prove visible animation behavior.

Repair creates immutable content-bound PCM clips in `.timing/audio/` and an atomically replaced `.timing/manifest.json`. The manifest and storyboard are each bounded to 1 MiB, at most 64 scenes and 4096 words/sentence rows. Audio uses the existing stable regular-file readback and 64 MiB source limit. The production duration ceiling remains 1800 seconds. The manifest records exact plan/source/script/narration/audio/storyboard identities, the timing revision, original sample clock and `render_verification: UNRUN`.

A source change makes inspection stale. Explicit repair updates affected local timing/audio only, preserving unchanged clips and visual scene entries. `shifted_scenes` distinguishes changed global offsets from changed local sources. Retired clips are retained; there is no implicit pruning of caller assets. Repeated repair may accumulate old clips, even though each admitted source and manifest is bounded.

The project plan's existing SQLite transaction serializes repair and its revision check. Storyboard publication, its binding and manifest publication are separate durable stages. An interrupted stage can leave an unbound new board or old manifest; readback and the render guard refuse this state. This is fail-closed recovery, not a multi-file atomic transaction. Artifacts are retained for inspection; a new explicit repair can recover after the caller rebinds an interrupted board.

## Render integration

The companion server mounts `video_explainer_mcp.tools.timing.timing_server` and exposes `explainer_timing`.

`planning_production.freeze_render_source` calls `storyboard_timing.require_current_timing(project, state)` under the existing `plan_transaction`, after the storyboard binding check and before the project revision snapshot. The worker repeats that guard under the plan transaction before native dispatch. A project without a timing manifest retains its existing render behavior; a timing-managed project must have a current manifest and all exact audio/board identities.

After the existing authored-storyboard native qualification completes, the worker calls `storyboard_timing.verify_render_timing(project, state, request, qualification)` with the qualification containing `media.duration_seconds` and retains the timing result. The hook checks the frozen request's board identity/frame count and measured rendered duration against the accepted narration. It launches no probe and establishes no qualification by itself.

The shared hooks are integrated and covered by source tests, including stale narration and measured output-duration boundaries. Installed/native acceptance remains open until the complete current candidate journey is executed and reviewed.

## Source-only validation

The focused tests use real temporary SQLite/source bindings, bounded authored PCM bytes, dummy sample/word receipts and mocked filesystem interruption. They cover the four original criteria, selective repair and global shifts, restart/CAS, source and clip/board/manifest corruption, missing alignment, unsupported scene boundaries and qualified-output tolerance using a mocked qualification. They execute no renderer, model, provider, native media binary or target server.

The implementation was independently authored against project helpers. No upstream source, runtime, prompts or assets were copied/imported and no HTTP source reads were made. The proposed upstream source license remains UNRESOLVED. Local code remains governed by the repository MIT license; existing helper notices remain intact.
