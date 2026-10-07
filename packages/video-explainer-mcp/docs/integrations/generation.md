# Selected video generation: development route

The development source adds three explainer MCP tools for `wan2.7-t2v`:
`explainer_generation_submit`, `explainer_generation_poll`, and
`explainer_generation_cancel`. Published companion `0.2.2rc3` does not contain
these tools. This route has source/mock checks and a synthetic MP4 decode witness;
paid generation and picture/sound quality remain unqualified.

Use the [optional Qwen integration](../../../../docs/integrations/qwen-video-edit.md)
for its separate image/video contracts. It stays disabled by default and has
no qualified durable generation workflow. Neither route installs local models.

## Configure the source checkout

From `packages/video-explainer-mcp` in the development checkout:

```sh
uv sync --locked --extra generation
uv run --locked video-explainer-mcp
```

Set these process variables or entries in the wrapper's existing environment file:

```dotenv
EXPLAINER_PROJECTS_PATH=/absolute/path/to/projects
DASHSCOPE_API_KEY=<your selected workspace credential>
EXPLAINER_DASHSCOPE_BASE_URL=https://<workspace>.ap-southeast-1.maas.aliyuncs.com/api/v1
```

Before any paid request, verify both `ffmpeg -version` and `ffprobe -version`
locally; FFmpeg and ffprobe must be available on `PATH` for output qualification.

The exact documented Beijing workspace origin is also accepted. The endpoint and
key are required; neither has a usable default. Restart after changing them.
The optional `generation` extra supplies HTTPX, loaded only at the HTTP boundary.
This route uses the existing project/job store and does not require the external
`video_explainer` CLI for submit, poll or cancel.

## Prepare one bounded request

Create an existing project directory and retain its script and scene files.
Each `PinnedFile` supplies a project-relative path and SHA256 of its exact bytes.
Use the schemas in [models/generation.py](../../src/video_explainer_mcp/models/generation.py)
for the complete request and declaration fields.

A request binds a unique `logical_job_id`, script/scene IDs and pins, prompt,
model, duration, resolution, ratio, seed and `synthetic illustrative` label.
Supported durations are integer 2–15 seconds; resolutions are 720P/1080P and
ratios are 16:9, 9:16, 1:1, 4:3 and 3:4. The selected contract requires audio. This route always requests the provider's
visible AI Generated watermark and disables automatic prompt rewriting
(`watermark=true`, `prompt_extend=false`); neither is configurable.
Image-to-video, first/last frames, identity/style references, driving audio,
continuation and transparency are refused before submission.

Before submit, provide three pinned JSON declarations inside the project:

1. `PriceDeclaration`: selected model/resolution, currency, positive per-second
   price, caller principal and dated primary-source provenance.
2. `ModelAccessDeclaration`: the exact selected workspace origin/model,
   declared access, the same principal and dated workspace-source provenance.
3. `OperatorQuote`: pins to those declarations, the same price/origin/principal,
   absolute issue/expiry times, the request hash and selected contract hash.

The request hash uses the fully validated `GenerationRequest` JSON with only
`quote` omitted. The contract hash uses `CONTRACT` in
[generation_request.py](../../src/video_explainer_mcp/generation_request.py).
Both use the existing `planning_sources.digest` canonical JSON function. Pin the
finished quote in `request.quote`; set `max_cost`, `currency`,
`spend_authorized=true` and an explicit authorized submit operation.
The declared price × duration must fit the caller's bound. Missing, expired,
changed or mismatched declarations block submission. These are operator
declarations: the server does not authenticate the named principal, verify live
account access/prices or impose a provider billing cap. Obtain actual source,
account and spending authority before sending a real request. Test fixture prices
are synthetic and must not be used as live evidence.

## Submit, inspect and recover

Call `explainer_generation_submit(project_id, request)` once. Save its `job_id`.
The durable logical job prevents automatic resubmission after restart or an
ambiguous HTTP response. Reusing the logical ID with a changed request fails.

Call `explainer_generation_poll(job_id, operation)` for each explicit fetch.
An operation contains a unique `operation_id`, the original declared `principal`
and `authorize=true`. Replaying an operation reads the durable result. Polling
makes one status fetch; there is no background polling loop. `max_polls` counts
fetch intent, including failed attempts and cancellation checks.

For `unknown` without a provider task ID, reconcile the original submission with
the provider. Do not create a new logical ID to retry an unresolved paid job.
`explainer_generation_cancel` first fetches status and sends cancel only for
freshly observed `PENDING`. It requires a further fetch to confirm `CANCELED`;
a cancel acknowledgment alone does not establish cancellation.

On provider success, a poll downloads up to 32 MiB, hashes the saved MP4 and
fully decodes it with FFmpeg. Qualification checks exact dimensions, duration
within 0.1 seconds and one H.264 video plus one audio stream. Only the selected
Shanghai result hostname is accepted; other legitimate provider result origins
are currently unsupported. Expired URLs, redirects, changed bytes and decode
errors retain failure or unknown status. Outputs bind the original script/scene,
request/source hashes, model, task ID and synthetic label. Inspect the returned
`state.asset` and `attestation`; file validity does not certify style, factual
accuracy or musical/visual quality.
