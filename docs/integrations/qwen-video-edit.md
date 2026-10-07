# Optional pinned Qwen image and video generation

This integration selects the external `video-edit` package from
[QwenLM/Qwen-MM-Plugins at 07736672525443c7f8a3f6405eed37d2236f023f](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/video-edit).
The [descriptor](../../integrations/qwen/video-edit.json) contains the actual
stdio `tools/list` argument schemas, source hashes, mode/model mapping and guards.
It stays disabled by default. No upstream generation code, SDK, assets or weights
are copied or imported into the research core.

The exact source process initialized and listed six tools on 7 October 2026:
`qwen_image`, `wan_t2v`, `wan_s2v`, `happyhorse`, `qwen_tts`, and `minimax_tts`.
Its native identity was `qwen_mm_plugins_video_edit` version `1.1.0`, protocol
`2025-03-26`. Discovery performed zero provider submissions and no tools/call;
the process exited 0 and was reaped. A Python audit guard denied socket/DNS and
ancillary process operations; OS-wide egress enforcement remains unverified.
The last two tools were inspected for import closure but are outside this
image/video assignment.

The selected existing cache runtime used CPython 3.13.12, MCP 1.27.1, Pydantic
2.13.4, AnyIO 4.13.0 and docstring-parser 0.18.0. DashScope and requests were
absent. The separately supplied prior API environment also lacks both extras.
Native provider mode samples are **UNRUN**. Source-handler tests use explicit
mock SDK/HTTP boundaries; they do not establish SDK availability or live quality.
Prior API/other-package receipts do not qualify this video-edit package.

## Manual selection and readiness

The pinned console entry is `qwen-mm-plugins-video-edit`, resolving
`qwen_mm_plugins_video_edit.__main__:main`; the equivalent source entry is:

```bash
PYTHONPATH="/selected/qwen/src:/selected/qwen/src/capabilities/video-edit" \
QWEN_MM_CONFIG="/selected/private/nonexistent-config" \
QWEN_MM_NATIVE_MODE=true \
  /selected/compatible-runtime/bin/python -m qwen_mm_plugins_video_edit
```

The paths are operator selections, not installed paths supplied by this project.
Select and verify the exact revision and a separate runtime before launch.
Upstream declares Python >=3.10, MCP >=1,<2, AnyIO >=4,<5, Pydantic >=2.11,<3,
docstring-parser >=0.18,<0.19, Pillow <12 and OpenAI >=1,<2; its video-edit extra
adds `dashscope>=1.25.16` and `requests`. Core startup must never install these.
FFmpeg/ffprobe are needed for subsequent artifact verification, not discovery.
Do not run upstream `--setup`, `--set` or `--unset` as readiness actions.

Discovery needs no provider key. Actual DashScope operations require
`DASHSCOPE_API_KEY` through the selected environment and explicit authority for
that operation, source/reference submission, account and spending bound.
`DASHSCOPE_BASE_URL` affects the native API origin; validate the exact selected
origin before any request. Keep `QWEN_MM_CONFIG` isolated and native mode true.
Readiness grants no generation, detection, upload or local-model authority.

## Exact mode contracts

| Tool / mode | Handler model and inputs | Execution |
| --- | --- | --- |
| qwen_image / text_to_image | `qwen-image-2.0-pro`; nonempty prompt | Synchronous SDK call |
| qwen_image / image_edit | `qwen-image-2.0-pro`; prompt and 1–3 `image_urls` | Synchronous SDK call; excess images silently dropped upstream |
| qwen_image / image_translate | `qwen-mt-image`; one image, `source_lang`, `target_lang` | Async submit; polls every 3s for 120s; uses only the first image |
| wan_t2v / text_to_video | `wan2.7-t2v`; prompt, size preset, duration | Blocking SDK call; no exposed polling deadline |
| wan_t2v / first_frame | `wan2.7-i2v`; prompt and `first_frame_url` | Sends first-frame media and resolution tier |
| wan_t2v / first_last_frame | `wan2.7-i2v`; prompt and both frame URLs | Sends ordered first/last media and resolution tier |
| wan_s2v / detect | `wan2.2-s2v-detect`; portrait `image_url` | Synchronous face-detect POST; upstream claims billing even for a negative result |
| wan_s2v / generate | `wan2.2-s2v`; portrait and `audio_url` | Async submit; default 15s interval, 700s timeout; interval clamped to >=5s |
| happyhorse / text_to_video | `happyhorse-1.0-t2v`; prompt | Async submit; default 15s interval, 600s timeout |
| happyhorse / image_to_video | `happyhorse-1.0-i2v`; `image_url`, optional prompt | First-frame media; ratio follows image, ignores ratio argument |
| happyhorse / reference_to_video | `happyhorse-1.0-r2v`; prompt and 1–9 ordered reference images | Prompt references `[Image 1]` etc.; excess images silently dropped |
| happyhorse / video_edit | `happyhorse-1.0-video-edit`; prompt, video, 0–5 reference images | Ignores duration/ratio; `audio_setting` auto/origin; excess references dropped |

