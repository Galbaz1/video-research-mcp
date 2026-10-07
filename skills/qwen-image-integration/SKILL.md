---
name: qwen-image-integration
description: Select the optional pinned external Qwen video-edit image tools for text generation, editing or image translation; check unsupported alpha intent and preserve source and result evidence before any authorized provider call.
---

## Installed resources

For the Claude installer layout, read
`../video-research-resources/docs/integrations/qwen-video-edit.md` and
`../video-research-resources/integrations/qwen/video-edit.json`.
The repository-relative links below apply in a source checkout or unpacked npm
package. Installing these resources does not activate the external integration.

Use the disabled optional integration documented in
[Qwen video-edit](../../docs/integrations/qwen-video-edit.md) and its
[exact schema descriptor](../../integrations/qwen/video-edit.json).
Source: QwenLM/Qwen-MM-Plugins at
`07736672525443c7f8a3f6405eed37d2236f023f`, package `video-edit`.
This skill is independently authored against Apache-2.0 original wrapper/skill
contracts; it copies no upstream code, assets or weights.

1. Verify the pinned external source, selected private compatible runtime and
   grants. The entry is `qwen-mm-plugins-video-edit` or
   `python -m qwen_mm_plugins_video_edit` over stdio. Isolate `QWEN_MM_CONFIG`;
   keep `QWEN_MM_NATIVE_MODE=true`. Discovery needs no key and must not generate.
   Observed discovery is six tools, server version 1.1.0; native provider samples
   remain UNRUN because the tested runtimes lack DashScope/requests.
2. Read the actual `qwen_image` schema. `text_to_image` and `image_edit` use
   `qwen-image-2.0-pro`; `image_translate` uses `qwen-mt-image`. Require a prompt
   for generation/editing, 1–3 images for editing and exactly one for translation.
   Preserve reference ordering and source hashes; reject overflow before upstream
   silently drops images. Translation uses language fields and ignores generation
   size/seed/prompt parameters.
3. Reject alpha-required intent before submit: the schema has no transparent
   background field. Preserve the unsupported request in the durable receipt.
   PNG filenames and prompt words supply no alpha proof. Validate real provider
   size/count limits and reference availability before any spending.
4. Obtain exact operation/source-submission/account/spend authority and verify
   selected origin and `DASHSCOPE_API_KEY` environment delivery. No install,
   upload or generation follows from readiness. The selected durable video route does not support these image modes.
   Keep paid calls disabled until durable intent/recovery guards are qualified.
5. Keep task/model/request/reference/script/scene identity, synthetic label,
   anchors and continuation settings. Shared submit/SDK retries lack guaranteed
   idempotency; a timeout or unknown effect requires reconciliation, never a
   new generation call. Translation polls at 3s/120s and prints its task ID only
   on timeout, so retain provider identity outside the text formatter.
6. Require bounded download, actual content hash and full decoded image metadata
   before accepting a final asset. URL-only output, upstream saved-path strings
   and request/URL-derived filenames are insufficient. Retain failed/expired URL
   evidence and unknown metadata. Durable receipts and final artifact acceptance remain separately unqualified.

Source mocks demonstrate contract behavior, not installed SDK availability,
provider quality, durable recovery, alpha support or whole-feature acceptance.
