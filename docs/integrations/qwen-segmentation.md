# Optional segmentation raster proposals

The owned `image_segment` entrypoint prepares one exact source-bound still
image and, with explicit workflow authority, submits one request to an
operator-configured SAM-compatible service. It preserves actual returned mask
and overlay PNG bytes, measures decoded pixels, and publishes a restart-verifiable
manifest. The bounded acceptance route uses a first-party HTTP mock fixture.
There is no bundled model, checkpoint, asset, font, launcher, GPU runtime, or SDK.

## Explicit selection and submission

`SEGMENTATION_SERVICES_JSON` configures `segmentation_services`. The default is
empty. Each operator profile contains:

| Field | Contract |
| --- | --- |
| `base_url` | Fixed endpoint prefix without userinfo, query, or fragment |
| `local` | Default `false`; `true` permits only literal `127.0.0.1` or `::1` |
| `origin` | Explicit `mock-fixture` or `model-service` |
| `api_key_env` | Optional environment variable name; its value is never in receipts |
| `declared_model` | Optional operator assertion, without load or identity attestation |
| `checkpoint_sha256` | Optional operator assertion, without byte or grant attestation |

Remote profiles require HTTPS and the existing transport's entirely public DNS
set, pinned address, and connected-peer proof. Local profiles use literal
loopback. The request cannot supply or override a URL, headers, credential, or
transport policy. A missing service or selected environment key refuses the
request. No service is launched, health-polled, installed, or downloaded.
Selection captures a separate validated profile snapshot. In-place endpoint or
origin changes during the request refuse publication instead of relabeling it.

`SegmentationRequest` requires `file_path`, the exact
`expected_source_sha256`, a non-whitespace `prompt` of at most 512 characters,
and an explicit slug `service_id`. Its defaults are `dry_run=true` and
`submission_authorized=false`. A dry plan prepares and verifies local artifacts
with zero HTTP. Submission requires both `dry_run=false` and an explicit
`submission_authorized=true` grant for that workflow.

The selected wire request is one POST to `<base_url>/segment`, containing
`image_b64`, the exact `prompt`, and `return_img=true`. A configured key adds
Bearer authentication only to that fixed endpoint. There is no retry or implicit
fallback. The unchanged `vision_http.exchange` retains HTTPX/HTTPCore/H11,
32 MiB request and 256 KiB raw response ceilings, a 120-second exchange deadline,
five-second joined cleanup, and refusal of proxies, redirects, unsafe DNS,
unproved peers, and compressed responses. Public errors contain fixed local
reasons without raw provider bodies, credentials, URL diagnostics, or transport
logs. Failure and cancellation join owned work and remove only that invocation's
staging outputs.

Missing optional Pillow returns `DEPENDENCY_MISSING` with a fixed instruction
to install `video-research-mcp[images]` in the server's Python interpreter; the
adapter does not install it automatically or expose raw import diagnostics.

## Original grid and actual raster evidence

Input uses the existing regular-file snapshot and local path fence. Symlinks,
FIFOs, URI paths, changed source bytes, and a wrong expected digest are refused.
The source is limited to 16 MiB and an unchanged grid of at most one million
pixels. Only single-frame still images are supported. Non-1 EXIF orientation is
explicitly unsupported; the operation does not silently normalize orientation,
resize, crop, select a video frame, or reinterpret mask coordinates.

Preparation uses the qualified Pillow helpers to encode an unscaled RGB PNG.
Metadata, profiles, and alpha are stripped; color management is unverified.
The receipt keeps the original stored-file identity and dimensions separately
from the prepared PNG's actual encoded and decoded-pixel hashes. The fixed RGB
PNG fixture retains its exact pixels and encoded body on the wire.

Responses must be JSON objects matching the exact prompt. Integer `num_masks`
must be from 0 through 16 and equal the actual result population. Each score is
finite, numeric, non-boolean, and from 0 through 1. Four finite, non-boolean
continuous `xyxy` corners must be ordered and within the original source grid.
Scores and corners retain their full supplied floating precision. The score is
an uncalibrated service declaration, and box/mask semantic correctness is
unverified.

Every mask must be strict Base64 containing one complete, CRC-valid,
single-frame PNG on the original grid. Only `L` or `1` binary masks are admitted;
decoded values must be 0/255 with nonempty foreground. The aggregate mask grid
ceiling is four million pixels. Actual encoded mask bytes are preserved. The
pixel SHA-256 is measured from canonical decoded `L` bytes; `stored_mode`
discloses `L` versus packed `1`. Foreground count, total pixels, and coverage are
measured from those pixels, without manufacturing a mask from a box or polygon.

