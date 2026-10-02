# Video windows and resumable analysis

`video_analyze` accepts local-file `fps`, `start_offset` and `end_offset`. Durations
use ordered `h`, `m`, `s` units with at most three decimal places in seconds:
`27m`, `1640s`, `1h2m3.125s`. Equivalent durations normalize to the same millisecond
values. FPS must be finite, greater than zero and at most 30. An end must exceed
the start. These arguments are separate from `execution_budget`, whose existing
window already owns its requested FPS and interval.

The prepared inline or uploaded SDK media part carries typed `VideoMetadata` and
`MediaProcessing.STATIC`. The response's `analysis_window` describes the requested
sampling and original source timestamp origin. Observed coverage remains unknown;
model timestamps require source/media review. Complete source and request settings
already belong to the result-cache identity. A changed window or FPS cannot reuse
another window's cached result. Equivalent normalized offsets can reuse an exact
fresh inline result. Opaque uploaded-file freshness remains unknown, so this route
does not assert a fresh result-cache hit. Static-window requests skip whole-file
context prewarming.

Local preparation uses a private exact-byte snapshot. When
`LOCAL_FILE_ACCESS_ROOT` is configured, put `GEMINI_CACHE_DIR` inside that root
so both the original source and generated snapshot/upload index satisfy the fence.
Symlink and nonregular source/index paths reject before provider dispatch.

## Bounded long-video workflow

`video_analyze_windows` defaults to a dry run. Supply exactly one local `file_path`
or YouTube `url`, explicit `end_ms`, instruction and five execution limits. The
tool hashes local original bytes, freezes runtime/account/schema/prompt settings
and enumerates at most 256
contiguous, non-overlapping, half-open intervals. The interval is caller supplied;
this planning step does not decode the source or verify its duration. Use
`media_info` to inspect actual duration before choosing an interval. Explicit FPS
is retained; automatic FPS selects a bounded uniform density from the initial
frame budget. Sampling density does not prove that a brief event was observed.

The direct YouTube URL route submits the canonical public locator to the configured
provider and performs no acquisition, download or File API upload. Its original
bytes, duration and current remote freshness remain unverified. Continuation binds
the locator and settings; it cannot prove that remote media stayed unchanged.

For local byte identity, or Loom, direct video or finite HLS, use the separate
metadata/acquisition operations first. `media_metadata` reads metadata; an explicitly
requested `media_acquire` returns a verified local analysis path. Acquisition
authorization and provider upload authorization are separate user decisions.
There is no silent download, provider fallback or additional synthesis request in
this window tool.

Example request:

```json
{
  "request": {
    "file_path": "/absolute/path/owned-video.mp4",
    "instruction": "List the actions and source timestamps in each interval.",
    "start_ms": 0,
    "end_ms": 120000,
    "window_ms": 60000,
    "fps": 0.5
  },
  "execution_budget": {
    "max_calls": 2,
    "max_tokens": 20000,
    "max_output_tokens": 2000,
    "max_frames": 60,
    "max_windows": 2
  },
  "dry_run": true
}
```

Inspect the dry plan before calling with `dry_run: false` under the appropriate
provider/source-upload authority. A count and generation each transmit media:
one completed interval normally consumes two calls, two requested windows and
twice its requested frames. Actual token counts and conservative schema/output
reservations control generation. Missing usage and ambiguous failures retain
their reservations. No price or hard charge bound is inferred.

File API preparation is separately reported. Large local source upload and polling are
excluded from the five count/generation limits; logical preparation attempts are scoped to the retained resource lifetime, and
unknown wire-level totals remain distinct. The whole original file is prepared
once for a run, even when generation requests only clipped intervals. The existing
single-window `execution_budget` route retains its inline-only size boundary.
The installed SDK's chunk uploader can retry independently of its initial upload
POST setting and can block its async path while waiting. Resource reservations
prevent duplicate launch on recovery; all-wire-attempt and hard wall-clock upload
bounds remain unverified.

## Recovery and retained outcomes

One canonical `JobStore` records each window run. `job_status` reads its attested
request/result; `job_cancel` stops queued work or requests an owner checkpoint.
Each attempted window is recorded before SDK submission. Completed windows survive
restart; a window interrupted after dispatch remains unknown and is never
automatically resubmitted. Generation under the durable submission scope uses one
SDK transport attempt and no application retry.
Cancellation and live ownership are checked again after token counting, before
generation is reserved or dispatched. A completed count remains in the run's
usage even when generation is known unsent. A run that loses ownership returns
the current canonical checkpoint with separate stopped-run telemetry; it cannot
overwrite the new owner's row.

A clean budget stop returns partial results, remaining work and a continuation
token. Send that token with the same request and a new explicit per-run budget.
The child retains the parent's frozen local source or remote locator, FPS, windows, model/account/schema
and settings. Repeating one token resolves the same child; its initial limits
cannot then be changed. Observed local source or request/settings mutation rejects continuation
before preparation or inference. A completed child does not repeat its provider
requests. `covered_windows` identifies successful provider-result windows. Observed/watched
coverage remains unknown. Ordered results remain separate model outputs; they do not establish
integrated factual acceptance or complete watched intervals.

File API upload preparation also uses the canonical store. A returned URI/name is
persisted before processing waits. A known processing timeout preserves that
resource for later polling; it does not authorize a new upload. An unknown upload
launch without resource identity remains unresolved. Remote revalidation is
required before reusing a retained active resource. A known failed or absent
resource permits a new reservation. Source bytes and configured credential scope
bind every resource, and ownership CAS prevents concurrent duplicate preparation.
Processing and active revalidation must return the exact retained resource name
and URI. Missing or mismatched identity leaves that resource unresolved and does
not permit a replacement upload.

## Source route and verification boundary

This independently authored implementation reconciles our own unpublished
`e326fde77356fecec64638abbdbbbaf7047c48b9` and
`bd980e834929c291ca3766180fb1a44d1f615efd` behavior with the current cache/budget/job
contracts. It implements the pinned long-video requirements from
`ludmila-omlopes/youtube-video-analyzer-mcp` at
`cdb00e98fcfe6198f209cc69288a2cdc3b495f58`. No foreign runtime body, asset, model
weight, dependency or default-model selection is copied. Exact current file
commitments belong to the reuse ledger and Beads `vrm-0e8.3.1` acceptance receipt.

Offline mocked SDK tests prove actual metadata, accounting, cache isolation and
durable recovery contracts. They do not prove live model quality, source upload
acceptance, human audit, comparative advantage or a registry release.

The mapped user operations use these verified entry points:

| Pinned source operation/workflow | Repository route |
| --- | --- |
| Single YouTube analysis and metadata | Existing `video_analyze` and `video_metadata`; bounded URL windows are already supported by `execution_budget` |
| Uploaded-file or direct URL long-video windows | `video_analyze_windows`, explicitly selecting local bytes or a canonical YouTube locator |
| Partial long-video continuation and task readback | Same tool with `continuation_token`, plus canonical `job_status` and `job_cancel`; ordered outcomes preserve the original denominator |
| A new follow-up question about retained media | Existing `video_create_session` and `video_continue_session`; `GEMINI_SESSION_DB` enables session persistence, while conversation history remains separate from verified source transcripts |
