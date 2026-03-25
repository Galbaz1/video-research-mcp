---
name: video-production
description: Orchestrate multi-clip AI video projects — style anchors, chaining patterns, frame-level QA, montage assembly. Not for video analysis, research, provider settings, or FFmpeg encoding.
---

# Video Production Pipeline

Orchestrates the full lifecycle of cinematic AI video: anchor image through multi-shot assembly. The core principle is **anchor-first chaining** — one perfect hero still locks visual identity (lighting, palette, texture) across every clip. Without this, each generation invents its own world.

## Production Phases

Every production follows five phases regardless of provider or chain pattern.

### 1. Concept

Define the visual brief before touching any tool.

- **Shot list**: one line per clip — subject, motion, duration, mood
- **Visual world(s)**: industrial, office, outdoor, etc. — each world gets its own anchor
- **Asset audit**: search project directories for existing footage before generating anything. Real footage at 1080p always trumps AI generation

### 2. Style Anchor

Generate one hero image per visual world with `mcp-image`. This image is the single source of truth for all subsequent clips.

```
mcp-image parameters:
  quality: "quality"
  imageSize: "4K"
  purpose: "cinematic video style anchor"
  maintainCharacterConsistency: true  (for multi-image sets)
```

Iterate with `inputImagePath` until lighting, composition, and subject are exactly right. The anchor is immutable once approved — everything flows from it.

**Anchor requirements:**
- Contains everything clips need to inherit: subject appearance, lighting direction, color temperature, atmospheric density
- Exact same lighting description must appear in both image and video prompts
- Store approved anchors in `assets/style-anchors/` with descriptor strings in `descriptors.md`
- Copy-paste descriptors between shots — never paraphrase

**Anchor sandwich** (for sequential scenes):

```
ANCHOR-START --> [motion] --> HERO --> [motion] --> ANCHOR-END
     |                                                  |
     = ANCHOR-END of previous scene         = ANCHOR-START of next scene
```

This ensures visual continuity: each scene's endpoint feeds the next scene's entry point.

### 3. Generate

Animate the anchor into video clips. The prompt describes **motion and environment only** — not appearance (the image handles that).

**Prompt structure:** See the prompt template in `video-generation` skill. Key rule: prompt describes **motion and environment only** — the anchor image handles appearance. Never paraphrase character descriptions across shots.

Never leave lighting vague. Map scenes to concrete physical lights:

| Environment | Physical Light |
|-------------|---------------|
| Server room | cool fluorescent strips, blue accent from screens |
| Industrial floor | high-bay sodium vapor, warm amber + clerestory daylight |
| Office | recessed LED panels 4000K, natural window light from one side |
| Outdoor day | overcast sky, no hard shadows, gentle ambient fill |
| Night/moody | single desk lamp, warm pool, deep shadows beyond |

**Multi-take protocol:** Generate 3-4 variants for important shots. Evaluate on two axes:

- **Technical quality** (100% zoom): texture flicker, boundary bleeding, lighting consistency, surface deformation
- **Rationality** (0.5x speed): physics plausibility, spatial logic, object permanence

Pick fewest rationality failures. Among ties, pick best technical. All fail: revise prompt — never fix blockers in post.

### 4. QA (Frame-Level Inspection)

Extract frames and inspect visually instead of watching at playback speed. This turns subjective "looks off" into precise "frame 47 has a lighting discontinuity."

**Standard extraction:**
```bash
mkdir -p /tmp/qa/variant-${i}
ffmpeg -i variant_${i}.mp4 -vf "fps=10" /tmp/qa/variant-${i}/frame_%04d.png
```

**Quick scan — contact sheet:**
```bash
ffmpeg -i input.mp4 -vf "fps=1,scale=320:-1,tile=6x5" -frames:v 1 -q:v 3 contact_sheet.jpg
```

**Visual inspection checklist:**
- Composition drift from intended layout
- Lighting direction/temperature stability across frames
- Object integrity (shape and detail maintained)
- Motion quality (smooth vs stutter/jump)
- Color temperature match to hero image

**Decision tree:**

| Result | Action |
|--------|--------|
| All variants fail | Improve prompt, regenerate (max 3 rounds) |
| One variant good | Lock it, proceed to assembly |
| Multiple good | Pick best, lock it |
| Close but flawed | Note specific frame issues, improve prompt |

After 3 failed prompt rounds, simplify the scene: reduce motion, shorten duration, or split into sub-scenes.