Positive results require an actual returned source-size RGB/RGBA overlay PNG.
It receives the same complete PNG, single-frame, orientation, dimension, and
decoded-pixel checks. The returned bytes are preserved without replacing them
with a fabricated local overlay. Zero results are a valid **abstention** with
the actual prepared image artifact; they do not prove object absence.

The complete response population is validated before any returned mask or
overlay is published. Source identity is rechecked after HTTP and through
publication. Existing manifest limits remain unchanged: 1..64 explicit
artifacts, at most 8 MiB aggregate encoded artifacts, and a 128 KiB manifest.
The manifest binds original source, prepared PNG, actual masks/overlay,
request/operation hashes, origin, model-readiness caveats, and file identities.
`image_manifest_read` rehashes the source and every artifact after restart.
Native image delivery and text-only delivery use the same artifact identities
and shared bounded image transport.

## Readiness, provenance, and grants

Valid service output establishes the observed wire/image contract. It does not
attest model load, checkpoint identity, model rights, segmentation accuracy,
object absence, human review, or destructive-edit acceptance. A mock profile
explicitly records `not_used_mock_fixture` and `inference_used=false`. A
`model-service` profile remains `unattested_external_service`; its configured
model/checkpoint fields are operator assertions. The original launcher's
`health.status='ok'`, process-alive counts, and started workers do not establish
model-loaded readiness. Its loading/restart, queue, timeout/cancellation, and
cleanup limitations remain separate unresolved runtime evidence.

Requirements are independently adapted from
[Qwen-MM-Plugins](https://github.com/QwenLM/Qwen-MM-Plugins), pinned at
`07736672525443c7f8a3f6405eed37d2236f023f`, under the complete Apache-2.0 grant.
Its eight selected wrapper/reference bodies were source-qualified independently;
this implementation imports or copies none of the foreign application or
launcher code. The repository's third-party notices and reuse ledger retain the
exact wrapper grant and adaptation bindings.

Four official SAM3 bodies were retained as read-only declarations and coordinate
references at `facebookresearch/sam3@2345a4ad109ac29c569da749c91d84f10dc08c40`
(40,534 bytes, 827 lines). The governing
[custom SAM License](https://github.com/facebookresearch/sam3/blob/2345a4ad109ac29c569da749c91d84f10dc08c40/LICENSE)
is separate from Qwen's Apache grant; the package's MIT classifier does not
replace that complete license. The public Hugging Face metadata pin
`3c879f39826c281e95690f02c7821c4de09afae7` declares manual gating. The retained
unauthenticated model-card GET returned HTTP 401. The gated model card,
checkpoint bytes and their access/grant commitments remain unread or unresolved.
No access request, authenticated fetch, weight download, redistribution, SAM,
Torch, GPU execution, or live model service is admitted by mock acceptance.
Service-operator terms and source-image/upload authority are separate boundaries.

## Verification boundary

The fixed first-party controls use a 32x24 RGB source, a 192-pixel binary mask
with 0.25 coverage and box `[8,6,24,18]`, score 0.875, and an actual returned
overlay with foreground `[225,55,28]` and background `[40,60,80]`. Unit checks
exercise source and raster refusal, exact bytes/pixels, complete populations,
native/text transport, restart tampering, and joined cleanup through mocked
DNS/connect boundaries while retaining HTTPX/HTTPCore/H11. They use no live
socket, model, asset download, install, heldout input, or human/model accuracy
claim. Root's sole independent review and fixed packaged 20-control journey are
distinct gates; source/unit readiness does not substitute for those results.

The accepted offline candidate passed the frozen twenty-control extracted-wheel
journey on its first attempt: 64 public calls (63 MCP client calls and one direct
public cancellation check), 46 written mock HTTP requests and zero real socket
attempts. Root independently rehashed 318 retained files and 2,717 loaded-file
bindings. All 3,210 root tests and required lint/installer/security/baseline/reuse/
release-contract checks passed. One original review found the mutable-profile
provenance defect; the public regression failed original code, and the validated
snapshot repair passed affected checks. Original primary and root verification
failures remain retained. These checks qualify the adapter contract, rather than
model load, segmentation semantics, live service, human audit or comparisons.
