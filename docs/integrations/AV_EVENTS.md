# Supported AV event and music records

The root server adds `media_caption_events`, `media_count_events`,
`media_ground_events` and `media_analyze_music` for exact local media revisions.
They prepare measured source windows and use the existing Gemini client for
optional, explicitly authorized inference. Existing `media_perceive` schemas,
default prompts and spoken/visible labels remain intact.

These tools expose inferred records with actual submitted support. They do not
establish event detection accuracy, physical event counts, continuous watched
coverage, musical correctness or human acceptance. The programme's reviewed live
fleeting-event, overlap and music journey remains `RESOURCE_UNAUTHORIZED`.
Source inspection and mocked SDK tests cannot satisfy that live gate.

## Caller workflow

Bind `file_path` to a regular local file and `expected_source_sha256` to its full
SHA-256. Select an explicit source interval, task and budgets. All four requests
default to `dry_run=true` and `authorize_submission=false`. A dry run prepares
actual source evidence and reports planned windows with zero provider calls. It
can use the installed local media tools; it is not a no-execution file inventory.

Inspect the source revision, decoded frame points or PCM selection, gaps and
planned population before authorizing submission. When the workflow already has
upload/spend authority, use the same request with `dry_run=false` and
`authorize_submission=true`. The configured Gemini account and model are used;
requests cannot inject an endpoint, provider, API key or remote upload destination.
An absent grant or account prevents all provider count/generation calls.

| Tool | Additional request fields | Retained result |
| --- | --- | --- |
| `media_caption_events` | Optional `instruction` | Chronological audio, visual and fused occurrences |
| `media_count_events` | Required nonempty `target` | Every admitted occurrence and a server-derived count |
| `media_ground_events` | Required nonempty `query`; strict integer `top_k` in1..128, default10 | All admitted matches, score-ranked selection and explicit selection population |
| `media_analyze_music` | Optional `instruction`; media type fixed to `audio` | Timed audio-only sections with inferred instruments, moods, tags and optional tempo/key/meter |

Each task has its own provider response schema and prompt. Counting accepts
occurrence records, not an independent model count. Grounding retains every
admitted record in `records`; `matches` contains the ranked top-k selection.
`grounding_population` reports available and retained records plus the exact
truncated IDs. Scores in0..1 are explicitly uncalibrated. Their order is not a
confidence certificate.

Music uses real selected audio only, including when the file is a video
container. It refuses missing audio or any visual payload before submission.
Music section boundaries and optional `tempo_bpm`, `key` and `meter` are model
inferences within measured audio support. The actual sample clock measures the
submitted waveform; it does not measure musical structure. Descriptions may
identify speech, nonspeech sounds or music; nonspeech is never automatically
renamed a spoken claim.

## Evidence and populations

Provider event times are finite window-relative seconds. The server maps them to
absolute source seconds while retaining the local offsets and window index.
Start-time order is required, but distinct overlapping intervals remain separate.
Exact duplicate records fail the whole window without merging or dropping them.
A fused `both` record is one retained occurrence and requires both actual audio
and visual support. No physical identity is automatically merged across windows.

Every retained record has a server-assigned `record_id`, exact source hash,
window and interval commitments, and `evidence_status=model_inference`.
Visual support cites unique actual submitted frame indices and preserves original
PTS, time base, source seconds and encoded artifact SHA. The point must lie inside
the claimed interval. Sample points do not prove coverage between them.

Audio support includes the actual `selected_window`, decoded source audio clock,
full submitted WAV SHA/bytes and independent PCM SHA, sample count, sample rate,
duration and format. A record outside that selected interval is refused. These
commitments are checked against retained immutable payloads and the original
source before and after provider work. Preparation artifacts are ephemeral;
results retain metadata rather than paths or raw payload bytes.

| Result state | Meaning |
| --- | --- |
| `planned` | Evidence prepared; no inference, `count=null` |
| Complete `events` | Nonempty admitted inference records; count derives from retained records |
| Complete `empty` | Valid empty supported population; count0 for a counting task, without claiming physical absence |
| Complete `abstained` | Explicit reasons with no records; counting total is unknown |
| `partial` | Earlier completed windows retained after a later failure or final source rejoin failure; total is `null` |
| `failed` / `error` | No complete window accepted; no accepted total |

Incomplete counting returns `count_so_far`, all retained records, all planned
windows and completed-window accounting. Later unrun windows remain planned;
they are never silently dropped from the population. A malformed response is an
error, not valid empty or abstention. Cancellation propagates after owned
preparation cleanup; it does not produce an accepted result.

## Bounded execution

Limits remain the existing AV limits: selection at most120seconds, at most4
windows,128 aggregate frames,48 frame references per window,24 count/generation
calls,8MiB prepared payload,64MiB serialized transmission ceiling and120seconds
for the operation. Responses are at most128KiB JSON per window. Local model-time
validation tolerance is1e-6seconds. Requests can choose smaller allowances.

The exact task schema is used for structured generation, serialized input byte
accounting and the request digest. Counting and generation transmit the same
prepared content. Each SDK transport attempt is configured with one submission;
only classified500/502/503/504 failures can produce up to3 task attempts. Unknown,
authentication, quota, schema and finish failures are terminal. There is no JSON
repair round. The existing source, buffer and account rechecks stay active.
Unknown provider usage and costs remain unknown. Raw provider body diagnostics
and credentials are withheld. Budget receipts describe observed SDK submissions;
they are not HTTP framing or operating-system isolation measurements.

## Source and runtime boundary

The design was informed by
[QwenLM/Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f),
at revision `07736672525443c7f8a3f6405eed37d2236f023f`, under its complete
[Apache-2.0 grant](https://github.com/QwenLM/Qwen-MM-Plugins/blob/07736672525443c7f8a3f6405eed37d2236f023f/LICENSE).
The preparation gate read12 complete source bodies,119,217bytes and2,979lines,
with31 exact artifact bindings. Fifteen original source defects remain recorded
in private source-contract evidence rather than being erased from the denominator.

The retained upstream runtime closure is `INCOMPLETE_CAP`; no Qwen Python module,
SDK, OSS upload, script or transitive runtime is imported or executed here. This
implementation uses existing root media preparation, Gemini transport and budgets.
No model, provider package, weights, fonts or assets are downloaded or installed
by the adapter. The source grant permits the inspected source; it does not attest
an external model, supplied media rights or native isolation. The unchanged
external companion production CLI is outside this route.
