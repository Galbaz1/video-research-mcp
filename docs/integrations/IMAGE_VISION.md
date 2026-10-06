# Configured image and video vision

`vision_chat`, `vision_ocr` and `vision_grounding` provide bounded model analysis,
comparison, text inference and proposed object regions. `image_ocr` remains the
separate local OCR/QR/document-geometry operation. A successful model response
establishes neither text accuracy nor object correctness.

Every request supplies an instruction and one to four exact local sources, each
with `file_path` and `expected_source_sha256`. Select `kind: image`, a precise
`kind: frame` with `time_seconds`, or `kind: video` with a bounded interval, FPS
and frame count. Image/frame crops and resizes retain inverse matrices to the
original oriented and stored pixels. Each video source defaults to 16 sampled
frames, with `max_frames` capped at 32 and `fps` in 0.1..10, default 1. The complete
request admits at most 32 sampled images and 8 MiB of raw image bytes; the 10 MB
encoded per-item limit is implementation policy. Sampling does not establish
continuous watched coverage or audio understanding.

```json
{
  "request": {
    "sources": [
      {"file_path": "/allowed/source-a.png", "expected_source_sha256": "<sha256>"},
      {"file_path": "/allowed/source-b.png", "expected_source_sha256": "<sha256>"}
    ],
    "instruction": "Compare the visible labels and cite each source index.",
    "backend": "gemini",
    "dry_run": true
  }
}
```

Dry run performs local preparation and returns original/prepared hashes, actual
frame clocks, selected origins and planned call limits. It makes zero count,
upload or inference calls and omits credentials/base64. Returned local view
manifests can be opened through `image_manifest_read`. Failed or cancelled
workflows remove only their own newly created views and join local/HTTP cleanup.
Successful views and crops remain available for a later manifest readback.

Submission requires `dry_run: false` and the current workflow's explicit
`authorize_submission: true`. The invoking human must authorize the chosen source
transmission and provider spending; the boolean does not manufacture that authority.
No automatic retry, fallback, answer cache, model download or knowledge-store
write occurs. Changes to endpoint/model/credential/configuration during a workflow
fail, retaining attempted calls and storage uncertainty. Source and transmitted
payload bytes are checked before and after inference and after crop extraction.

## Backend configuration

The default `gemini` route uses the existing configured Gemini client. It counts
the exact prepared inputs, reserves schema bytes plus output tokens and issues
one generation with SDK retries disabled. Its plan needs two provider calls.
Unknown token count prevents generation; truncation, non-STOP termination or an
observed reservation overrun fails without retry. Usage and charge uncertainty
remain separate from these bounds.
The request digest binds the selected account through a credential hash and the
effective sampling temperature. That same account is passed to the SDK client;
changes between counting and generation fail before generation. Models without
sampling support omit temperature, so an unused temperature setting does not
change the request identity.

`VISION_BACKENDS_JSON` configures optional compatible chat endpoints. Requests
select a profile name; they cannot replace an endpoint, account credential or
capability declaration. For example:

```json
{
  "local": {
    "base_url": "http://127.0.0.1:1234/v1",
    "model": "operator-selected-installed-model",
    "local": true,
    "capabilities": ["images", "video", "structured_json"],
    "structured_format": "json_object"
  }
}
```

A selected local endpoint must use literal `127.0.0.1` or `::1`. Remote endpoints
require HTTPS, entirely public DNS answers, pinned peer IP/port and the original
Host/TLS hostname. Requests disable redirects, proxy environment and retries.
Transport logs are suppressed only for the calling exchange. Bodies and raw
responses have 32 MiB/256 KiB ceilings. One workflow deadline, configured by
`MEDIA_ACQUIRE_TIMEOUT_SECONDS` and capped at 120 seconds, covers preparation,
uploads, inference and verification. HTTP exchanges also have a 120-second
deadline and at most five seconds of separate, joined cleanup. These
controls are tested against the installed transport with mocked socket/TLS
boundaries; live provider interoperability is unverified.

Set `api_key_env` to a server-selected environment-variable name ending in
`API_KEY` for the credential of that exact origin. Compatible endpoints must
declare `images` and `structured_json`, plus `video` for video requests. Set
`structured_format: json_schema` only when the selected service supports it.
Capability declarations establish routing eligibility; they do not prove model
vision quality, weight licensing or local inference. A local server can forward
work to another service. Local profiles require a separately operated service,
installed model and qualified runtime; this adapter starts or installs none of
them. No actual input-token or dollar ceiling is established
for compatible image inputs. One chat call is bounded; numeric provider token
usage is retained when supplied, and unknown usage remains unknown.

