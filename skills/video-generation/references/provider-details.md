# Provider Details Reference

Full tool references, model IDs, camera reliability data, and provider-specific rules for Veo and Sora video generation.

## Veo Tool Reference

### generate_video

Text prompt to video generation.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `prompt` | string | Yes | -- | Text description of the scene |
| `model` | string | No | `veo-3.1-generate-preview` | Model ID |
| `aspect_ratio` | string | No | `"16:9"` | `"16:9"` or `"9:16"` |
| `duration_seconds` | string | No | `"8"` | `"4"`, `"6"`, or `"8"` |
| `resolution` | string | No | `"1080p"` | `"720p"` or `"1080p"` |
| `negative_prompt` | string | No | -- | Exclusions (always include default block) |
| `number_of_videos` | int | No | 1 | 1-4 variants |

```json
{
  "prompt": "Medium shot, 35mm lens look. Industrial control panel with brushed metal...",
  "model": "veo-3.1-generate-preview",
  "aspect_ratio": "16:9",
  "duration_seconds": "8",
  "resolution": "1080p",
  "negative_prompt": "motion blur, face distortion, warping...",
  "number_of_videos": 3
}
```

### animate_image

Static image to animated video.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `prompt` | string | Yes | -- | Animation description |
| `image_path` | string | Yes | -- | Absolute path to source image |
| `model` | string | No | `veo-3.1-generate-preview` | Model ID |
| `aspect_ratio` | string | No | `"16:9"` | `"16:9"` or `"9:16"` |
| `duration_seconds` | string | No | `"8"` | `"4"`, `"6"`, or `"8"` |
| `resolution` | string | No | `"1080p"` | `"720p"` or `"1080p"` |
| `negative_prompt` | string | No | -- | Exclusions |
| `last_frame_path` | string | No | -- | End frame for interpolation |

### extend_video_clip (Veo 3.1 only)

Extend an existing video with new content. Continues from the last second.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `prompt` | string | Yes | -- | Description for the extension |
| `video_path` | string | Yes | -- | Absolute path to source video |
| `model` | string | No | `veo-3.1-generate-preview` | Must be Veo 3.1 |
| `aspect_ratio` | string | No | `"16:9"` | Must match source |
| `duration_seconds` | string | No | `"8"` | Extension duration |
| `resolution` | string | No | `"1080p"` | Must match source |
| `negative_prompt` | string | No | -- | Exclusions |

### generate_video_with_style (Veo 3.1 only)

Generate video with 1-3 reference images for style/character consistency.

| Parameter | Type | Required | Default | Notes |
|-----------|------|----------|---------|-------|
| `prompt` | string | Yes | -- | Video description |
| `reference_image_paths` | list[string] | Yes | -- | 1-3 absolute image paths |
| `reference_types` | list[string] | No | all `"asset"` | `"asset"` or `"style"` per image |
| `model` | string | No | `veo-3.1-generate-preview` | Must be Veo 3.1 |
| `aspect_ratio` | string | No | `"16:9"` | `"16:9"` or `"9:16"` |
| `duration_seconds` | string | No | `"8"` | `"4"`, `"6"`, or `"8"` |
| `resolution` | string | No | `"1080p"` | `"720p"` or `"1080p"` |
| `negative_prompt` | string | No | -- | Exclusions |
| `number_of_videos` | int | No | 1 | 1-4 variants |

Reference type semantics:
- `"asset"` -- content matching, preserves composition and subject identity
- `"style"` -- tonal consistency, preserves palette, grain, and lighting without copying layout

### list_veo_models

List available Veo models and their capabilities. No parameters.

## Veo Model IDs

| Model | ID | Features | Best for |
|-------|----|----------|----------|
| Veo 3.1 Preview | `veo-3.1-generate-preview` | All tools, highest quality | Final takes |
| Veo 3.1 Fast | `veo-3.1-fast-generate-preview` | All tools, faster | Drafts, iteration |
| Veo 3.0 | `veo-3.0-generate-001` | generate_video, animate_image, native audio | Stable production |
| Veo 3.0 Fast | `veo-3.0-fast-generate-001` | generate_video, animate_image | Fast production |
| Veo 2.0 | `veo-2.0-generate-001` | generate_video, animate_image | Basic, cheapest |

## Veo Default Negative Prompt

ALWAYS pass this block via `negative_prompt`. Merge with any user-specified exclusions:

```
motion blur, face distortion, warping, morphing, duplicate limbs, inconsistent lighting, background shifting, floating objects, blurry textures, oversmoothed skin, plastic sheen, glowing artifacts, flickering, temporal inconsistency, subtitle, watermark, text overlay, oversaturated
```

Only skip if the user explicitly opts out.

## Veo Output

Videos saved to: `~/Videos/veo-generated/`

Return format:
```json
{
  "status": "success",
  "videos": [
    {
      "path": "/abs/path/to/video.mp4",
      "duration_seconds": 8,
      "model": "veo-3.1-generate-preview"
    }
  ]
}
```

Videos remain on Google servers for **2 days** -- download promptly.

## Sora API Reference

Script path: `/Users/fausto_home/.claude/skills/sora/scripts/sora_direct.py`

Run with: `uv run --with requests python <script> <command> [args]`

### create-and-poll

Generate a video and wait for completion.

```bash
uv run --with requests python /Users/fausto_home/.claude/skills/sora/scripts/sora_direct.py create-and-poll \
  --model sora-2-pro \
  --prompt-file prompt.txt \
  --size 1920x1080 \
  --seconds 4 \
  --input-reference image.png \
  --download \
  --variant video \
  --out out.mp4 \
  --json-out out.json
```

| Flag | Required | Default | Notes |
|------|----------|---------|-------|
| `--model` | No | `sora-2` | `sora-2` or `sora-2-pro` |
| `--prompt` | One of | -- | Inline prompt text |
| `--prompt-file` | One of | -- | Path to prompt file |
| `--size` | No | `1280x720` | `WxH` (e.g., `1920x1080`, `1080x1920`) |
| `--seconds` | No | `4` | Duration in seconds |
| `--input-reference` | No | -- | Source image for I2V |
| `--download` | No | false | Download when complete |
| `--variant` | No | -- | `video` for MP4 |
| `--out` | No | -- | Output file path |
| `--json-out` | No | -- | Write JSON metadata |

### create

Submit generation without polling.

```bash
uv run --with requests python /Users/fausto_home/.claude/skills/sora/scripts/sora_direct.py create \
  --model sora-2 \
  --prompt "Slow reveal of a lantern-lit market alley." \
  --size 1280x720 \
  --seconds 8
```

### status / download

Check status and download completed videos.

```bash
uv run --with requests python <script> status --id video_abc
uv run --with requests python <script> download --id video_abc --variant video --out clip.mp4
```

### extend

Extend an existing video.

```bash
uv run --with requests python <script> extend \
  --id video_abc \
  --seconds 8 \
  --prompt "Continue the scene as the camera slowly rises."
```

### edit

Re-render with modified prompt (same framing).

```bash
uv run --with requests python <script> edit \
  --id video_abc \
  --prompt "Same shot and framing, warmer palette, softer backlight."
```

### production (Draft-to-Final Pipeline)

**Step 1 -- Generate drafts:**

```bash
uv run --with requests python <script> production \
  --stage drafts \
  --prompt-file /absolute/path/to/prompt.txt \
  --input-reference /absolute/path/to/image.png \
  --size 1080x1920 \
  --seconds 4 \
  --run-dir /absolute/path/to/sora-run
```

Generates 2 draft clips with `sora-2` at 720p-compatible sizes.

**Step 2 -- Review drafts (Gemini scoring):**

```bash
uv run --with requests python <script> review-drafts \
  --run-dir /absolute/path/to/sora-run
```

Scores each draft on 5 dimensions:

| Dimension | Measures |
|-----------|----------|
| `prompt_fidelity` | How well output matches the prompt |
| `temporal_stability` | Frame-to-frame consistency |
| `surface_realism` | Material quality, absence of plastic look |
| `lighting_coherence` | Consistent shadows and light through clip |
| `text_preservation` | Legibility and stability of on-screen text |

Each scores 1-10. Overall: PASS (>= 7.0 weighted) or FAIL.

**Step 3 -- Finalize winner:**

```bash
uv run --with requests python <script> finalize-from-review \
  --run-dir /absolute/path/to/sora-run
```

Reads reviews, selects winner, writes `final-spec.json`, launches `sora-2-pro` final.

**Direct final (skip review):**

```bash
uv run --with requests python <script> production \
  --stage final \
  --prompt-file /absolute/path/to/prompt.txt \
  --final-prompt-file /absolute/path/to/revised.txt \
  --input-reference /absolute/path/to/image.png \
  --size 1080x1920 \
  --seconds 4 \
  --run-dir /absolute/path/to/sora-run
```

