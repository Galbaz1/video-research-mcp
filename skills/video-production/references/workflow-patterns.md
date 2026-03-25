# Video Production: Workflow Patterns Reference

Detailed walkthroughs for each chaining pattern, QA protocol, and post-processing pipeline. This supplements the main `SKILL.md` with copy-paste-ready commands and exhaustive checklists.

## Pattern 1: Animate & Propagate (Full Walkthrough)

The recommended default. One hero still branches into multiple clips sharing visual DNA.

### Step-by-step

1. **Generate hero still** with `mcp-image`:
   - `quality: "quality"`, `imageSize: "4K"`, `purpose: "cinematic video keyframe"`
   - `maintainCharacterConsistency: true` for multi-scene sets
   - Iterate with `inputImagePath` until perfect

2. **First clip** — animate the hero:
   ```
   animate_image:
     image_path: /path/to/hero.png
     prompt: "Subtle movement: [describe motion]. Camera holds still."
     duration: 8
     number_of_videos: 4
     aspect_ratio: "16:9"
     model: "veo-3.1-generate-preview"
     negative_prompt: "text, watermark, logo, blurry, distorted, deformed,
                       low quality, overexposed, underexposed, glitch"
   ```

3. **Subsequent clips** — use hero as style reference:
   ```
   generate_video_with_style:
     prompt: "[new scene description with motion]"
     reference_image_paths: ["/path/to/hero.png"]
     reference_types: ["style"]
     duration: 8
     number_of_videos: 4
   ```

4. **QA each clip** (see QA Protocol below)

5. **Assemble** with FFmpeg montage

### When to use

- Central character recognizable across multiple distinct scenes
- Same factory/environment in different states
- Hero product shown in different contexts

## Pattern 2: Frame-Forward Chain (Full Walkthrough)

Each clip's endpoint becomes the next clip's starting point.

### Step-by-step

1. **Generate hero still** (same as Pattern 1)

2. **First clip** — animate the hero:
   ```
   animate_image:
     image_path: /path/to/hero.png
     prompt: "Camera slowly tracks right. [describe initial motion]."
     duration: 8
     number_of_videos: 4
   ```

3. **Extract last frame** from the winning variant:
   ```bash
   ffmpeg -sseof -0.1 -i clip_1_winner.mp4 -frames:v 1 -q:v 2 bridge_frame_1.jpg
   ```

4. **Visually verify** the bridge frame with Read tool. If the gap between this frame and the next scene's intended composition is too large, generate intermediate anchor images with mcp-image.

5. **Next clip** — animate from the bridge frame:
   ```
   animate_image:
     image_path: /path/to/bridge_frame_1.jpg
     prompt: "Continuing motion. [describe next segment]."
     duration: 8
     number_of_videos: 4
   ```

6. **Repeat** steps 3-5 for each link in the chain

7. **Assemble** with concat or xfade

### Drift mitigation

Motion drift accumulates after 3-4 links. Countermeasures:
- Trim each clip to its first 3-4 strong seconds before extracting the last frame
- After 4 links, pause and assemble what you have for a quality checkpoint
- If drift is visible, restart the chain from the last good bridge frame with a corrective prompt

### When to use

- Walking through a factory, zooming into a machine
- Journey through time or space
- Any continuous camera movement

## Pattern 3: Parallel Variants (Full Walkthrough)

One anchor, multiple independent clips with different treatments.

### Step-by-step

1. **Generate hero still** (same as Pattern 1)

2. **Generate variants** — each with a different mood/treatment:
   ```
   # Dawn version
   animate_image:
     image_path: /path/to/hero.png
     prompt: "Golden dawn light washes across the scene. Gentle warmth."
     number_of_videos: 4

   # Dusk version
   animate_image:
     image_path: /path/to/hero.png
     prompt: "Deep blue dusk, warm interior light spills from windows."
     number_of_videos: 4

   # Storm version
   animate_image:
     image_path: /path/to/hero.png
     prompt: "Heavy rain, dramatic clouds, flashes of distant lightning."
     number_of_videos: 4
   ```

