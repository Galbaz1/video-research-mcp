# Image generation, editing and translation

Companion RC4 candidate (`0.2.2rc4` on PyPI, source tag `v0.8.0-rc.6`)
adds four image lifecycle tools. Publication and installation verification are
pending; published `0.2.2rc3` does not contain them. Candidate tag links resolve
after publication.
This adapter uses primary HTTP contracts directly, without the DashScope SDK.
Live access, output quality and identity preservation remain unqualified.
The submit/finalize/poll/cancel route needs no upstream `video_explainer` CLI.

From `packages/video-explainer-mcp` in the development checkout:

```sh
uv sync --locked --extra generation
uv run --locked video-explainer-mcp
```

Configure `EXPLAINER_DASHSCOPE_IMAGE_BASE_URL` explicitly as the regional workspace
origin ending in `/api/v1`; its default is empty. Generation/editing accept
documented Beijing or Singapore workspace origins. The selected legacy
translation model is documented only in Beijing; translation requires
`https://<workspace>.cn-beijing.maas.aliyuncs.com/api/v1`.
The existing `DASHSCOPE_API_KEY` credential
must belong to that region. Credentials stay in server configuration. The
Pillow decoder is supplied by the generation extra; no installation occurs on
startup. Set `EXPLAINER_PROJECTS_PATH` to the existing project root. The existing
durable controller uses `VRM_JOB_DB` when configured.

| Mode | Selected model and HTTP contract | Input and output |
| --- | --- | --- |
| `text_to_image` | `qwen-image-2.0-pro`, synchronous `POST /services/aigc/multimodal-generation/generation` | One user message, one text instruction; 1–6 PNG outputs |
| `image_edit` | Same model and synchronous endpoint | 1–3 ordered actual image files encoded as Base64 image entries, followed by one text instruction; 1–6 PNG outputs |
| `image_translate` | `qwen-mt-image`, asynchronous `POST /services/aigc/image2image/image-synthesis` with `X-DashScope-Async: enable` | One already public HTTPS URL whose current bytes match a local source pin; one JPG output with source dimensions |

