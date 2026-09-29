# Video Production: Workflow Patterns Reference

Detailed walkthroughs for each chaining pattern, QA protocol, and post-processing pipeline. This supplements the main `SKILL.md` with copy-paste-ready commands and exhaustive checklists.

## Pattern 1: Animate and Propagate

Use one inspected subject/environment reference for distinct scenes. Prepare a separate motion/camera prompt per shot, then pass references through the actual provider schema. Veo's asset references are not a `style` mode; follow `video-generation/references/provider-details.md`. Generate within the declared attempt/concurrency budget and check identity in each result before assembly.

## Pattern 2: Frame-Forward Chain

Generate the first shot, choose its accepted endpoint, and extract a bridge frame:

```bash
ffmpeg -sseof -0.1 -i clip_1.mp4 -frames:v 1 -q:v 2 bridge_1.jpg
```

Inspect that frame for identity, geometry, and lighting before using it as the next shot's image input. A bad endpoint propagates drift. Check the joined sequence after each link; restart from the last good reference only within the existing budget.

## Pattern 3: Parallel Variants

Hold the anchor, motion, duration, and provider settings fixed while changing one requested treatment. Give every worker a separate directory and a bounded attempt count. Compare the actual outputs against the same QA criteria and join all workers before selecting or assembling.

## Pattern 4: Extension

Check whether the provider accepts the source video, its origin, duration, and resolution. An arbitrary local MP4 is not automatically extendable. Keep the operation/source ID, request a single supported extension, and inspect the seam plus the new material. Repeat only if the next extension was authorized and remains inside the budget; drift is measured per artifact rather than assumed at a fixed number of seconds.

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

Inspect detected timestamps: scene detection is heuristic. Split only at confirmed cuts or account for them in transition timing.

## Multi-Take Variant Selection Protocol

When the budget authorizes multiple variants per shot:

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

See `ffmpeg-production` SKILL.md for the canonical chain order and codec selection. The sequence below covers video-production-specific recipes only.

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

## Bounded QA Repair

Record the current prompt, reference, and exact failed timestamp. Change one relevant variable and permit one repair within the agreed budget. Preserve the earlier clip. After a repeated infrastructure failure or exhausted attempt budget, stop and return the defect; do not launch an automatic new cohort. A prompt optimizer is optional and must be available before using it.

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
|   +-- variants/             # Raw output (authorized attempt count)
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
