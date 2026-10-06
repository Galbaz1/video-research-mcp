# Bounded AV-memory lifecycle

`video_memory_lifecycle` implements one invocation of `build`, `append`, `resume`,
`status`, `watch` or `replay`. This is a source implementation over the existing
`av_store` revisions, `av_build` admission/fold/native client, and evidence-only
`retrieval`; it introduces no provider SDK, memory engine, dependency, worker queue,
listener or background automation.

The source-only fixture checks do not establish native MCP registration, installed
runtime behavior, AV quality, a real presentation clock, speaker identity, held-out
acceptance or release. Root owns those integration and acceptance steps.

## Inputs and state

A source segment supplies `segment_id`, `file_path`,
`expected_source_sha256`, `expected_source_bytes`, `duration_seconds`, and existing
typed `ArtifactRef` observations. The duration and segment order are explicitly
`caller_asserted`. Supplied transcripts/AV events must pass the existing complete
schema, exact byte/source commitments and parent-clock agreement. Their stored
asserted/inferred basis is preserved. Captions never become transcript speakers.

`config.profile` and the optional build `config.av_route` are committed by canonical
SHA-256. Build, append, resume and status use that exact semantic configuration.
Replay additionally accepts its own explicit `av_route`: observing a supplied-only
memory does not require rebuilding it through a provider. Changing this replay route
does not mutate or reconfigure the stored memory.

The first source remains the canonical `MemoryState.source` anchor, including its
original duration. The latest `history[].lifecycle` checkpoint carries every source's
full digest, exact input manifest, offset, planned window count and processed prefix.
Records retain canonical source-based IDs and artifact origins. Record times and
`window` positions use the declared global clock. Total lifecycle duration is reported
separately from the anchor duration. Historical checkpoints remain in immutable
revision files; newer history entries retain their revision references and failures
without duplicating the entire source plan at every window.

## Build, interruption, resume and append

The fixed 30-second source windows are planned before extraction. Revision 1 has the
full denominator, an empty extracted prefix and `complete:false`. Each accepted
window publishes records, identities, facts, receipts and its progress in one canonical
revision using the existing fsync/link publication primitive. Empty admitted windows
count as processed; observation density is not a completeness or correctness measure.

Each invocation defaults to 16 processed windows and 30 seconds, bounded by
`limits.max_windows` (1–64) and `limits.timeout_seconds` (>0–60). The complete plan is
limited to 16 distinct source digests/segment IDs and 512 source windows. Reaching a
limit retains the same denominator and requires an explicit subsequent invocation.

`resume` requires the current `expected_revision`, rechecks source/config commitments,
and processes only the missing suffix of the frozen plan. It accepts no replacement
plan. Supplied input digests cannot be silently repaired with different bytes.
Restoring the exact missing original bytes permits an explicit resume and preserves
the original failed revision/report. There are no automatic retries.

`append` requires the current revision and a complete existing checkpoint. It freezes
the new denominator before processing additional sources. Source/config freshness is
checked before reuse and source bytes are checked again before window publication.
Publication conflicts propagate without a second publication attempt. A failed
segment persists its classification and stops every later segment/window.
The owned publisher adapter also rejects redirected artifact directories/files before
using the shared store. This does not claim native containment against concurrent
filesystem path replacement; that remains a native integration boundary.

Speaker labels from different files are distinct by default. An explicit
`identity_bindings: {"SPEAKER_00": "P001"}` refers to an already stored global person;
its basis is `user_asserted`. Existing names and identity revisions survive append.
Caller-authored `facts` use existing `FactInput`, cite canonical stored record IDs,
and are marked `asserted`. Fact conflicts use existing canonical merge/supersession;
losing facts and their provenance remain available. No names are automatically bound.

Example build (placeholders must be replaced with actual file/artifact commitments):

```json
{
  "action": "build",
  "memory_dir": "/allowed/memory",
  "expected_source_sha256": "<full-source-sha256>",
  "segments": [{
    "segment_id": "day1",
    "file_path": "/allowed/day1.mp4",
    "expected_source_sha256": "<full-source-sha256>",
    "expected_source_bytes": 12345,
    "duration_seconds": 65.0,
    "artifacts": [{"kind": "transcript", "path": "/allowed/transcript.json",
                   "sha256": "<full-artifact-sha256>"}]
  }],
  "limits": {"max_windows": 1, "timeout_seconds": 30}
}
```

Read `status` with the same anchor/config, then call `resume` with the returned
revision. Append uses the same anchor/config/revision plus its new source segments.
Returned `extracted/planned` counts describe processed source windows, and
`extracted_clips` names the exact chronological prefix.