The synchronous [generation](https://www.alibabacloud.com/help/en/model-studio/qwen-image-api)
and [editing](https://www.alibabacloud.com/help/en/model-studio/qwen-image-edit-api)
contracts use `model`, `input.messages`, and `parameters`. The adapter carries
`size`, `n`, `seed` when supplied, `negative_prompt`, `prompt_extend`, and `watermark`
exactly. `watermark=null` resolves to `true` for generation/editing; an explicit
boolean sets that control. Translation requires `null`, because its contract
has no watermark setting. Generation/editing require dimensions divisible by 16 and a pixel area from 512² to
2048², avoiding implicit provider rounding. The primary prompt limit is 1,300
tokens; this bounded adapter accepts at most 1,300 UTF-8 bytes and 1,000 characters
without assuming a qualified tokenizer. PNG/JPEG/WebP still references are
supported; animation is refused. Individual image bodies are bounded to 10 MiB,
decoded pixels to 16 Mi pixels, and the output set to 32 MiB.

The [translation contract](https://www.alibabacloud.com/help/en/model-studio/qwen-mt-image-api)
uses `input.image_url`, `source_lang`, `target_lang`, and
`ext.config.imageSegment`. Legacy `qwen-mt-image` requires Chinese or English on
one side. Supported source codes are `zh,en,ja,ko,ru,es,fr,pt,it,de,vi,auto`;
target codes are `zh,en,ja,ko,ru,es,fr,pt,it,vi,ms,th,id,ar`.
Source and target must differ. German is source-only. Translation has no selected
prompt, size, seed, count, watermark, identity/style, or continuation control;
such intent is refused. Translation requires a public URL rather than local
upload or Base64. Its current remote bytes are compared before POST; subsequent
provider retrieval and semantic use remain unqualified. A successful, billed
response reporting no translatable text is retained as such.

Each request includes a logical job ID, an explicit authorized operation ID and
caller declaration, `script_id`, `scene_id`, pinned script and scene files,
`spend_authorized`, `max_cost`, currency, and a pinned quote.
`spend_authorized=true` records an input acknowledgement; obtain actual human
submission and spending authority separately. It does not authenticate a
principal, verify live account access or cap provider billing. Price, access and
quote files use the [request, operation and declaration schemas](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/models/image_generation.py).
The price unit is
`image`; the quoted total is `price_per_image × n`. The quote commits the request
excluding its own pin, the captured contract hashes, origin, model, mode,
currency, caller and absolute validity interval. Its price and access source
files are independently pinned. These are operator declarations, not
authentication or verified provider access. Missing, changed or incompatible
declarations refuse before generation.

Prepare a validated request with its pinned script/scene, optional references
and placeholder quote pin. Serialize it with `model_dump(mode="json")`, remove
only `quote`, then hash it with
[`planning_sources.digest`](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/planning_sources.py).
Use the same function on `CONTRACT` in
[`image_generation_request.py`](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/image_generation_request.py).
Store those values in `ImageQuote.request_sha256` and `contract_sha256`, pin the
finished quote file and replace the request's quote pin. Price/access declarations
must describe the selected real model and region; synthetic test prices are not
live evidence.

After validating the request and obtaining human authority:

```text
explainer_image_generation_submit(project_id, request) → save job_id
explainer_image_generation_finalize(job_id, operation) → synchronous images
explainer_image_generation_poll(job_id, operation) → translation/recovery
```

Each `operation` has a fresh `operation_id`, the original declared `principal`
and `authorize=true`. Inspect tool errors before reading `job_id` or assets.
One translation poll makes one fetch; another fetch needs another explicit
operation. On completion, inspect `state.assets`: each saved path, SHA256,
decoded format/dimensions and qualification. Keep the original logical job ID
when recovering. Core `job_status` refuses this generated-media kind.

For editing, `input`, `identity`, and `style` reference roles retain actual ordered
files and hashes. The provider receives their image bytes with the explicit
prompt. A valid reference proves byte custody; it does not guarantee identity or
style fidelity. Arbitrary context is not a qualified capability. Every handoff
retains the request, controls, reference pins, synthetic illustrative label,
source/contract revisions, artifact hashes and actual decoded format/dimensions.

An editing continuation is an explicit reuse of anchors and settings. Pin a JSON
object matching the prior handoff's `continuation_settings`, with exactly
`model`, `controls`, `references`, and `unaffected_artifacts`, then supply that
file as `continuation`. Every control and reference must match, and every
unaffected artifact is rehashed. This uses the documented image-edit inputs;
there is no hidden conversation or provider session state. Unsupported alpha
intent is retained and refused before POST because these selected contracts have
no documented alpha control.

1. Call `explainer_image_generation_submit` once. Its durable generation intent
   precedes the HTTP effect. The durable job ID, provider request ID and optional
   translation task ID remain distinct. Replaying the same logical request
   returns its existing state; a conflicting request refuses.
2. For synchronous output, call `explainer_image_generation_finalize` with a
   fresh authorized operation. It downloads captured URLs without API credentials
   and qualifies the actual raster bytes and requested dimensions. Poll can also
   finalize captured output, but never invents a synchronous status endpoint.
   Each qualified image is checkpointed before the next download; recovery reuses
   verified saved originals if a later URL fails.
3. For translation, call `explainer_image_generation_poll` with a fresh operation
   for one documented `GET /tasks/{task_id}`. Poll count is finite and durable.
   A successful task is downloaded and qualified; signed URLs are kept in private
   durable state and omitted from public readback. Result downloads require HTTPS
   with validated origins; redirects and automatic HTTP retries are refused.
   Public readback redacts credentials and signed URLs in translation messages;
   exact provider response bytes and messages remain in private durable state.
4. After interruption or restart, use explicit poll/finalize recovery. Ambiguous
   submission without a recoverable provider ID/response remains UNKNOWN and
   requires provider reconciliation. A new operation ID never authorizes another
   generation POST. Changed source/adapter/output bytes refuse or downgrade proof.
5. `explainer_image_generation_cancel` reports unsupported synchronous remote
   cancellation. Translation cancellation follows the primary
   [task-management contract](https://www.alibabacloud.com/help/en/model-studio/manage-asynchronous-tasks):
   fetch fresh PENDING, record at most one cancel intent, POST cancel, validate the
   JSON-string request-ID ACK, then fetch confirmation. The ACK alone is not
   cancellation. An ambiguous cancel is not resubmitted.

The adapter retains source/contract revisions and independently authored HTTP
contracts. Fixture success does not establish live delivery, semantic fidelity,
full security review or whole-programme acceptance.
