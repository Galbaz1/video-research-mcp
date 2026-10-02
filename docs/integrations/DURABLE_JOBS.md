# Durable research, batch and render operations

The root and explainer servers share one SQLite job schema and database. Set
`VRM_JOB_DB` to an absolute private path to select it; the default is
`~/.local/state/video-research-mcp/jobs.sqlite3`. Configuration is loaded before
explainer startup recovery. New state directories use mode 0700 and the database,
WAL and shared-memory files use 0600. Existing parent permissions are preserved.
No optional checkpoint service or additional runtime dependency is required.

## Research operations

`research_web` and `research_web_followup` accept an optional stable `job_id`.
Their existing inputs and provider interaction IDs are preserved. Admission is
stored before one SDK submission. Repeating the same ID and immutable request
returns retained state; changing its request or adapter revision is rejected.
One active or ambiguous research operation per configured credential is admitted.
Age alone does not erase an operation or authorize another launch.

`research_web_status` reconciles the recorded provider ID. Read-only status polls
allow up to three requests for transient 403 responses; create and cancel calls
have no automatic transport retry. An SDK response for another operation is
rejected. Active request/result envelopes are attested before provider access or
local cancellation mutation. An immediately completed creation retains its full
report. An interrupted create without an operation ID remains `unknown`, blocks
another launch and requires external reconciliation. The server cannot recover
an ID the provider never returned and cannot infer whether such work was billed.

`research_web_cancel` records a request. Only an actual provider acknowledgement
can establish remote cancellation. A missing acknowledgement remains
`cancel_requested`. Completion after that request is retained as
`completed_after_cancel` with a partial job and explicit reconciliation required.
Retained reports are read back without resubmitting or repeating optional storage.

## Video batches

`video_batch_analyze` retains its directory, filter, instruction, schema, thinking
level and maximum-file inputs, and adds `job_id` and `max_concurrency` (1–3,
default 3). The immutable request includes original file hashes, prepared payload byte checks and configured
account, model and sampling settings. Completed and failed items remain in the
original denominator. Unknown, interrupted and late-completed items are reported
separately from successes; queued cancellation is counted separately from failure.

After restart, the same request may resume previously queued items. An item
checkpointed as running is changed to unknown and is never resubmitted. Source or
runtime changes stop that item's submission. Ownership is checked before media
preparation and again before inference; cancellation during preparation stops
inference. Non-idempotent item inference uses one transport attempt, with no
outer inference retry or optional graph-generation call.

`job_status` returns the actual durable record and current byte attestation.
`job_cancel` requests a video batch owner to stop queued work at its checkpoints;
it reports provider termination as unknown. Use the dedicated research or render
cancellation tool for those operation kinds.

## Explainer renders

`explainer_render_start`, `explainer_render_poll` and `explainer_render_cancel`
use the same store. Admission binds exact project source files, settings and CLI
candidate bytes. Two workers in each explainer process drain queued work; this is
a per-process bound. The database's project admission CAS prevents duplicate
active renders of the same project across processes.

Startup claims queued work once after checking its original inputs. A stale
running render becomes unknown. Recovery never reruns that render or signals a
stored PID. Live workers keep their lease while the CLI and FFmpeg run. Owned
cancellation joins the task, reaps the actual subprocess and, on POSIX, terminates
its owned process group. Windows descendant-process termination has not been
verified. Foreign or orphaned processes are reported as unable to terminate.

Status is read-only. Artifact hashing runs outside the event loop so root and
explainer heartbeats remain responsive. Missing or modified completed artifacts make the effective
readback state unknown while preserving the recorded terminal state. The output baseline is captured at dispatch; a changed admission baseline blocks
launch. Output must be a newly produced regular file; symlinks and old identical bytes with a new
modification time do not establish a completed render.

## Evidence and limits

The controller commits canonical JSON request bytes, operation kind, adapter
revision and exclusive scope in `request_sha256`. It commits result bytes,
request digest, provider/process operation ID and artifact hash manifest in
`result_sha256`. Readback independently checks the request and result envelopes
and streams current regular artifact files. Altering an envelope or artifact
prevents verified output. These digests detect drift relative to the retained
commitment; they are not signatures against an actor who can rewrite the entire
database and all commitments.

Ownership uses SQLite CAS with expiring leases. It is authority to reconcile an
operation, not permission to repeat uncertain work. Terminal results cannot be
retried or overwritten. The standalone store remains one canonical source file,
materialized into each package so separately installed servers share identical
schema behavior. Its larger module keeps that independently packaged schema,
byte bindings and native permission controls together; functions remain bounded.

Verification uses local SQLite, owned synthetic media, guarded SDK HTTP mocks
and owned CLI/FFmpeg processes. It establishes lifecycle and byte integrity.
Provider execution, factual/media quality, human audit, comparative advantage and
registry release remain their separate programme gates. Configuring a provider
or discovering a tool does not authorize spend, uploads or publication.