3. **QA each variant set** independently

4. **Pick best** from each set, or combine into a time-lapse montage

### When to use

- Same scene in different moods or lighting
- Time-of-day treatments
- A/B visual tests for stakeholder review

## Pattern 4: Extend Chain (Full Walkthrough)

Single continuous shot beyond the generation time limit.

### Step-by-step

1. **Generate hero still** (same as Pattern 1)

2. **First segment** (8s):
   ```
   animate_image:
     image_path: /path/to/hero.png
     prompt: "Slow cinematic reveal. Camera drifts forward."
     duration: 8
     number_of_videos: 4
   ```

3. **Extend** from the winning clip:
   ```
   extend_video_clip:
     video_path: /path/to/clip_1_winner.mp4
     prompt: "Continue the slow forward drift. Same lighting and atmosphere."
     duration: 8
   ```

4. **Extend again** if needed (max 2 extensions = ~24s total)

5. **QA the full continuous clip** — pay special attention to extension seams

### Degradation limits

- After 1 extension (~16s): usually good
- After 2 extensions (~24s): quality starts degrading
- After 3+ extensions: not recommended — plan the most important content in the first 8s

### When to use

- Slow reveals
- Continuous pans
- Atmospheric holds
- Any single unbroken shot > 8s

## QA Protocol: Frame Extraction and Inspection

### Frame extraction commands

```bash
# Standard: every 100ms (10 fps) — full QA pass
ffmpeg -i input.mp4 -vf "fps=10" /tmp/qa/frame_%04d.png

# Light: every 200ms (5 fps) — quick scan
ffmpeg -i input.mp4 -vf "fps=5" /tmp/qa/frame_%04d.png

# Contact sheet: all frames in one image — fastest scan
ffmpeg -i input.mp4 -vf "fps=1,scale=320:-1,tile=6x5" -frames:v 1 -q:v 3 contact_sheet.jpg

# Specific timestamp
ffmpeg -ss 00:00:02.500 -i input.mp4 -frames:v 1 frame_at_2500ms.png

# Last frame (for bridge extraction)
ffmpeg -sseof -0.1 -i input.mp4 -frames:v 1 -q:v 2 last_frame.jpg
```

### Inspection workflow

1. **Contact sheet first** — one Read call to scan the entire clip
2. **Sample frames** — frames 1, 10, 20, 30 from each variant to identify best candidate
3. **Winner deep scan** — frame-by-frame on the selected variant

### Visual inspection checklist

For each frame set, evaluate these dimensions:

**Composition drift**
- Does the scene maintain the intended layout?
- Is the subject still centered/positioned as intended?
- Have background elements shifted or appeared/disappeared?

**Lighting consistency**
- Does light direction stay stable across frames?
- Is the color temperature constant?
- Are shadows consistent in direction and intensity?

**Object integrity**
- Do objects maintain their shape and detail?
- Are edges clean (no boundary bleeding)?
- Do textures remain stable (no flicker)?

**Motion quality**
- Is the motion smooth or does it stutter/jump?
- Are there any rubber-sheet deformations on surfaces?
- Does the motion match the prompt intent?

**Color temperature**
- Does the palette match the hero/anchor image?
- Is there any color drift across the clip duration?
- Are skin tones (if present) stable?

### Scene detection (pre-assembly)

Run on every raw AI clip before planning transitions:

```bash
# Detect scene changes (threshold 40 = 40% frame difference)
ffmpeg -i input.mp4 -vf "scdet=threshold=40" -f null - 2>&1 | grep scdet

# Extract thumbnails at detected cuts
ffmpeg -i input.mp4 \
  -filter_complex "select='gt(scene,0.4)',metadata=print:file=scenes.txt" \
  -vsync vfr scene_%04d.jpg
```

If a clip has internal scene changes, split it at the detected cut or account for it in xfade timing.

## Multi-Take Variant Selection Protocol

When generating 3-4 variants per shot:

### Rapid triage (30 seconds per variant)

