---
name: ffmpeg-production
description: FFmpeg video/audio processing — conversion, scaling, compression, trimming, concatenation, AI post-processing. Not for audio ducking/voice mixing (tts-production) or Remotion rendering.
---

# FFmpeg Production

FFmpeg recipes for video post-production. Covers the operations you reach for daily: format conversion, scaling, trimming, concatenation, compression, and AI video post-processing.

For platform-specific export presets (YouTube, TikTok, Instagram, Twitter), see [references/platform-presets.md](references/platform-presets.md).

## Post-Processing Filter Order

**Sequence determines correctness, not just quality.** This is a physical constraint.

```
[1] Temporal denoise  — remove inter-frame shimmer before any processing
[2] Scale             — scale before sharpening avoids halos
[3] Sharpen           — recover edge detail lost in generation/upscale
[4] Color grade (LUT) — normalize over-saturated AI palette
[5] Curves/EQ         — fine-tune contrast and shadow lift
[6] Film grain        — LAST before encode; grain before denoising destroys it
[7] Encode            — libx265 -tune grain or AV1 FGS
```

Violations cause correctness failures: grain before denoising destroys it; interpolation after grain synthesis causes tearing.

Full chain as a single filtergraph:

```bash
ffmpeg -i input.mp4 \
  -vf "hqdn3d=2:2:3:3,\
       scale=1920:1080:flags=lanczos,\
       unsharp=5:5:0.8:5:5:0.4,\
       lut3d=grade.cube,\
       curves=r='0/0 0.5/0.52 1/1':b='0/0.03 1/0.97',\
       noise=alls=6:allf=t+u" \
  -c:v libx265 -crf 18 -preset slow -tune grain \
  -c:a copy output.mp4
```

### Hald CLUT Color Grading

Preferred for iterative grading: export a Hald CLUT, grade in Photoshop/GIMP, re-import. No re-encoding between iterations.

```bash
ffmpeg -i input.mp4 -i hald_clut_graded.png \
  -filter_complex "[0:v][1:v] haldclut" \
  -c:v libx265 -crf 18 output.mp4
```

## Format Conversion

### Codec Selection

| Target | Codec | When to use |
|--------|-------|-------------|
| Web/streaming | libx264 | Universal compatibility |
| Archive/master | libx265 | ~40% smaller at same quality |
| Modern distribution | libsvtav1 | Best compression, slower encode |
| Browser embed | libvpx-vp9 | WebM container, good compression |

### Essential Flags

| Flag | Purpose |
|------|---------|
| `-movflags +faststart` | Moves moov atom to front for web streaming |
| `-pix_fmt yuv420p` | Ensures player compatibility |
| `-preset slow/medium/fast` | Encode speed vs compression tradeoff |
| `-crf 18-28` | Quality control (lower = better, 23 is default) |
| `-profile:v high` | H.264 feature set (high for quality, baseline for compat) |

### CRF Quality Guide

| Use case | CRF | Preset | Notes |
|----------|-----|--------|-------|
| Archive/master | 18 | slow | Best quality, large files |
| Production | 20-22 | medium | Good balance |
| Web/preview | 23-25 | fast | Smaller files |
| Draft/quick | 28+ | veryfast | Fast encoding |

### GIF to MP4

```bash
ffmpeg -i input.gif -movflags faststart -pix_fmt yuv420p \
  -vf "scale=trunc(iw/2)*2:trunc(ih/2)*2" output.mp4
```

### Compress Video

```bash
# Good quality, smaller file
ffmpeg -i input.mp4 -c:v libx264 -crf 23 -preset medium -c:a aac -b:a 128k output.mp4

# Target file size (e.g., ~10MB for 60s = ~1.3Mbps)
ffmpeg -i input.mp4 -c:v libx264 -b:v 1300k -c:a aac -b:a 128k output.mp4
```

## Video Scaling and Cropping

```bash
# Scale to 1080p (letterbox — maintain aspect ratio, add black bars)
ffmpeg -i input.mp4 \
  -vf "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2" \
  output.mp4

# Scale to 1080p (crop to fill)
ffmpeg -i input.mp4 \
  -vf "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080" \
  output.mp4

# Scale to width, auto height (even dimensions)
ffmpeg -i input.mp4 -vf "scale=1280:-2" output.mp4
```

## Audio Extraction and Conversion