## Watch and replay

Watch accepts a caller-described `source` and an explicitly authorized
`config.av_route`. Replay accepts the exact memory anchor/config, named
`clips: ["day1:0", "day1:2"]`, and an explicitly authorized `av_route`. Replay clips
are caller-retained files declared in the original segment's `clips` list with local
`window`, `path`, `sha256` and `bytes`. Retention and deletion remain caller decisions;
this tool neither creates nor deletes retained clips.

Without an authorized route the result is `status:unavailable`, `failure:config`,
`complete:false`, before any media hashing/submission. When configured, default
`limits` are 3 clips, 8 MiB payload, 120 seconds of selected media and a 30-second
invocation. Maximums are 8 clips, 32 MiB payload, 1,800 seconds of selected media and
60 seconds per invocation. Excess, duplicate, missing and unknown clip IDs are named.
Selected clips are submitted in their caller-declared chronological positions.

The input payload guard budgets the full declared source sizes as their conservative
inline base64 equivalent, including URI prefixes; actual bytes are verified through
the existing bounded regular-file reader. This is not a measured provider wire size:
the native AV client controls its own frame/audio serialization, and
`wire_payload_bytes` stays unknown. Admitted observations and returned stored evidence
share a response data payload ceiling; omitted retrieval evidence is named and makes
the result partial/rejected. Status/error metadata and execution receipts remain
separate from this data payload measure. Endpoint calls use an owned narrow adapter
around the existing `av_build.caption_events` native `media_caption_events` contract.
It preserves structured failure categories that the older shared route wrapper drops.
The route's `max_calls` is enforced across the
invocation, including multiple roles and clips.

Errors are classified as `reject`, `timeout`, `rate` or `config`. Every attempted
delegation is receipted before awaiting it; returned execution counters are retained,
and unreturned native provider usage stays unknown. A failure stops later clips,
preserves completed observations, and makes no automatic retry. Timeout cancels the
awaited operation. Existing synchronous local I/O has its own byte/deadline guards;
invocation deadlines are cooperative around it, not proof of kernel-level hard wall
enforcement or confirmed native cancellation/shutdown.

Watch/replay return typed AV observations and, for replay, canonical stored evidence
through `retrieval.run_plan`. They return no model answer, invented speech or inferred
speaker identity. A retained clip's parent-source/time correspondence remains
`caller_asserted`; hashing the clip does not prove its frames were sliced from that
parent. Partial completion, missing clips and native/runtime unknowns stay explicit.

## Root integration and source notice

Root must mount `video_memory_lifecycle_server` from
`video_research_mcp.tools.video_memory_lifecycle` on the shared server and update the
shared installer/manifest/reuse ledger as appropriate. No shared file was changed in
this lane. Root must preserve lifecycle source mappings when routing reads/exports:
the original single-source `moment` exporter cannot use the anchor file to export an
appended source's global window. Existing retrieval can consume the canonical records;
use explicit global time ranges through the lifecycle's full declared duration.

This is an independent implementation of the lifecycle protocol in
[QwenLM/Qwen-MM-Plugins at the pinned revision](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f).
The six reviewed original project files are `tools/get_memory_status.py`,
`tools/watch_and_answer.py`, `tools/replay_and_answer.py`, `watch.py` under
`src/capabilities/omni-memory/qwen_mm_plugins_omni_memory/`, and `storage.py`,
`build_memory.py` under `src/capabilities/omni-memory/skill/script/build_memory/`.
The pinned project [Apache-2.0 license](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/LICENSE)
and each file's complete bytes/hash/header were reviewed from Root's exact cached
seven-file index. No upstream runtime, prompt, asset or source module is copied or
imported. Changes replace mutable store/cache heuristics, runtime bootstrap and retry
loops with canonical revisions, exact commitments and finite evidence-only calls.

Run source-only checks with the existing environment, without installation:

```bash
PYTHONPATH=src .venv/bin/python -m pytest tests/test_video_memory_lifecycle.py tests/test_video_memory_lifecycle_replay.py -q
.venv/bin/ruff check src/video_research_mcp/models/video_memory_lifecycle.py src/video_research_mcp/video_memory/lifecycle*.py src/video_research_mcp/video_memory/replay.py src/video_research_mcp/tools/video_memory_lifecycle.py tests/test_video_memory_lifecycle*.py
```

The R175 unit checks use only dummy files, caller-authored schemas, real immutable
snapshot operations and mocked external native-client responses. They are separate
from the frozen original/native/held-out evaluation cohorts.
