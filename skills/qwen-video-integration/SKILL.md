---
name: qwen-video-integration
description: Select the optional pinned external Wan 2.7, Wan 2.2 portrait/audio and HappyHorse video-edit tools, checking exact modes, reference drops, truncation and generation retry limits before authorized submission.
---

## Installed resources

For the Claude installer layout, read
`../video-research-resources/docs/integrations/qwen-video-edit.md` and
`../video-research-resources/integrations/qwen/video-edit.json`.
The repository-relative links below apply in a source checkout or unpacked npm
package. Installing these resources does not activate the external integration.

Read [Qwen video-edit](../../docs/integrations/qwen-video-edit.md) and the
[exact schemas](../../integrations/qwen/video-edit.json). Source:
QwenLM/Qwen-MM-Plugins at `07736672525443c7f8a3f6405eed37d2236f023f`,
package `video-edit`. This independently authored skill references Apache-2.0
original wrappers/skills; upstream code, assets and weights are not bundled.

Verify the external source, private compatible runtime and grants. Launch
`qwen-mm-plugins-video-edit` or `python -m qwen_mm_plugins_video_edit` over
stdio with isolated `QWEN_MM_CONFIG` and `QWEN_MM_NATIVE_MODE=true`. Discovery
must make zero generation/detection submits. Actual six-tool discovery passed;
native provider samples remain UNRUN because DashScope/requests are absent in
the inspected runtimes. Prior Qwen API evidence does not qualify these modes.

| Requested operation | Exact tool / selector | Required anchors |
| --- | --- | --- |
| Text video | `wan_t2v`, mode `text_to_video`, model wan2.7-t2v | Prompt |
| First frame | `wan_t2v`, mode `first_frame`, model wan2.7-i2v | Prompt and first_frame_url |
| First and last frames | `wan_t2v`, mode `first_last_frame`, model wan2.7-i2v | Prompt and both ordered frame URLs |
| Portrait readiness | `wan_s2v`, action `detect`, model wan2.2-s2v-detect | Portrait; upstream claims billing even for a negative result |
| Portrait lip sync | `wan_s2v`, action `generate`, model wan2.2-s2v | Portrait and audio |
| HappyHorse text | `happyhorse`, mode `text_to_video`, model happyhorse-1.0-t2v | Prompt |
| HappyHorse image | `happyhorse`, mode `image_to_video`, model happyhorse-1.0-i2v | Image; optional prompt |
| HappyHorse references | `happyhorse`, mode `reference_to_video`, model happyhorse-1.0-r2v | Prompt and 1–9 ordered images |
| HappyHorse edit | `happyhorse`, mode `video_edit`, model happyhorse-1.0-video-edit | Prompt, video and 0–5 optional images |

Before spend, validate the selected mode's actual duration/resolution/aspect and
anchor constraints, reference bytes/hashes and URL origin. Reject excess images;
upstream silently drops them. Wan's 1024*1024 preset maps to 960*960; image
modes send only the resolution tier and follow the first image's aspect. Wan
2.7 declares 2–15s; HappyHorse generation declares 3–15s. These duration bounds
are docstring claims, not Pydantic enforcement or live catalog qualification.
The upstream Wan-S2V docstring claims voice WAV/MP3 under 15MB/20s and a clear single portrait.

HappyHorse image mode ignores ratio. Video-edit ignores ratio and requested
duration, follows its source and may truncate inputs over 15s. Reject over-15s
whole-video intent before dispatch; record any authorized exact selected interval.
Use audio_setting auto/origin only for HappyHorse edits. Unsupported anchors,
alpha-required intent or missing provider limit metadata block submission.

An actual call needs specific source/voice/reference/account/spend authority and
`DASHSCOPE_API_KEY` from the selected environment. The separate `explainer_generation_submit/poll/cancel` route supports only
`wan2.7-t2v`. Its guards cover no native Qwen call, including `wan_t2v` text
generation or HappyHorse. Keep all native Qwen paid calls disabled until their
own durable intent/recovery guards and runtime are qualified. The official
Wan2.7 text-to-video reference excludes Wan2.7 from SDK support; the pinned Qwen
Wan wrapper uses that SDK, so its source mapping is not a working live route. SDK/POST retries lack demonstrated
idempotency; never reissue generation after interruption/timeout/unknown effect.
Wan's SDK call has no exposed poll deadline. Wan-S2V defaults to 15s/700s,
HappyHorse to 15s/600s, both clamp interval to >=5s; retrying GETs can overrun
nominal deadlines. Upstream has no public cancel or standalone poll/resume tool.

Retain task/model/source/reference/script/scene identity, synthetic label,
identity/style anchors and continuation settings across handoff. Text task IDs
and optional provider usage are not durable operation IDs or measured metadata.
Require bounded download, actual output SHA256 and full decode with measured
video dimensions, duration and audio before accepting an artifact. Saved paths
and URL-only results do not establish that evidence. Durable receipts, recovery and final artifact qualification remain unqualified;
preserve all failed and untested modes.