1. Generate contact sheet for each variant
2. Scan for obvious blockers: hard cuts, major composition breaks, wrong subject
3. Eliminate any variant with blockers

### Dual-axis evaluation (surviving variants)

**Technical quality** (watch at 100% zoom / inspect extracted frames):
- No temporal flicker in textures (hair, fabric, metal)
- No boundary bleeding at object/background edges
- Consistent lighting direction across all frames
- No rubber-sheet deformation on surfaces

**Rationality** (watch at 0.5x speed):
- Physics plausible — no floating, no gravity violations
- Scene logic — spatial relationships make sense
- Object permanence — nothing appears/disappears mid-clip

### Selection rule

1. Pick fewest rationality failures
2. Among ties, pick best technical quality
3. All fail: revise prompt (never try to fix blockers in post)

### When to re-prompt vs accept

- **Re-prompt**: any blocker artifact, wrong subject, wrong motion direction
- **Accept with post-fix**: minor color drift (fix in grade), too-clean texture (fix with grain)
- **Accept as-is**: technically clean, matches intent, no visible artifacts at 0.5x

## Post-Processing Pipeline

### Chain order (load-bearing)

```
Raw AI clip
    |
[1] Temporal denoising     -- remove inter-frame shimmer/flicker
    |
[2] Upscale (if needed)    -- scale before sharpening avoids halos
    |
[3] Sharpening             -- recover edge detail lost in generation/upscale
    |
[4] Color grade (LUT)      -- normalize AI's often over-saturated palette
    |
[5] Curves/EQ              -- fine-tune contrast and shadow lift
    |
[6] Film grain synthesis   -- LAST before encode; never before denoising
    |
[7] Encode with grain-tune -- libx265 -tune grain or AV1 FGS
```

### FFmpeg post-processing commands

**Film grain overlay (breaks plastic AI texture):**
```bash
ffmpeg -i input.mp4 \
  -vf "noise=c0s=8:c0f=t+u,format=yuv420p" \
  -c:v libx264 -crf 18 -preset slow \
  -c:a copy -movflags +faststart \
  output_grain.mp4
```

**Subtle chromatic aberration (lens imperfection at edges):**
```bash
ffmpeg -i input.mp4 \
  -vf "rgbashift=rh=2:bh=-2:rv=1:bv=-1" \
  -c:v libx264 -crf 18 -preset slow \
  -c:a copy -movflags +faststart \
  output_ca.mp4
```

**QC probe after every step:**
```bash
ffprobe -v error -show_entries format=duration:stream=width,height,codec_name,r_frame_rate \
  -of json output.mp4
```

**Strip audio:**
```bash
ffmpeg -i input.mp4 -an -c:v copy output_silent.mp4
```

### Film grain decision tree

```
Is the final encode AV1 (libsvtav1)?
+-- YES --> Use AV1 FGS
|           ffmpeg -i denoised.mp4 -c:v libsvtav1 -crf 30 \
|             -svtav1-params "tune=0:film-grain=8:film-grain-denoise=0" output.av1.mp4
|
+-- NO --> Is this an offline batch or archive master?
           +-- YES --> Use geq-based synthesis (realistic silver-halide clumping)
           |           ffmpeg -i input.mp4 -vf \
           |             "geq=lum='lum(X,Y)+10*sin(random(1)*2*PI)*gauss(0.5)':cb=cb(X,Y):cr=cr(X,Y)" \
           |             output.mp4
           |
           +-- NO --> Use noise filter (fast, good enough for web delivery)
                      ffmpeg -i input.mp4 -vf "noise=alls=8:allf=t+u" \
                        -c:v libx265 -crf 18 -tune grain output.mp4
```

### Mixed-resolution normalization (before concat)

AI generators produce variable output sizes. Normalize all inputs first:

```bash
ffmpeg -i a.mp4 -i b.mp4 -i c.mp4 -filter_complex \
  "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[v0];
   [1:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[v1];
   [2:v]scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2[v2];
   [v0][v1][v2]concat=n=3:v=1[vout]" \
  -map "[vout]" output.mp4
```

## Assembly Recipes