```bash
# Extract to MP3
ffmpeg -i input.mp4 -vn -acodec libmp3lame -q:a 2 output.mp3

# Extract to AAC
ffmpeg -i input.mp4 -vn -acodec aac -b:a 192k output.m4a

# Extract to WAV (uncompressed)
ffmpeg -i input.mp4 -vn output.wav

# M4A to MP3
ffmpeg -i input.m4a -codec:a libmp3lame -qscale:a 2 output.mp3

# Adjust volume
ffmpeg -i input.mp3 -filter:a "volume=1.5" output.mp3
```

## Trimming and Cutting

```bash
# Cut from timestamp for duration (recommended — re-encode for accuracy)
ffmpeg -i input.mp4 -ss 00:00:30 -t 00:00:15 -c:v libx264 -c:a aac output.mp4

# Cut between timestamps
ffmpeg -i input.mp4 -ss 00:00:30 -to 00:00:45 -c:v libx264 -c:a aac output.mp4

# Stream copy (faster but may lose frames at non-keyframe cut points)
ffmpeg -i input.mp4 -ss 00:00:30 -t 00:00:15 -c copy output.mp4
```

Re-encoding is recommended for trimming. Stream copy (`-c copy`) can silently drop video if the seek point misses a keyframe.

## Concatenation

```bash
# Create file list
printf "file '%s'\n" clip1.mp4 clip2.mp4 clip3.mp4 > list.txt

# Concatenate (same codec/resolution — stream copy)
ffmpeg -f concat -safe 0 -i list.txt -c copy output.mp4

# Concatenate (mixed sources — re-encode)
ffmpeg -f concat -safe 0 -i list.txt -c:v libx264 -c:a aac output.mp4
```

## Speed Change

```bash
# 2x speed (video + audio)
ffmpeg -i input.mp4 \
  -filter_complex "[0:v]setpts=0.5*PTS[v];[0:a]atempo=2.0[a]" \
  -map "[v]" -map "[a]" output.mp4

# 0.5x slow motion
ffmpeg -i input.mp4 \
  -filter_complex "[0:v]setpts=2.0*PTS[v];[0:a]atempo=0.5[a]" \
  -map "[v]" -map "[a]" output.mp4

# Video only (drop audio)
ffmpeg -i input.mp4 -filter:v "setpts=0.5*PTS" -an output.mp4
```

**Speed math:** To fit X seconds into Y seconds: `speed = X / Y`, `setpts = 1/speed * PTS`, `atempo = speed`.

**Extreme speeds (>2x audio):** Chain atempo filters (each limited to 0.5-2.0):

```bash
# 4x audio: atempo=2.0,atempo=2.0
# 8x audio: atempo=2.0,atempo=2.0,atempo=2.0
```

## Fade and Transitions

```bash
# Video fade in/out (1s each, 10s video)
ffmpeg -i input.mp4 \
  -vf "fade=t=in:st=0:d=1,fade=t=out:st=9:d=1" -c:a copy output.mp4

# Audio fade in/out
ffmpeg -i input.mp4 \
  -af "afade=t=in:st=0:d=1,afade=t=out:st=9:d=1" -c:v copy output.mp4
```

## Two-Pass Loudnorm (EBU R128)

Always two-pass. Single-pass acts as a dynamic compressor; two-pass applies linear gain and preserves dynamic range.

```bash
# Pass 1: measure
ffmpeg -i input.mp4 \
  -af "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json" \
  -f null - 2>loudnorm_stats.json

# Pass 2: apply (substitute measured values from stats)
ffmpeg -i input.mp4 \
  -af "loudnorm=I=-16:LRA=11:TP=-1.5:measured_I=-18.2:measured_LRA=9.1:measured_TP=-3.2:measured_thresh=-28.5:linear=true" \
  output_normalized.mp4
```

Target levels: YouTube `-14 LUFS` TP `-1 dBFS` | Streaming `-14 LUFS` TP `-2 dBFS` | Broadcast EBU R128 `-23 LUFS` TP `-1 dBFS`.

## Probe and Validate

```bash
# Get duration
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 input.mp4

# Full info as JSON
ffprobe -v quiet -print_format json -show_format -show_streams input.mp4

# Validate output is playable
ffprobe -v error -select_streams v:0 -show_entries stream=codec_name -of csv=p=0 output.mp4
```

## Common Errors

| Error | Fix |
|-------|-----|
| "height not divisible by 2" | Add `-vf "scale=trunc(iw/2)*2:trunc(ih/2)*2"` |
| Video won't play in browser | Use `-movflags faststart -pix_fmt yuv420p -c:v libx264` |
| Audio out of sync after speed change | Use `filter_complex` with matched `setpts` + `atempo` |
| Output 0 bytes | Check full ffmpeg output — silent failures hide in stderr |
| "encoder not found" | Install FFmpeg with full codecs (`brew install ffmpeg`) |