### create-character

Upload a non-human character reference for reuse.

```bash
uv run --with requests python <script> create-character \
  --name Mossy \
  --video-file character.mp4
```

## Sora Model IDs

| Model | Use for | Max resolution |
|-------|---------|---------------|
| `sora-2` | Drafts, iteration, cheap exploration | 720p |
| `sora-2-pro` | Final takes, production quality | 1080p |

## Sora I2V Auto Resize/Crop Rules

When using `--input-reference`, the script automatically normalizes the source image:

- Source is resized and cropped to exactly match `--size` before upload
- No manual pre-processing needed
- Portrait source + portrait output (`1080x1920`): best results
- Landscape source + landscape output (`1920x1080`): best results
- Portrait source + landscape output: auto-cropped, acceptable quality
- Landscape source + portrait output: auto-cropped, acceptable quality

The normalization happens client-side before the API call. The API receives an image that matches the requested output dimensions.

## Camera Movement Reliability Table

Field-tested success rates. Validate every prompt's camera choice against this data.

| Movement | Success Rate | Use for | Prompt Phrasing |
|----------|-------------|---------|-----------------|
| **Static** | 94-97% | Hero shots, UI demos, text-heavy content | "Static shot, camera completely still" |
| **Zoom** | 81-87% | Reveals, emphasis, product focus | "Slow zoom in on..." |
| **Pan** | 73-85% | Environment establishment, transitions | "Slow pan left across..." |
| **Tilt** | 67-81% | Height reveals, building reveals | Descriptive: "camera shifts from looking down to up" |
| **Tracking** | 58-68% | B-roll only, never hero shots | "Lateral tracking alongside subject" |
| **Crane** | 44-52% | B-roll, expect retakes | "Camera rises up from ground" |
| **Combined** | ~29% | **NEVER** -- split into separate shots | N/A |

### Generation strategy by success rate

- **>80%** (static, zoom): safe for single-take hero shots
- **70-80%** (pan): acceptable for important shots, generate 2 variants
- **60-70%** (tilt, tracking): B-roll only, generate 3 variants
- **<60%** (crane, combined): avoid or budget for 3-5 attempts

### Prompt phrasing rules

- Use "tilt" descriptively ("camera shifts from looking down to up"), not as a keyword
- Combined movements fail ~70% of the time -- always split into separate sequential shots
- For text-heavy content, only use static or slow zoom
- For UI screenshots, always static

## Cost Comparison

### Veo

| Model | Resolution | Per Second | 4s Clip | 8s Clip |
|-------|-----------|-----------|---------|---------|
| Veo 3.1 Standard | 1080p | $0.40 | $1.60 | $3.20 |
| Veo 3.1 Fast | 720p | $0.15 | $0.60 | $1.20 |
| Veo 3.0 | 1080p | -- | -- | -- |
| Veo 2.0 | 1080p | -- | -- | -- |

Multi-take (3 variants): $9.60 (standard) or $3.60 (fast).

### Sora

| Model | Resolution | 4s Clip | 8s Clip |
|-------|-----------|---------|---------|
| sora-2 | 720p | ~$0.85 | -- |
| sora-2-pro | 1080p | ~$3.50 | ~$5.60 |

Typical scene cost (2 drafts + 1 final): $4-6.

### Strategy

- **Iteration/exploration**: Veo 3.1 Fast ($1.20/8s) or sora-2 ($0.85/4s)
- **Final takes only**: Veo 3.1 Standard or sora-2-pro
- **Never** use the quality model for drafts

## Generation Timing

- Veo: 11 seconds to 6 minutes depending on model and complexity
- Sora: varies, use `create-and-poll` for automatic waiting
- Sora poll interval default: 10 seconds

## Authentication

| Provider | Env Var | Notes |
|----------|---------|-------|
| Veo | `GOOGLE_API_KEY` or `GEMINI_API_KEY` | Server checks both |
| Sora | `OPENAI_API_KEY` | Must be set before running script |

## Guardrails

### Both providers

- No real people or public figures
- No copyrighted characters
- All file paths must be absolute

### Sora-specific

- Only non-human character uploads (`create-character`)
- No copyrighted music

### Veo-specific

- Always include the default negative prompt block
- Named physical light sources in every prompt
- Videos expire from Google servers after 2 days