Wan size presets are `1280*720`, `720*1280`, `960*960`, `1024*1024`, and
`1920*1080`. The legacy square maps to `960*960`; image modes send only 720P or
1080P and take aspect/dimensions from the first frame. The upstream Wan docstring claims
2–15s duration and seed 0–2147483647; those bounds are not enforced by its argument
model. The upstream HappyHorse docstring claims 3–15s generation, 720P/1080P and nine ratio enums;
duration/seed/media limits likewise need validation before spend. Wan-S2V's
schema permits 480P/720P; its upstream docstring claims the requirement for a single clear front-facing
portrait and WAV/MP3 audio under 15MB and 20s. Upstream describes detection as a separately billed
operation; that billing rule is not independently verified. It is never dependency verification.

The HappyHorse video-edit docstring permits 3–60s inputs but says inputs over
15s are automatically truncated to the first 15s. Reject an over-15s whole-video
request before submission; preserve any explicitly selected source interval.
Do not silently shorten, resize, discard anchors or ignore required intent.

## Required operating guards and output evidence

Keep every native Qwen paid call disabled, including text-to-video. The separate
explainer `explainer_generation_submit/poll/cancel` route protects only its own
`wan2.7-t2v` HTTP calls; it supplies no guard for `wan_t2v`, HappyHorse or other
Qwen tools. The [official Wan text-to-video reference](https://www.alibabacloud.com/help/en/model-studio/text-to-video-api-reference)
explicitly excludes Wan2.7 from SDK support. The pinned Qwen Wan handler uses the
SDK, so its source mapping conflicts with that documented support boundary.

There is no `transparent_background` field in the upstream image schema.
An alpha-required request is unsupported: preserve the intent in the durable
request receipt and reject before submit. A PNG extension or prompt mentioning
transparency does not establish an alpha channel. Reference counts must be checked
before calling upstream to prevent its silent drops. Exact mode schemas describe
accepted fields; they do not validate all provider limits, URL origins, decoded
media, identity/style continuity or source authority.

The shared generation helper retries transient failures with up to 10 inner
attempts and throttling with up to four outer attempts (linear 1s backoff;
throttle exponential 2s with up to 1s jitter). Submit retries have no demonstrated
idempotency guarantee and can duplicate billed generation. Polling retains a
provider task ID on timeout but a GET/retry can overrun the nominal deadline.
Keep a submitted/unknown job occupied and reconcile it; never invoke a generation
mode again to resume. This package has no public cancel, standalone poll/resume
or durable operation store. Durable selected-provider submit/resume/cancel and final artifact verification
remain separately unqualified; no verified complementary operator guide is bound here.

Outputs are text blocks containing URLs, optional provider usage and sometimes
a saved path; errors use `Error:` text and may lack protocol `isError`. HappyHorse
and Wan-S2V print task IDs on success/failure/timeout. Image translation prints
its ID on timeout, but omits it on success and provider failure; synchronous
image/Wan output omits it. A later exception can lose an already submitted ID.
Wan duration/size text describes the request, and optional usage is provider
reported. Neither is decoded output metadata.

Upstream docstrings claim generated URLs expire after 24h; expiry behavior is
unqualified. `save_url_to_dir` raises HTTP errors, retries, buffers the response
without a byte ceiling and skips an existing destination without validation.
Its URL/request-derived filenames are not content hashes. Do not accept URL-only
or merely saved output as a final artifact. A durable handoff must bind request,
model/job, script/scene, synthetic label, exact source/reference hashes, identity/
style anchors and continuation settings, then bounded-download, hash and fully
decode the result with measured dimensions, duration and audio. Failed/expired
URLs and incomplete decode retain failure; missing metadata remains unknown.

## Reuse and acceptance boundary

The exact root [Apache-2.0 grant](https://raw.githubusercontent.com/QwenLM/Qwen-MM-Plugins/07736672525443c7f8a3f6405eed37d2236f023f/LICENSE)
was retained with SHA256
`cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`.
Selected original wrapper/helper/skill files were checked against the complete
pinned tree and their own bodies; no overriding notice/license applies in their
selected ancestors. This descriptor, documentation and the two integration
skills are independently authored; upstream bytes remain private and unmodified.
Fonts, JS, media, model weights, runtime dependencies and provider terms have
separate grants and are not bundled or qualified here.

Verified behavior is limited to exact argument schemas, source-handler mocks
and provider-free six-tool discovery. Native SDK availability, reliable job
recovery, output decoding, style/identity continuity, live provider quality and
full security review remain unqualified. The external integration stays disabled;
these checks do not establish a completed production workflow.
