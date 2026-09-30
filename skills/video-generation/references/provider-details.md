# Video Provider Reference

Verified against primary documentation on 2026-09-29. Re-check availability and pricing before paid execution; this reference does not describe an installed MCP server.

## Gemini Omni Flash

The current stable video model is `gemini-omni-1.1-flash`. [Its model card](https://ai.google.dev/gemini-api/docs/models/gemini-omni-flash) documents conversational generation/editing through Interactions, text/image/video inputs (up to 10 seconds for edits/extensions), and 3–10 second outputs at 360p/720p/1080p/4K. Read the linked generation guide before preparing a request; a Veo connector cannot be assumed to expose Omni.

## Veo through the Gemini API

The current [Google Veo guide](https://ai.google.dev/gemini-api/docs/veo) documents `veo-3.1-generate-preview`, `veo-3.1-fast-generate-preview`, and `veo-3.1-lite-generate-preview`. These are preview models, with one video per request. Use Fast for a bounded draft when its capabilities fit; select Standard or Lite based on the actual shot requirements and live price.

- Standard/Fast: text, image, and video inputs; 720p, 1080p, or 4K output; generated audio.
- Lite: text/image inputs; 720p or 1080p. Do not assume extension support.
- Duration is 4, 6, or 8 seconds. Reference images, 1080p, and 4K require 8 seconds.
- Veo 3.1 supports up to three asset references. `reference_type="asset"` preserves subject assets; do not assume a `style` reference mode.
- Extensions accept previously generated Veo video and produce 720p. A local arbitrary MP4 is not automatically an eligible extension input.
- Generation is asynchronous: retain the returned operation, poll to completion, check failure/filter results, and download the actual returned video. Provider retention is limited; save successful output promptly.

The SDK entry point is `client.models.generate_videos(...)`, with options in `types.GenerateVideosConfig`. Read the official examples for the selected input mode. Connector parameter names may differ; inspect their schema. Current costs and limits live in [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing) and the [Veo guide](https://ai.google.dev/gemini-api/docs/veo).

## Sora retirement

OpenAI lists the Videos API, `sora-2`, and `sora-2-pro` as removed on **2026-09-24**, with no replacement listed. Do not launch new Sora jobs or depend on a local Sora helper. Preserve existing downloaded clips for reuse. Source: [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations).

## Provider-independent QA

```bash
ffprobe -v error -show_entries format=duration:stream=width,height,codec_name,r_frame_rate -of json clip.mp4
ffmpeg -i clip.mp4 -vf "fps=1,scale=320:-1,tile=6x5" -frames:v 1 contact-sheet.jpg
```

A contact sheet samples the image sequence; it cannot prove motion or audio quality. Watch/listen to the accepted clip and inspect suspicious timestamps at full resolution. Keep model, prompt, operation ID, settings, references, measured properties, and QA decisions with each output.