## Original PNG with native Ollama

An explicitly selected `ollama_plain` profile uses the local Ollama `/api/chat`
endpoint. The profile requires a literal loopback origin, `local: true` and
`capabilities: ["images"]`, with no credential or upload policy:

```json
{
  "ollama": {
    "protocol": "ollama_plain",
    "base_url": "http://127.0.0.1:11434",
    "model": "operator-selected-installed-model",
    "local": true,
    "capabilities": ["images"]
  }
}
```

This route accepts one original PNG in `vision_chat`. It holds an exact snapshot
through inference and sends the original bytes and literal instruction without
an image conversion or JSON/schema prompt wrapper. Frame/video sources, explicit
crop/resize/time settings, custom schemas, crop export, OCR/grounding and explicit
`thinking_level` are refused before preparation. The PNG header is checked for
bounded dimensions and CRC; this establishes neither full image decoding nor
model suitability.

The native request sets `num_predict` to the request's output-token limit,
`num_ctx: 4096`, `temperature: 0`, `think: false`, `stream: false` and
`keep_alive: 0`. Its request ceiling is 1 MiB. The 128 KiB receive ceiling includes
HTTP headers and framing; the connected stream must prove the guard is present
before transmission. Controlled loopback exchanges verify these limits and
joined cleanup. Plain text is returned as `model_output.answer` with an empty
region list. An incomplete answer, a different model echo, observed thinking or
an output count above the requested limit fails without retry. Only bounded
numeric/enum/boolean response metadata is exposed.

Dry plans and actual responses retain protocol, model, endpoint, effective
controls, original PNG identity and exact serialized request/response body
hashes. Those hashes describe JSON bodies, not TCP/TLS framing. Model installation,
weight identity, host capacity, observed inference quality and total input/context
usage require separate runtime evidence. This route downloads no model and does
not establish general video, OCR or grounding acceptance. Existing compatible
profiles keep their earlier request-digest representation.

## Grounding and object crops

The model returns an answer and up to16 regions with `source_index`, `label` and
strict normalized1000 `[left, top, right, bottom]` corners relative to the exact
prepared image. Booleans, numeric strings, nonfinite/reversed/out-of-bounds corners
and ambiguous video regions fail. An empty region list is a valid abstention.
Geometry is mapped through preparation matrices to the original oriented and
stored coordinates. `export_crops: true` on `vision_grounding` extracts the
outward-rounded original-pixel crop with its source hash, clock, transform and
output manifest. The exported bytes and coordinate mapping can be verified;
the label and proposed location remain model inference.

Custom JSON schemas are supported only by `vision_chat` without crop export.
They require the optional strict-schema dependency and complexity/JSON validation.
Model-derived text/regions never become authoritative observations automatically.

## Explicit temporary video route

A profile may expressly choose `video_delivery: dashscope_temporary`. Its exact
selected official DashScope account origin must supply `api_key_env` and the same
origin's `upload_policy_url: https://<selected-host>/api/v1/uploads`. This route
sends the full original MP4, capped at24MiB and the configured
`max_video_seconds` (default120, maximum7200). Intervals require sampled frames.

The plan needs three calls per video: selected-account/model policy GET,
policy-bound OSS multipart upload, then the selected inference endpoint. The
inference key goes only to the selected policy/inference origin; it is absent
from the OSS upload. No automatic upload/fallback occurs from a sampled profile.
A failed upload or later generation retains the attempt, exact source hash and
unknown storage outcome; no automated deletion/retention guarantee is supplied.

[Official temporary-storage documentation](https://www.alibabacloud.com/help/en/model-studio/get-temporary-file-url)
describes same-account/model binding and48-hour URL expiry. Expiry is provider
documentation, not measured data deletion. Its regional prose and examples differ;
regional availability remains unverified. Current model-specific service limits
must be checked with separate account/source/spend authority before a live run.

## Source and evidence boundary

This is independently authored implementation from the pinned Qwen API and
Omni image workflow requirements. See the [reuse ledger](reuse-ledger.json),
[notices](../../THIRD_PARTY_NOTICES.md) and [isolated Qwen API route](qwen-api.md).
No foreign source body, model weight, image, font or upstream dependency is added
to the core environment. Development mocks and exact local pixels establish
request/geometry/ownership contracts, not provider quality, human acceptance,
comparative advantage or release publication.