**Artifact severity:**

| Artifact | Severity | Action |
|----------|----------|--------|
| Temporal flicker | Blocker | Regenerate |
| Boundary inconsistency | Blocker | Regenerate |
| Rubber-sheet deformation | Blocker | Regenerate |
| Physics violations | Blocker | Regenerate |
| Color temperature drift | Major | Fix in color grade |
| Too-clean texture | Minor | Fix with grain overlay |

Gate: 0 blockers to pass. Any blocker means regenerate or revise prompt. Majors fix in post if possible.

**Scene detection before assembly:**
```bash
ffmpeg -i input.mp4 -vf "scdet=threshold=40" -f null - 2>&1 | grep scdet
```

AI generators sometimes insert hard cuts within a single clip. Detect before designing transitions.

### 5. Assemble

Once all scenes pass QA individually:

1. **Normalize** all clips to identical fps, resolution, pixel format (mandatory — skip and xfade timing breaks silently)
2. **Color-match** — same LUT across all clips (inconsistent grades reveal the AI workflow)
3. **Join** with xfade transitions (dissolve, 0.5-1s)
4. **Post-process** — film grain last in filter chain, immediately before encode
5. **QC** — `ffprobe` after every operation, final printscreen QA on transition points

**xfade offset formula:**
```
offset = sum_of_previous_clip_durations - cumulative_overlap
```

Every `xfade` must have a paired `acrossfade` with identical duration (omitting causes audio discontinuities).

## Chaining Patterns

Four patterns for different production scenarios. Choose based on the decision tree, then see `references/workflow-patterns.md` for detailed walkthroughs.

### Pattern 1: Animate & Propagate (default)

Hero still branches into multiple clips sharing visual DNA. Best for: central character or environment across distinct scenes.

```
Hero Still --> animate_image --> Clip 1
          --> style-ref video --> Clip 2
          --> style-ref video --> Clip 3
                                  --> FFmpeg montage
```

### Pattern 2: Frame-Forward Chain

Each clip's last frame becomes the next clip's first frame. Best for: continuous motion through a space.

```
Hero --> animate --> Clip 1 --> extract last frame --> animate --> Clip 2 --> ...
```

Extract bridge frame: `ffmpeg -sseof -0.1 -i clip_N.mp4 -frames:v 1 -q:v 2 last_frame_N.jpg`

Gotcha: motion drift accumulates after 3-4 links. Trim each clip to its first 3-4 strong seconds before extracting.

### Pattern 3: Parallel Variants

One anchor, multiple independent clips with different treatments. Best for: same scene in different moods, lighting, or time-of-day.

### Pattern 4: Extend Chain

Single clip extended sequentially beyond the generation limit. Best for: long takes, slow reveals, atmospheric holds.

Gotcha: quality degrades after 2 extensions (~24s). Plan the most important content in the first 8s.

**Decision tree:**

```
Multiple distinct scenes, same visual identity  --> Pattern 1
Continuous motion through a space               --> Pattern 2
Same scene, different moods/treatments          --> Pattern 3
Single long unbroken shot                       --> Pattern 4
Unsure                                          --> Pattern 1 (most versatile)
```

## Critical Rules

1. **Existing footage trumps AI generation.** Always audit project assets first
2. **Post-processing is not optional.** Every clip: `hqdn3d -> scale -> unsharp -> eq` before assembly
3. **Contact sheet QA is mandatory** per clip before inclusion
4. **Anchor-end of scene N = anchor-start of scene N+1.** This is the chain contract
5. **Never generate video from text alone.** Always start from an anchor image
6. **Max 5-6 chained scenes before a quality checkpoint.** Visual drift accumulates
7. **Prompt describes motion, not appearance.** The anchor image handles visual identity

## Post-Processing

See `ffmpeg-production` for the canonical post-processing chain order (temporal denoise → upscale → sharpen → color grade → grain → encode). The sequence is load-bearing — grain before denoising is destroyed, interpolation after grain causes tearing.

## Related Skills

| Need | Skill |
|------|-------|
| Hero image prompt optimization | `image-generation` |
| Provider tools and settings | `video-generation` |
| FFmpeg encoding and filters | `ffmpeg-production` |
| Voice-over and audio mixing | `tts-production` |

## Deep Reference

For detailed per-pattern walkthroughs, FFmpeg commands, QA inspection protocol, multi-take selection, and post-processing recipes: [references/workflow-patterns.md](references/workflow-patterns.md)
