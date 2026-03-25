# Platform Export Presets

Platform-specific FFmpeg recipes for distributing finished video.

## Platform Requirements

| Platform | Max Resolution | Max Size | Max Duration | Audio |
|----------|---------------|----------|--------------|-------|
| YouTube | 8K | 256GB | 12 hours | AAC 48kHz |
| YouTube Shorts | 1080x1920 | 256GB | 60s | AAC 48kHz |
| Twitter/X | 1920x1200 | 512MB | 140s | AAC 44.1kHz |
| LinkedIn | 4096x2304 | 5GB | 10 min | AAC 48kHz |
| Instagram Feed | 1080x1350 | 4GB | 60s | AAC 48kHz |
| Instagram Reels | 1080x1920 | 4GB | 90s | AAC 48kHz |
| TikTok | 1080x1920 | 287MB | 10 min | AAC |

## YouTube

YouTube re-encodes everything. Upload high quality.

```bash
# YouTube 1080p
ffmpeg -i input.mp4 \
  -c:v libx264 -preset slow -crf 18 \
  -profile:v high -level 4.0 \
  -bf 2 -g 30 \
  -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart \
  output-youtube.mp4

# YouTube Shorts (vertical 1080x1920)
ffmpeg -i input.mp4 \
  -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" \
  -c:v libx264 -crf 18 -c:a aac -b:a 192k \
  output-shorts.mp4
```

## TikTok

Vertical 9:16 required. Keep file under 287MB.

```bash
# TikTok vertical
ffmpeg -i input.mp4 \
  -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" \
  -c:v libx264 -preset medium -crf 22 \
  -c:a aac -b:a 128k -ar 44100 \
  -movflags +faststart \
  output-tiktok.mp4
```

## Instagram

```bash
# Instagram Feed (square 1080x1080)
ffmpeg -i input.mp4 \
  -vf "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080" \
  -c:v libx264 -preset medium -crf 22 \
  -c:a aac -b:a 128k -ar 48000 \
  -movflags +faststart \
  -t 60 \
  output-ig-feed.mp4

# Instagram Feed (portrait 1080x1350 — more screen real estate)
ffmpeg -i input.mp4 \
  -vf "scale=1080:1350:force_original_aspect_ratio=decrease,pad=1080:1350:(ow-iw)/2:(oh-ih)/2" \
  -c:v libx264 -preset medium -crf 22 \
  -c:a aac -b:a 128k -ar 48000 \
  -movflags +faststart \
  -t 60 \
  output-ig-portrait.mp4

# Instagram Reels (vertical 1080x1920)
ffmpeg -i input.mp4 \
  -vf "scale=1080:1920:force_original_aspect_ratio=decrease,pad=1080:1920:(ow-iw)/2:(oh-ih)/2" \
  -c:v libx264 -preset medium -crf 22 \
  -c:a aac -b:a 128k -ar 48000 \
  -movflags +faststart \
  -t 90 \
  output-ig-reels.mp4
```

## Twitter/X

Strict limits: max 140s, 512MB, 1920x1200.

```bash
# Twitter optimized (target <15MB for fast upload)
ffmpeg -i input.mp4 \
  -c:v libx264 -preset medium -crf 24 \
  -profile:v main -level 3.1 \
  -vf "scale='min(1280,iw)':'min(720,ih)':force_original_aspect_ratio=decrease" \
  -c:a aac -b:a 128k -ar 44100 \
  -movflags +faststart \
  -fs 15M \
  output-twitter.mp4

# Verify size and duration
ffprobe -v error -show_entries format=duration,size -of csv=p=0 output-twitter.mp4
```

## LinkedIn

```bash
ffmpeg -i input.mp4 \
  -c:v libx264 -preset medium -crf 22 \
  -profile:v main \
  -vf "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease" \
  -c:a aac -b:a 192k -ar 48000 \
  -movflags +faststart \
  output-linkedin.mp4
```

## Web Embed

```bash
# MP4 (progressive loading, small file)
ffmpeg -i input.mp4 \
  -c:v libx264 -preset medium -crf 26 \
  -profile:v baseline -level 3.0 \
  -vf "scale=1280:720" \
  -c:a aac -b:a 128k \
  -movflags +faststart \
  output-web.mp4

# WebM (better compression)
ffmpeg -i input.mp4 \
  -c:v libvpx-vp9 -crf 30 -b:v 0 \
  -vf "scale=1280:720" \
  -c:a libopus -b:a 128k \
  -deadline good \
  output-web.webm
```

