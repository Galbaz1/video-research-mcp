# Durable video generation

Companion RC4 candidate (`0.2.2rc4` on PyPI, source tag `v0.8.0-rc.6`)
adds `explainer_generation_submit`, `explainer_generation_poll` and
`explainer_generation_cancel`. Publication and installation verification are
pending; published `0.2.2rc3` lacks these tools. Source/mock checks and synthetic
MP4 decode evidence leave paid generation and picture/sound quality unqualified.
Text-to-video selects `wan2.7-t2v`; first-frame and first-plus-last-frame modes
select `wan2.7-i2v` and send wire model `wan2.7-i2v-2026-04-25`.
Use the [image route](image-generation.md) for durable image generation, editing
and translation. The [optional Qwen integration](../../../../docs/integrations/qwen-video-edit.md)
is a separate raw-process route, disabled by default. Optional durable S2V/HappyHorse
modes are implemented in this candidate, with separate input contracts below.
Their native/provider and creative acceptance remains pending.

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
The optional `generation` extra supplies HTTPX and Pillow. Pillow decodes frame
references; HTTPX loads at the HTTP boundary.
This route uses the existing project/job store and does not require the external
`video_explainer` CLI for submit, poll or cancel.

## Prepare one bounded request

Create an existing project directory and retain its script and scene files.
Each `PinnedFile` supplies a project-relative path and SHA256 of its exact bytes.
Use the schemas in [models/generation.py](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/models/generation.py)
for the complete request and declaration fields.

A request binds a unique `logical_job_id`, script/scene IDs and pins, prompt,
model, duration, resolution, ratio, seed and `synthetic illustrative` label.
For the selected Wan2.7 modes, durations are integer 2–15 seconds; resolutions are 720P/1080P and
ratios are 16:9, 9:16, 1:1, 4:3 and 3:4. The selected contract requires audio.
`watermark=true` and `prompt_extend=false` are the defaults; both controls are
explicitly configurable and retained in the saved request and asset handoff.

For `wan2.7-i2v`, supply one `first_frame` reference and optionally one
`last_frame`. Each pin must identify an opaque, unrotated, single-frame
JPEG/PNG/BMP/WebP of at most 20 MB, with both sides 240–8000 pixels and no alpha
channel or palette-transparency metadata. The declared
ratio must match the first frame exactly. Declare `expected_dimensions` as
multiples of 16: these are your output acceptance expectation, not a guarantee
from the provider. Saved video must match them to qualify. The wire carries
the exact pinned image bytes as data URIs. Identity/style references, driving
audio, continuation and transparency remain unsupported on this video route;
unsupported intent fails before submission.

### Optional cloud modes in the candidate

These models use the same durable submit, poll and cancel tools. They require
model-specific quotes and pinned inputs; they do not use the optional Qwen CLI.

| Model | Inputs | Duration and resolution |
| --- | --- | --- |
| `wan2.2-s2v` | One `portrait` image and one `driving_audio` WAV/MP3 | Whole audio, shorter than 20 seconds; 480P/720P; Beijing workspace only |
| `happyhorse-1.0-t2v` | Prompt and ratio; no references | Integer 3–15 seconds; 720P/1080P |
| `happyhorse-1.0-i2v` | One `first_frame` image | Integer 3–15 seconds; 720P/1080P |
| `happyhorse-1.0-r2v` | 1–9 image references, each identified as `[Image N]` in the prompt | Integer 3–15 seconds; 720P/1080P |
| `happyhorse-1.0-video-edit` | One `source_video` H.264 MP4/MOV and 0–5 image references | Whole video, 3–15 seconds; 720P/1080P |

Declare `expected_dimensions` and `expected_audio`. Output dimensions must
match the selected tier and the declared ratio or input aspect. The local
admission policy allows 10% deviation from the nominal tier pixel area and 2%
from the aspect ratio; these tolerances are not provider output guarantees.
Optional modes do not require a multiple-of-16 pixel grid. S2V and video-edit
retain measured whole-media duration: declared duration must be within 0.1
seconds, and the quote uses the measured value, including fractional seconds.
S2V requires audio in the output. See the request schema for each mode's allowed
controls, media formats, roles and size bounds; unsupported controls or excess
references fail before submission.

Before submit, provide three pinned JSON declarations inside the project:

1. `PriceDeclaration`: selected model/resolution, currency, positive per-second
   price, caller principal and dated primary-source provenance.
2. `ModelAccessDeclaration`: the exact selected workspace origin/model,
   declared access, the same principal and dated workspace-source provenance.
3. `OperatorQuote`: pins to those declarations, the same price/origin/principal,
   absolute issue/expiry times, the request hash and selected contract hash.

The request hash uses the fully validated `GenerationRequest` JSON with only
`quote` omitted. Compute the contract hash as `digest(contract_for(request.model))`
for that validated request, using the model-specific contract in
[generation_request.py](https://github.com/Galbaz1/video-research-mcp/blob/v0.8.0-rc.6/packages/video-explainer-mcp/src/video_explainer_mcp/generation_request.py).
Both use the existing `planning_sources.digest` canonical JSON function. Pin the
finished quote in `request.quote`; set `max_cost`, `currency`,
`spend_authorized=true` and an explicit authorized submit operation. The flag
is an input acknowledgement; it does not establish actual human spending authority.
The declared price × admitted duration must fit the caller's bound; whole-media
modes use the measured input duration rather than the rounded declaration. Missing, expired,
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
within 0.1 seconds and one H.264 video plus the declared audio presence. Only explicitly admitted HTTPS result origins are accepted; other provider
origins are unsupported. Redirects are refused. Expired URLs, redirects, changed bytes and decode
errors retain failure or unknown status. Outputs bind the original script/scene,
request/source hashes, model, task ID and synthetic label. Inspect the returned
`state.asset` and `attestation`; file validity does not certify style, factual
accuracy or musical/visual quality.

Core `job_status` refuses this generated-media kind. Use
`explainer_generation_poll(job_id, operation)` for bounded readback/recovery.
Full security review and whole-programme acceptance remain open.
