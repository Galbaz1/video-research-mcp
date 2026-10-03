---
name: av-events
description: Caption, count or ground supported occurrences in exact local audio/video, or inspect timed musical sections with measured submitted evidence. Use the root AV tools and keep inferred semantics distinct from decoded clocks and physical truth.
---

# AV event and music evidence

## Installed workflow resources

For a Claude installer layout, use the adjacent managed support directory
`../video-research-resources/` and its `../video-research-resources/docs/integrations/AV_EVENTS.md`.
The `../video-research-resources/integrations/qwen/av-events.json` descriptor records the selected component and requirements.
The repository-relative references below apply when using a source checkout or unpacked npm package. Installing resources does not activate optional runtimes, providers or external source components.

Use the root tools `media_caption_events`, `media_count_events`,
`media_ground_events` and `media_analyze_music`. Read the
[integration contract](../../docs/integrations/AV_EVENTS.md) when choosing budgets,
interpreting support or handling incomplete populations. Existing `media_perceive`
remains available for its published joint spoken/visible timeline contract.

Bind one regular local file with its full `expected_source_sha256`, choose a
bounded interval, and prepare with `dry_run=true`. Inspect the exact source,
actual frame PTS/indices, decoded audio interval, gaps and planned windows. A dry
plan can perform local native preparation, but makes zero provider calls.

Choose finite `fps` in 0.1..30 inclusive; the default is 1. The extractor samples
available source frames without interpolation. Set explicit frame budgets when
requesting higher rates: `max_frames_per_window` defaults to 32 and caps at 48,
with at most 128 aggregate frames. A reached frame budget reports partial visual
sampling and `coverage.stop_reason=frame_budget`; inspect actual PTS, sampled
points and gaps. A higher rate does not enlarge byte, deadline or provider budgets,
and sampled points do not establish continuous watched coverage.

Submit with `dry_run=false` and `authorize_submission=true` only when the workflow
has authority for that source upload and spend. Use the configured Gemini account;
never add endpoints, credentials, uploads or alternate services to a request.
The adapter has no installer or foreign Qwen execution route.

Choose the concrete task:

- Caption supported chronological audio, visual and fused occurrences.
- Count an explicit nonempty `target`; use only the server's admitted record count.
- Ground a nonempty `query`; choose positive integer `top_k` and retain the disclosed
  available/selected/truncated populations. Scores are uncalibrated model labels.
- Analyze music as audio only, including from a video container. Retain timed
  sections, instruments, moods and tags. Tempo, key, meter and section boundaries
  are inferred; decoded sample clocks measure the submitted waveform.

Report records with their source SHA, stable record ID, absolute and local times,
window index and actual audio/visual support. Both modalities supporting one fused
record count once. Keep distinct overlapping records and cross-window boundaries;
do not invent a physical identity merge or continuous watched coverage. Do not
rename nonspeech audio as a spoken claim.

Keep planned, valid empty, abstained, partial and failed outcomes distinct. A dry
count is unknown. An abstention does not prove absence. A later window failure
retains earlier records and `count_so_far`, while the final total remains unknown.
Include all planned and completed windows, measured gaps, attempts and unknown
usage. Do not repair JSON, silently truncate records or broaden retries after a
terminal failure. Cancellation must finish owned cleanup before returning.

Decoded clocks and byte commitments establish submitted lineage, not event or
music correctness. The programme's reviewed live semantic journey remains
`RESOURCE_UNAUTHORIZED`; source and mocked SDK checks do not close that gate.