## GIF Preview

```bash
# High-quality GIF (first 5 seconds)
ffmpeg -i input.mp4 -t 5 \
  -vf "fps=15,scale=480:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  preview.gif

# Smaller GIF (first 3 seconds)
ffmpeg -i input.mp4 -t 3 \
  -vf "fps=10,scale=320:-1:flags=lanczos,split[s0][s1];[s0]palettegen[p];[s1][p]paletteuse" \
  preview-small.gif
```

## Batch Export Script

```bash
#!/bin/bash
INPUT="${1:?Usage: export-all.sh <input.mp4>}"
BASE="${INPUT%.*}"

ffmpeg -i "$INPUT" -c:v libx264 -preset slow -crf 18 \
  -c:a aac -b:a 192k -movflags +faststart "${BASE}-youtube.mp4"

ffmpeg -i "$INPUT" -c:v libx264 -crf 24 \
  -vf "scale='min(1280,iw)':'-2'" \
  -c:a aac -b:a 128k -movflags +faststart "${BASE}-twitter.mp4"

ffmpeg -i "$INPUT" -c:v libx264 -crf 22 \
  -c:a aac -b:a 192k -movflags +faststart "${BASE}-linkedin.mp4"

ffmpeg -i "$INPUT" -c:v libx264 -crf 26 \
  -vf "scale=1280:720" \
  -c:a aac -b:a 128k -movflags +faststart "${BASE}-web.mp4"

echo "Exported:" && ls -lh "${BASE}"-*.mp4
```

## Codec Comparison

| Codec | Container | Compression | Encode speed | Decode support | Best for |
|-------|-----------|-------------|-------------|----------------|----------|
| libx264 (H.264) | MP4 | Good | Fast | Universal | Web, streaming, social |
| libx265 (H.265) | MP4 | ~40% better | 2-5x slower | Most modern devices | Archive, master files |
| libsvtav1 (AV1) | MP4/WebM | ~50% better | Slow | Growing | Distribution with size limits |
| libvpx-vp9 (VP9) | WebM | ~30% better | Moderate | All browsers | Web embed alternative |

## AV1 Film Grain Synthesis

For grain-heavy AI content, AV1 FGS encodes grain as metadata (not pixels), saving significant bitrate.

```bash
# Step 1: denoise source
ffmpeg -i input.mp4 -vf "nlmeans=s=5" -c:v libx265 -crf 16 denoised.mp4

# Step 2: encode with FGS metadata
ffmpeg -i denoised.mp4 -c:v libsvtav1 -crf 30 \
  -svtav1-params "tune=0:film-grain=8:film-grain-denoise=0" output.av1.mp4
```

- `tune=0` = subjective quality mode (recommended with FGS)
- `film-grain-denoise=0` = skip internal denoising (source already denoised)

## Hardware Acceleration

### macOS (VideoToolbox)

```bash
# H.264 hardware encode
ffmpeg -i input.mp4 -c:v h264_videotoolbox -b:v 5M output.mp4

# H.265 hardware encode
ffmpeg -i input.mp4 -c:v hevc_videotoolbox -b:v 5M output.mp4
```

### NVIDIA (NVENC)

```bash
# H.264 NVENC
ffmpeg -hwaccel cuda -i input.mp4 -c:v h264_nvenc -preset p7 -crf 20 output.mp4

# H.265 NVENC
ffmpeg -hwaccel cuda -i input.mp4 -c:v hevc_nvenc -preset p7 -crf 20 output.mp4
```

Hardware encoders trade quality for speed. Use software encoding (libx264/libx265) for final masters; hardware for previews, drafts, and batch processing.

## Frame Interpolation (minterpolate)

For clean slow-motion, use `mci:mc_mode=aobmc:me_mode=bidir`. The default `blend` mode only works for mild slowdowns.

```bash
# High-quality 2x slow motion (aobmc — required for clean results)
ffmpeg -i input.mp4 \
  -vf "minterpolate=fps=48:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1" \
  output_slow.mp4

# Fast blend mode (mild slow-down only)
ffmpeg -i input.mp4 -vf "minterpolate=fps=48:mi_mode=blend" output.mp4
```

`mci:aobmc` is single-threaded. For long clips, chunk and parallel-process.
