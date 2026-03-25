---
name: video-generation
description: Generate AI video with Veo or Sora. Triggers on text-to-video, image-to-video, video extension, style-consistent generation. Not for video analysis, research, or FFmpeg editing.
---

# Video Generation

Generate AI video using Veo (MCP tools) or Sora (direct API script). This skill covers provider selection, generation modes, defaults, and the draft-to-final workflow.

For full tool references, model IDs, camera reliability data, and negative prompt blocks, see [references/provider-details.md](references/provider-details.md).

## Provider Selection

Choose before writing prompts.

| Need | Provider | Why |
|------|----------|-----|
| Native audio, 4K output, style/asset references, video extension | **Veo** | Veo 3.1 has the richer media-control surface |
| 1080p production, text-heavy scenes, clean draft/final model split | **Sora** | `sora-2` drafts + `sora-2-pro` finals is the most reliable loop |
| High-value hero shot, uncertain which provider wins | **Both** | Generate with both, pick winner from review evidence |

Decision rules:

1. **Veo** when: native audio matters, you need 4K, you have style-anchor images for cross-clip consistency, or you need to extend an existing clip.
2. **Sora** when: 1080p is sufficient, the scene has on-screen text, or the draft-to-pro upgrade path saves iteration time.
3. **Both** when: the shot is expensive to reshoot and the extra cost of a bakeoff is justified.

## Generation Modes

### Text-to-Video

Prompt describes the scene. Both providers support this.

- Veo: `mcp__veo__generate_video` -- supports `number_of_videos` (1-4) for multi-take
- Sora: `sora_direct.py create-and-poll` -- single generation per call

### Image-to-Video (I2V)

Animate a static image. Source image quality is critical.

- Veo: `mcp__veo__animate_image` -- absolute path to source image required
- Sora: `sora_direct.py create-and-poll --input-reference` -- auto-resizes/crops source to match output size

### Video Extension

Continue an existing clip with new content.

- Veo: `mcp__veo__extend_video_clip` -- Veo 3.1 only, continues from last second
- Sora: `sora_direct.py extend --id <video_id>` -- extends by prompt

### Styled Generation (Veo only)

Generate video with 1-3 reference images for visual consistency.

- `mcp__veo__generate_video_with_style` -- Veo 3.1 only
- Reference types: `"asset"` (preserves composition) or `"style"` (preserves palette/grain/lighting)

## Default Settings

### Veo Defaults

| Parameter | Draft | Final |
|-----------|-------|-------|
| Model | `veo-3.1-fast-generate-preview` | `veo-3.1-generate-preview` |
| Resolution | `720p` | `1080p` |
| Duration | `6s` | `8s` |
| Aspect ratio | `16:9` | `16:9` |
| Negative prompt | Always include default block (see references) | Always include default block |

### Sora Defaults

| Parameter | Draft | Final |
|-----------|-------|-------|
| Model | `sora-2` | `sora-2-pro` |
| Resolution | `1280x720` | `1920x1080` (or `1080x1920` portrait) |
| Duration | `4s` | `4s` (or `8s` for extended scenes) |
| Draft count | 2 | 1 |

## Draft-to-Final Workflow

Generate cheap drafts first, review, then produce the final with the quality model. This saves 60-70% on failed iterations.

### Veo Path

1. Generate 2-3 variants with `veo-3.1-fast-generate-preview` at 720p
2. Review candidates (silence test at 1x, slow-motion scan at 0.5x)
3. Regenerate winner prompt with `veo-3.1-generate-preview` at 1080p

### Sora Path (Preferred -- Automated)

1. **Drafts**: `sora_direct.py production --stage drafts` -- generates 2 clips with `sora-2` at 720p
2. **Review**: `sora_direct.py review-drafts` -- Gemini scores each draft on 5 dimensions (prompt fidelity, temporal stability, surface realism, lighting coherence, text preservation)
3. **Finalize**: `sora_direct.py finalize-from-review` -- selects winner, launches `sora-2-pro` final at 1080p

All three steps require `--run-dir` with an **absolute path**. Relative paths break the review subprocess.

## Camera Movement Reliability

Camera choice directly affects generation success rate. Summary:

| Movement | Success Rate | Recommendation |
|----------|-------------|----------------|
| **Static** | 94-97% | Default for hero shots, UI demos |
| **Zoom** | 81-87% | Good for reveals and emphasis |
| **Pan** | 73-85% | Acceptable for environment shots |
| **Tilt** | 67-81% | Use descriptive phrasing, not "tilt" |
| **Tracking** | 58-68% | B-roll only, generate 3 variants |
| **Crane** | 44-52% | Expect retakes |
| **Combined** | ~29% | **Never** -- split into separate shots |

For movements below 70%, always generate 3 variants. Full percentages and prompt phrasing in [references/provider-details.md](references/provider-details.md).

## Key Constraints

### Veo

- Always pass the negative prompt block (see references)
- All paths must be absolute
- `extend_video_clip` and `generate_video_with_style` require Veo 3.1
- Videos stay on Google servers for 2 days -- download promptly
- Named physical light sources required in every prompt (never "well-lit")

### Sora

- `OPENAI_API_KEY` must be set
- `--run-dir` must be absolute for production workflows
- No real people, public figures, copyrighted characters
- Only non-human character uploads
- 720p drafts auto-map to compatible sizes when final target is 1080p
- I2V auto-resizes source images to match `--size`

## Cost Reference

| Provider | Model | Resolution | Duration | Cost |
|----------|-------|-----------|----------|------|
| Veo | 3.1 Standard | 1080p | 8s | ~$3.20 |
| Veo | 3.1 Fast | 720p | 8s | ~$1.20 |
| Sora | sora-2 | 720p | 4s | ~$0.85 |
| Sora | sora-2-pro | 1080p | 4s | ~$3.50 |
| Sora | sora-2-pro | 1080p | 8s | ~$5.60 |

Typical scene (draft + final): $4-6 total.

## Prompt Structure

Follow this template for both providers:

```
[Camera+Lens]: [Subject with physical detail] [Action with force verbs],
in [Setting with atmosphere], lit by [Named physical light source].
Style: [Texture micro-details, film grain]. Audio: [Ambient/SFX].
```

Rules:
1. **Named physical light source** -- always specify concrete light ("cool fluorescent overhead strips", not "well-lit")
2. **Avoid dynamic physics** -- no falling objects, fluids, collisions
3. **Force-based verbs** -- "grips handle and pulls" not "opens"
4. **Micro-imperfections** -- append "slightly grainy film-like quality, fine surface texture"
5. **Exact descriptors** -- copy-paste character/scene descriptions across shots, never paraphrase

## Configuration

- Veo MCP server: `veo` in `~/.claude/.mcp.json`
- Veo auth: `GOOGLE_API_KEY` or `GEMINI_API_KEY`
- Veo output: `~/Videos/veo-generated/`
- Sora script: `/Users/fausto_home/.claude/skills/sora/scripts/sora_direct.py`
- Sora auth: `OPENAI_API_KEY`
- Run with: `uv run --with requests python <script> <command> [args]`

## Related Skills

- **video-production** — multi-shot orchestration, chaining patterns, QA workflow
- **image-generation** — hero image generation for style anchors
- **ffmpeg-production** — post-processing, encoding, platform export
