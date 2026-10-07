# Current media routes — checked 2026-10-07

This dated routing snapshot describes provider contracts and useful existing
workflows. It does not establish an installed adapter, account access or artifact
quality. Before a call, inspect the live tool/API schema, model discovery, input
support, pricing and the cumulative production allowance. Reuse accepted assets
when they already satisfy the brief; use a new model only for a concrete need.

| Need | Current candidate and primary contract | Production handoff |
|---|---|---|
| Precise image generation/editing | [GPT Image 2.5 Sunburst](https://developers.openai.com/api/docs/models/gpt-image-2.5-sunburst), snapshot `gpt-image-2.5-sunburst-2026-09-08` | [image-generation](../../image-generation/SKILL.md); inspect reference fidelity and exact text |
| Faster image generation | [GPT Image 2.5 Flare](https://developers.openai.com/api/docs/models/gpt-image-2.5-flare), snapshot `gpt-image-2.5-flare-2026-09-08` | Same image workflow; audition against the actual quality requirement |
| Google image generation/editing | [Gemini Nano Banana 2.1](https://ai.google.dev/gemini-api/docs/models/gemini-nano-banana-2.1), stable `gemini-nano-banana-2.1`; card updated October 6 | Same image workflow; read current [image-generation contract](https://ai.google.dev/gemini-api/docs/image-generation) |
| Generated moving shot | [Gemini Omni 1.1 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-omni-flash), `gemini-omni-1.1-flash`, via [Interactions video guide](https://ai.google.dev/gemini-api/docs/omni) | [video-generation](../../video-generation/SKILL.md); inspect actual motion/audio |
| Audio/video review | [Gemini 3.8 Flash](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash), `gemini-3.8-flash`; audio/video inputs, text output | [video understanding](https://ai.google.dev/gemini-api/docs/video-understanding); supplemental critique with explicit sampling/coverage |
| Narration with alignment | `eleven_v4` through [speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps) | [tts-production](../../tts-production/SKILL.md) and [audition](narration-audition.md); only `stability` / `similarity_boost` v4 controls |

OpenAI Image API selection is described in [generate images](https://developers.openai.com/api/reference/resources/images/methods/generate).
Its Sora models and Videos API retired September 24, 2026, according to the
[deprecation record](https://developers.openai.com/api/docs/deprecations). Do not
route new video work through a retired Sora endpoint.

The current Omni provider contract records 3–10-second clips at native 720p/24fps;
the video guide identifies 1080p and 4K outputs as upscaled. An upscale does not
establish added scene detail or quality. Verify supported duration/resolution and
input limits for the selected operation, then probe the returned artifact.

## Preserve the actual Interactions response

For the current raw Google REST image/video responses, inspect `steps` entries
whose `type` is `model_output`, then their `content` items with `type` `image` or
`video`. Media items carry `mime_type` and base64 `data`; the [video guide](https://ai.google.dev/gemini-api/docs/omni)
also documents URI output. SDK convenience fields such as `output_video` are not
a universal REST envelope. Do not assume only `output_image` / `output_video`.

Preserve returned MIME type, usage and response metadata in the private execution
record. Current production readbacks included JPEG images; do not write those
bytes as PNG by changing the filename. Validate/decode according to the actual
format. A response with `store=false` may omit an interaction `id`; retain the
available request metadata and local correlation, without inventing a provider ID.
Unknown/partial responses remain unresolved and do not authorize duplicate spend.

## Authored geometry and motion

When accurate object relations or editable geometry matter, use the existing
[Blender research visualization](../../research-visualization-blender/SKILL.md)
route after its owned-session checks. Preserve authored geometry, source claims
and saved scene; inspect native transforms and rendered pixels separately.

ThreeJS or Remotion can serve an authored diagram/motion treatment only when the
chosen project's route is installed and supported. Inspect its version, entrypoint,
assets/fonts and export mechanism first; use [frame-based motion guidance](motion-and-rhythm.md)
for the existing Remotion route. This skill adds no renderer or ThreeJS tool.
Choose the route by explanatory need, then inspect actual playback and audio.
Model review, geometry readback and successful decode each leave perceptual gaps.
