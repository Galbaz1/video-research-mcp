# Provider readiness and bounded development runs

`vrm-0e8.2.9` supplies a read-only inspector and a separately reviewable pilot
proposal. The [matrix and plans](provider-readiness.json) cover core/companion
integration groups and explicitly optional families.
Settings refer to the current config fields and environment variables. They do
not pin provider model IDs in prose.

```bash
uv run python scripts/inspect_provider_readiness.py
uv run pytest tests/test_provider_readiness.py -q
```

The inspector reads current config source through AST, installed package metadata,
PATH presence, the renderer prerequisite files and the shared dotenv parser. It
mirrors dotenv precedence in a private dictionary. It does not inject environment
variables, import provider clients or tracing setup, run executables, probe URLs,
inspect login stores, create credentials or write files. Endpoint/path/credential
and configured model values are omitted. Safe numeric limits are reported against
their config field, including the current local media input limit. Invalid numeric
or provider settings are reported without echoing their values.

## What a state establishes

| State | Evidence |
| --- | --- |
| `disabled` | Current source flag/endpoint enables no service, or integration is still explicitly planned |
| `missing` | Required key, package, executable or source-defined prerequisite is absent/invalid |
| `mocked` | The companion's selected TTS provider is mock; no real synthesis is established |
| `installed` | Required local runtime metadata/PATH entries exist; service authentication remains unverified |
| `configured-but-unverified` | Current configuration and local prerequisites are present; connectivity, scope, quota and actual provider behavior remain unverified |
| `live-verified` | Requires a separately accepted exact provider-run receipt; the inspector cannot establish it |

The inspector consequently emits `live_verified=false` for every current row.
It rejects a manifest that attempts to supply authority or live-verification
receipts through this offline path. Installed CLI presence does not prove a valid
login. The renderer follows its current source auto-detection as well as
`EXPLAINER_PATH`; its unresolved upstream grant remains a separate operational
block. Planned CAD/FEM, hardware, local models, parsers, Qwen/cloud generation and
publication families stay disabled even if a related executable is installed.

The local PNG inspection/crop helper requires independently installed FFmpeg;
the matrix reports its presence without executing it. The matrix's original
registration-pending note is historical: the root now mounts the media, media-read
and image subservers. See [native media](NATIVE_MEDIA.md) and
[image exports](IMAGE_EXPORTS.md) for the current entry points and prerequisites.
Registration and an installed decoder establish no provider-media acceptance.

The source fingerprints identify the code actually inspected. A safe local
presence report is not an exact effective model/settings freeze. An authorized
runner must privately resolve and freeze those settings, source commit, account,
price revision and schema before submitting a request.

## Proposed development pilot

All six plans are **drafts without run authority**. Their allocations share one
proposed **USD 10 aggregate ceiling**, one concurrent request, at most **10
billable generation/synthesis attempts** and **25 provider HTTP operations**.
An allocation is a limit, not an estimate of the current provider price.

| Plan | Input/mode | Generation attempts | HTTP operations | Allocation |
| --- | --- | ---: | ---: | ---: |
| Text grounding | Two original development text cases: current versus stale evidence and absent evidence | 2 | 2 | $0.50 |
| Native AV | Three prompts over one original three-second synthetic MP4: visual marker, beep, temporal order | 3 | 8 | $1.00 |
| Cache reuse | One declared text source, one short cache, two calls, status and cleanup | 2 | 5 | $0.50 |
| Deep research | One source-limited original development question, six polls and one cancellation maximum | 1 | 8 | $5.00 |
| Scene text | One original development plan; one SDK turn with tools disabled | 1 | 1 | $1.00 |
| Voiceover | At most 160 characters from the original development plan; one configured non-mock synthesis | 1 | 1 | $2.00 |

Each plan records source/case hashes, configuration bindings, attempts, concurrency,
wall-clock limit, HTTP-operation count, spend allocation, necessary source-upload/
output/cleanup authority and telemetry requirements. No publication, physical
operation, recording or account creation is authorized by these plans. The
voiceover payload is a deterministic first-160-character UTF-8 extraction with
its own hash. Deep research also needs a reviewed public seed/browsing scope.

The existing checked-in video/audio development cases are **text observation
snapshots**, so they cannot prove media inspection. The native AV pilot instead
names a privately stored, newly authored deterministic MP4 with exact hash,
duration, frame rate, dimensions and construction recipe. It has a red square and
a synthetic tone, with no natural speech, human identities or third-party assets.
It is a provider contract smoke. It cannot establish speech intelligibility,
speaker identity, long-video coverage or comparative superiority.

## Launch and telemetry boundaries

Before any launch, the coordinator needs exact account/project and operation
permission, rights-cleared source/provider/runtime selection, privately frozen
settings and a proven maximum charge that fits the remaining shared allocation.
Use an account/backend hard spend cap or a demonstrated preflight upper charge
bound. If neither exists, the plan stays blocked. Timeout and cancellation alone
do not enforce a backend bill. The plans prescribe one application attempt;
provider SDK retries and hidden auxiliary work must also be disabled or counted.

Preserve raw request/task/file/cache IDs, input/config/source/output hashes,
input/output/thought/cached tokens, search/embedding/auxiliary usage, pricing
revision/currency, elapsed time, every failed/refused/abstained attempt, cleanup
and account billing. Missing telemetry remains unknown.

Current gaps are explicit: Gemini text wrappers discard response usage; optional
MLflow autolog capture has not been demonstrated. Deep research exposes selected
token totals but needs search/auxiliary and asynchronous billing receipts. The
scene wrapper drops SDK terminal cost/usage. Embedding, reranking, storage, voice,
stock media and renderer services have separate usage and rights. Mere key or URI
presence resolves none of these gaps.

The inspector validates only declared development sources and current code. It
reads no private heldout inputs, labels, source snapshots or media. The deferred
human source audit and independent heldout acceptance remain mandatory at
`vrm-0e8.10.2`; this readiness leaf supplies no waiver and no superiority evidence.
