# Video execution budgets and response views

`video_analyze(dry_run=true)` hashes a bounded local original or identifies an
unfetched remote URL, then reports local reads and remote source/prompt/schema
payloads. It creates no provider client, upload, optimizer request, cache prewarm or
inference. An unfetched URL has unknown freshness. The plan inherits current model
configuration; it does not invent token usage, prices, charges or observed coverage.

An explicit `execution_budget` enables the current single-analysis pipeline with
static video sampling. For example:

```json
{
  "dry_run": true,
  "execution_budget": {
    "max_calls": 2,
    "max_tokens": 100000,
    "max_output_tokens": 2048,
    "max_frames": 60,
    "max_windows": 2,
    "start_ms": 0,
    "end_ms": 30000,
    "fps": 1.0
  }
}
```

The two calls are the provider token-count request and one generation request.
Both transmit the original inline bytes or URL and the requested window. Every
transmission consumes a call/window and its requested static sampling positions;
each retry consumes another reservation. The plan blocks a budget that cannot fit
those first two transmissions. `max_output_tokens` is sent to the SDK and SDK
transport retries are disabled; application retries are metered individually.
Reservations use the provider input count, a separately labelled conservative
UTF-8 schema allowance and the output cap. Missing counts block generation.
Failed attempts retain reservations because their billing is unknown.

`execution_usage` separates measured provider usage from conservative reservations,
reports every attempted model operation and preserves absent telemetry as unknown.
A provider report exceeding a reservation blocks later requests and returns an
explicit failure. Requested frame positions are a local planning bound; decoded
frames, observed coverage, provider billing and any monetary charge ceiling remain
unverified. `cost_usd` and `saved_tokens` remain null. The current provider contracts
are described in Google's [video processing guide](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding),
[token guide](https://ai.google.dev/gemini-api/docs/generate-content/tokens) and
[thinking token limits](https://ai.google.dev/gemini-api/docs/thinking#token-limits-and-max_output_tokens).

Bounded execution bypasses result-cache reads/writes, metadata optimization, context
prewarm and optional knowledge enrichment. Local files must fit the existing inline
threshold and match the planned original SHA-256 at preparation and core analysis.
The original file is sent; the requested window is metadata, not a local extracted
clip. Large File API uploads and the multi-stage strict artifact pipeline return
concrete plan blockers in this bounded mode. Their existing unbounded interfaces
remain available with their ordinary contracts.

`output_fields` selects top-level response fields after complete analysis and
storage. Source identities, complete citations/evidence carriers, provenance,
coverage, quality reports, artifacts and execution usage remain included. Nested
custom fields carrying evidence are retained whole. Sparse projection reports its
requested/returned fields and method; it does not claim a measured billing saving.

For a custom schema returning `transcript: string`, `transcript_offset` and
`transcript_limit` page that string by Unicode code points. Limits are 1–10,000;
offsets are 0–2^31−1. `transcript_page` reports exact returned/total counts, omitted
prefix, remaining suffix, stable `next_offset` and `truncated`. The flag is true
whenever any original text is omitted, including final pages with an omitted
prefix. Past-end offsets return an empty page without continuation. The original
stored transcript and complete citations stay unchanged. Missing/non-string
transcripts and invalid requests return explicit errors; error responses preserve
any usage already recorded.