### Basic xfade concatenation

```bash
ffmpeg -i scene_1.mp4 -i scene_2.mp4 -i scene_3.mp4 \
  -filter_complex "
    [0:v][1:v]xfade=transition=fade:duration=0.3:offset=7.7[v01];
    [v01][2:v]xfade=transition=fade:duration=0.3:offset=15.1[v012]" \
  -map "[v012]" \
  -c:v libx264 -crf 18 -preset slow \
  final_sequence.mp4
```

### xfade with paired acrossfade (required when clips have audio)

```bash
ffmpeg -i a.mp4 -i b.mp4 -i c.mp4 -filter_complex \
  "[0:v][1:v]xfade=transition=dissolve:duration=1:offset=4[v01];
   [v01][2:v]xfade=transition=wipeleft:duration=1:offset=7[vout];
   [0:a][1:a]acrossfade=d=1[a01];
   [a01][2:a]acrossfade=d=1[aout]" \
  -map "[vout]" -map "[aout]" \
  -c:v libx265 -crf 18 output.mp4
```

### xfade offset formula

```
offset_AB = duration_A - overlap
offset_BC = (duration_A + duration_B) - (overlap_AB + overlap_BC)
```

Example: clips A(5s), B(4s), C(6s) with 1s overlaps:
- `offset_AB = 5 - 1 = 4`
- `offset_BC = (5 + 4) - (1 + 1) = 7`

### Double-exposure blend (thematic overlaps)

```bash
ffmpeg -i clip_a.mp4 -i clip_b.mp4 -filter_complex \
  "[0:v]trim=start=3:end=5,setpts=PTS-STARTPTS[a_end];
   [1:v]trim=start=0:end=2,setpts=PTS-STARTPTS[b_start];
   [a_end][b_start]blend=all_expr='A*0.5+B*0.5'[blended];
   [0:v]trim=end=3,setpts=PTS-STARTPTS[a_pre];
   [1:v]trim=start=2,setpts=PTS-STARTPTS[b_post];
   [a_pre][blended][b_post]concat=n=3:v=1[vout]" \
  -map "[vout]" output.mp4
```

## Prompt-Optimizer Integration on QA Failures

When variants fail QA, feed specific feedback to the `/prompt-optimizer` skill:

1. **Current prompt** text
2. **Specific frame failures**: "frame 15-20 show lighting flip from left to right"
3. **Hero image** as visual reference
4. **Composition reference** (if using Stitch mockups)

The optimizer rewrites the prompt targeting the specific failure. Regenerate 4 new variants and return to QA.

**Iteration limit**: 3 rounds max on the same prompt approach. After that, simplify:
- Reduce motion complexity
- Shorten duration
- Split into sub-scenes
- Use a static or zoom-only camera instead of tracking

## Frame Interpolation

### RIFE (recommended)

GPU-accelerated, superior results for AI footage:

```bash
rife-ncnn-vulkan -i input.mp4 -o frames/ -m rife-v4.6 -j 1:4:4
ffmpeg -r 48 -i frames/%08d.png -c:v libx265 -crf 18 output_rife.mp4
```

### minterpolate (FFmpeg fallback)

When GPU/Vulkan unavailable:

```bash
ffmpeg -i input.mp4 \
  -vf "minterpolate=fps=48:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" \
  output_slow.mp4
```

## Project Directory Structure

```
project/
+-- assets/
|   +-- style-anchors/       # Hero images + descriptors.md
|   +-- anchors/              # Start/end anchor images per scene
|   +-- variants/             # Raw output (4 per generation)
|   |   +-- scene-1/
|   |   |   +-- iteration-1/
|   |   |   +-- iteration-2/
|   |   +-- scene-2/
|   +-- printscreens/         # Extracted QA frames
|   |   +-- scene-1/
|   |   |   +-- variant-1/ through variant-4/
|   |   +-- scene-2/
|   +-- approved/             # Winning variants
|   +-- final/                # Assembled output
+-- prompts/
    +-- scene-1.md            # Prompt history with iteration notes
    +-- scene-2.md
```
