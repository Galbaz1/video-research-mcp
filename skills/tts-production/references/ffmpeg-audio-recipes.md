# FFmpeg Audio Recipes for TTS Production

Patterns for mixing voice-over into video, audio ducking, and multi-element assembly.

## Speed Adjustment

```bash
# Speed up (atempo range: 0.5–2.0, natural limit: 1.35x)
ffmpeg -y -i input.mp3 -filter:a "atempo=1.2" -codec:a libmp3lame -b:a 192k output.mp3
```

## Loudness Normalization (EBU R128)

Two-pass for broadcast-standard loudness:

```bash
# Pass 1: measure
ffmpeg -i input.mp3 -af "loudnorm=I=-16:LRA=11:TP=-1.5:print_format=json" -f null - 2>stats.json

# Pass 2: apply (use measured_I, measured_LRA, measured_TP, measured_thresh from stats)
ffmpeg -i input.mp3 -af "loudnorm=I=-16:LRA=11:TP=-1.5:measured_I=X:measured_LRA=Y:measured_TP=Z:measured_thresh=W:linear=true" output.mp3
```

## Simple Ducking + Voice Overlay

Basic pattern: duck music during voice, overlay voice at timestamp.

```bash
ffmpeg -y -i video.mp4 -i voice.mp3 \
  -filter_complex "
    [0:a]volume='if(between(t,START,END),0.45,1)':eval=frame[music];
    [1:a]adelay=START_MS|START_MS[voice];
    [music][voice]amix=inputs=2:duration=first:dropout_transition=0[out]
  " \
  -map 0:v -map "[out]" -c:v copy -c:a aac -b:a 192k -movflags +faststart output.mp4
```

## Smooth Cosine-Ease Ducking (recommended)

Hard step ducking causes audible clicks. Use cosine-ease ramps instead:

```
# Single zone (ramp_duration=0.5s, duck_level=0.55 = 55% reduction):
volume='1.0 - 0.55 * (
  (0.5 - 0.5*cos(3.14159265 * clip((t - ZONE_START) / 0.5, 0, 1)))
  * (0.5 - 0.5*cos(3.14159265 * clip((ZONE_END - t) / 0.5, 0, 1)))
)':eval=frame
```

### Multiple Zones

Chain zones with addition. Each zone is a pair of cosine ramps:

```
volume='1.0 - 0.55 * (
  (0.5-0.5*cos(PI*clip((t-Z1_START)/0.5,0,1))) * (0.5-0.5*cos(PI*clip((Z1_END-t)/0.5,0,1)))
  + (0.5-0.5*cos(PI*clip((t-Z2_START)/0.5,0,1))) * (0.5-0.5*cos(PI*clip((Z2_END-t)/0.5,0,1)))
  + (0.5-0.5*cos(PI*clip((t-Z3_START)/0.5,0,1))) * (0.5-0.5*cos(PI*clip((Z3_END-t)/0.5,0,1)))
)':eval=frame
```

Where `PI = 3.14159265`, `0.5` is ramp duration, `0.55` is duck depth.

**Tuning parameters:**
- Ramp duration: 0.3s (quick) to 1.0s (gentle). 0.5s is default.
- Duck depth: 0.45 (subtle) to 0.65 (aggressive). 0.55 works for most narration.
- Zone boundaries: start ducking ~0.5s before voice starts, end ~1s after voice ends.

## Multi-Element Assembly

Pattern for mixing N voice blocks + SFX over music with ducking:

```bash
ffmpeg -y \
  -i video.mp4 \
  -i music.wav \
  -i sfx1.mp3 \
  -i sfx2.mp3 \
  -i voice1.mp3 \
  -i voice2.mp3 \
  -i voice3.mp3 \
  -filter_complex "
    [1:a]DUCKING_EXPRESSION[music];
    [2:a]adelay=SFX1_MS|SFX1_MS,volume=0.7[sfx1];
    [3:a]adelay=SFX2_MS|SFX2_MS,volume=0.8[sfx2];
    [4:a]adelay=V1_MS|V1_MS[v1];
    [5:a]adelay=V2_MS|V2_MS[v2];
    [6:a]adelay=V3_MS|V3_MS[v3];
    [music][sfx1][sfx2][v1][v2][v3]amix=inputs=6:duration=first:dropout_transition=0:normalize=0[out]
  " \
  -map 0:v -map "[out]" \
  -c:v copy -c:a aac -b:a 192k -ar 44100 \
  -movflags +faststart \
  output.mp4
```

**Key flags:**
- `dropout_transition=0` — no fade between elements
- `normalize=0` — prevent auto-normalization that compresses dynamic range
- `adelay=MS|MS` — delay in milliseconds, both channels
- `-movflags +faststart` — web-optimized MP4

## Music Preprocessing

Remove unwanted frequencies from specific sections (e.g., remove sub-bass heartbeat):

```bash
# Remove bass from first 32s
ffmpeg -i music.wav -af "highpass=f=85:poles=2" -t 32 music-clean-0-32.wav

# Keep original from 30s onward
ffmpeg -i music.wav -ss 30 music-original-30-end.wav

# Crossfade at overlap (30-32s)
ffmpeg -i music-clean-0-32.wav -i music-original-30-end.wav \
  -filter_complex "[0:a][1:a]acrossfade=d=2:c1=tri:c2=tri[out]" -map "[out]" music-processed.wav

# Add fade-out
ffmpeg -i music-processed.wav -af "afade=t=out:st=52:d=4" music-final.wav
```

## Localization Pattern

To create a translated version of a narrated video:

1. Translate text blocks
2. Generate TTS per block (same voice + settings)
3. Keep SFX and music pipeline unchanged
4. Adjust `adelay` values if block durations differ
5. Recalculate ducking zones to match new timing
6. Run assembly command with substituted voice files

**Constraint:** Final voice block must finish with enough visual cool-down before video end.
