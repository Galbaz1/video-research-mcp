# Optional TwelveLabs hosted workflows

`twelvelabs_call` implements selected REST operations against
`https://api.twelvelabs.io`. It uses TwelveLabs' own BYOK credential and hosted
processing. The adapter is disabled by default and does not install the
external npm MCP, discover its tools, or provide local inference.

Set `TWELVELABS_ENABLED=true` and provide `TWELVELABS_API_KEY` through the process
environment or secret store. No key is required for core startup. The read-only
doctor reports disabled, missing, or configured-but-unverified; it never probes
an account. A tool's grants are runtime controls, not authority for an agent to
spend money or disclose material without the user's current authorization.

Every request selects one `operation`, exact route `ids`, and finite JSON
`parameters`. `dry_run=true` is the default. Dry plans make no DNS/HTTP or job
database calls; a selected local file is read only under `LOCAL_FILE_ACCESS_ROOT`
and its expected SHA256. Execution requires `authorize_submission=true`.
Disclosure of local media, media URLs, or new provider media processing requires
`authorize_media_transfer=true`. Every DELETE and task cancellation additionally
requires `authorize_destruction=true`. There is no implicit upload, default index,
folder expansion, fallback, retry, polling, pagination, or cleanup.

Supported operation families:

| Family | Operations |
|---|---|
| Assets | `asset_create`, `asset_get`, `asset_list`, `asset_delete` |
| Indexes | `index_create`, `index_list`, `index_delete` |
| Indexed assets | `indexed_asset_create`, `indexed_asset_get`, `indexed_asset_list`, `indexed_asset_delete` |
| Search | `search_text_image_composed_entity` |
| Embeddings | `embedding_task_create`, `embedding_task_get`, `embedding_task_list` |
| Entity collections | `entity_collection_create`, `entity_collection_list`, `entity_collection_delete` |
| Entities | `entity_create`, `entity_list`, `entity_delete` |
| Analysis | `analysis_sync`, `analysis_task_create`, `analysis_task_get`, `analysis_task_list`, `analysis_task_cancel`, `analysis_task_delete` |

Examples below are requests, not observed provider outputs. Select models
explicitly using the current account's supported models; the adapter supplies
no model default. Index creation uses `index_name` and explicit `models` objects.

```json
{
  "operation": "search_text_image_composed_entity",
  "parameters": {
    "index_id": "EXACT_INDEX_ID",
    "search_options": ["visual"],
    "query_text": "a person holding a red sign",
    "group_by": "clip",
    "page_limit": 10
  }
}
```

For image search, supply `query_media_type="image"` and one to ten
`query_media_url` strings, or one `local_file` with `expected_source_sha256`.
Text plus image supplies a composed query; `<@EXACT_ENTITY_ID>` in `query_text`
selects an entity query. No candidate URL or thumbnail is fetched. Local uploads
use a constant filename with the selected supported image/video extension;
private basenames are not sent. Extension and byte admission do not establish
decoded media validity. Asset creation selects exactly one local file or URL.

Run `asset_get` explicitly and retain its ready observation's `job_receipt.job_id`.
`indexed_asset_create` then requires `ids.index_id`, `parameters.asset_id`, and
that `ready_asset_job_id`. The adapter checks receipt integrity, account, asset ID
and readiness without another request. This is a retained provider observation,
not a guarantee that the service's state has stayed unchanged. Asset IDs,
indexed-asset IDs, legacy video IDs and task IDs remain distinct.

Embedding task creation uses `input_type="video"`, explicit `model_name`, and
`video={"media_source":{"url":"https://…"}}`. Model-dependent newer sync
multi-input/text/image shapes are a separate service interface; they are not
guessed or routed through this video task contract. Indexed embeddings can be
requested explicitly through `indexed_asset_get` query parameters. Finite bounded
vector data remains a provider representation, never source-verified truth.

Sync/async analysis accepts `video={"type":"url","url":"https://…"}` and
`prompt` or `prompt_v2`. Asset/base64 variants and legacy video payloads are
explicitly unsupported in this selected analysis contract. `analysis_sync`
forces `stream=false`; NDJSON is unsupported. An explicitly selected analysis
window must last at least one second. Original provider clocks, including nonzero
source start times, are not shifted. Entity creation selects existing `asset_ids`;
its name or embedding does not verify a real-world identity.

`queued`, `pending`, `validating`, `indexing` and `processing` map to processing.
Ready analysis requires retained result data and `finish_reason="stop"`; length
limits or reported errors stay partial. Missing results and unknown statuses stay
unknown. Failed and canceled tasks retain their observations; omitted usage is
unknown, never zero charges. Successful empty DELETE responses are supported.
Deleting a task does not cancel processing. Cancellation does not prove immediate
compute termination; asset `force` deletion and index deletion can remove remote
relationships. There is no automatic destructive compensation.

Each real call persists an immutable local job before one HTTP attempt. Reuse an
identical `job_id` to read the retained result; changed request/account/source
bindings refuse. `job_status` reads the SQLite record and fresh byte attestation.
Local completed means the HTTP observation was retained, even if the remote task
is still processing. A crash, timeout or cancellation stays ambiguous and cannot
resubmit the same call. Reconcile the provider explicitly using a new status-call
job and a known provider task ID. Caller-supplied `custom_id` is not idempotency.

Limits: local media at most 8 MiB; parameters 64 KiB; form/query fields at most 128;
response at most 256 KiB and returned JSON text at most 128 KiB; search page at most 50;
one HTTP request, at most 120 seconds plus joined transport cleanup at most 5 seconds.
Local preparation has the selected timeout too; cancellation signals its bounded
read worker and joins it before returning. Local preparation and the HTTP exchange
use separate deadlines.
Smaller request limits apply. HTTPS source syntax is checked locally; the provider's
remote media DNS, redirects, fetch size and original bytes remain unverified. The
API transport separately checks all public DNS answers, pins the connected peer,
preserves Host/TLS identity, disables proxies/redirects/compression, and joins
owned cleanup. The raw response hash is retained even when output is refused or
redacted. Upstream error bodies and credential echoes are withheld/redacted.

Clip results retain exact returned seconds and provider video/index IDs, plus
an explicit `urn:twelvelabs:…` reference derived from those IDs and offsets.
This is a provider-origin reference, not an attested source byte digest. Malformed
clips stay in the rejection denominator. Grouped-video DTOs remain in bounded
`provider_data`; no uninspected nested clip schema is invented.

Source authority is the MIT client plugin
[pinned source](https://github.com/twelvelabs-io/twelve-labs-claude-code-plugin/tree/c9d4936dbee87ecfd4fb8c54f7369d9b83439f14)
and the official REST contracts inspected for this adapter. All twelve mapped
files, one necessary helper, and the MIT grant were read at that revision.
The adapter is independently authored; no upstream code, SDK, server, assets or
weights are copied/imported. The MIT client license does not grant hosted service,
account, data-processing or model rights. The plugin's 24 documented external tool
names remain undiscovered until a separately authorized external integration test.
Mocked contracts and installed MCP journeys establish local behavior; live schema,
inference quality, costs, remote cleanup, human acceptance and release remain unverified.
