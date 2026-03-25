---
name: tts-production
description: Produces voiceover audio via ElevenLabs TTS API. Activates for TTS generation, voice tuning, audio ducking, or multilingual narration — not for voice AI agents, transcription, or music.
---

# TTS Production with ElevenLabs

Generate, tune, and mix voice-over audio using the ElevenLabs Text-to-Speech API.

> **Critical:** Use direct API calls (curl), NOT ElevenLabs MCP tools. The MCP `Text_To_Speech` tool returns 404 due to routing issues. Direct API is reliable and battle-tested.

## API Pattern

### Text-to-Speech with Timestamps (recommended)

```bash
curl -s -X POST "https://api.elevenlabs.io/v1/text-to-speech/${VOICE_ID}/with-timestamps" \
  -H "xi-api-key: ${ELEVENLABS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Your text here",
    "model_id": "eleven_multilingual_v2",
    "voice_settings": {
      "stability": 0.75,
      "similarity_boost": 0.80,
      "style": 0.40,
      "use_speaker_boost": true
    }
  }' \
  --output /tmp/tts-response.json
```

### Decode Response

```python
import json, base64
with open('/tmp/tts-response.json', 'r') as f:
    data = json.load(f)
audio_bytes = base64.b64decode(data['audio_base64'])
with open('output.mp3', 'wb') as f:
    f.write(audio_bytes)
ends = data.get('alignment', {}).get('character_end_times_seconds', [])
print(f'Duration: {ends[-1]:.2f}s' if ends else 'No timestamps')
```

### Simple TTS (no timestamps)

```bash
curl -s -X POST "https://api.elevenlabs.io/v1/text-to-speech/${VOICE_ID}" \
  -H "xi-api-key: ${ELEVENLABS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{ "text": "...", "model_id": "eleven_multilingual_v2", "voice_settings": {...} }' \
  --output output.mp3
```

### Sound Effects Generation

```bash
curl -s -X POST "https://api.elevenlabs.io/v1/sound-generation" \
  -H "xi-api-key: ${ELEVENLABS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{ "text": "short sharp underwater splash blip", "duration_seconds": 1.0, "prompt_influence": 0.8 }' \
  --output sfx.mp3
```

## Model Selection

| Model | Use Case | Speed | Quality |
|-------|----------|-------|---------|
| `eleven_multilingual_v2` | **Production** — Dutch, English, mixed language | Slow | Highest |
| `eleven_flash_v2_5` | Quick drafts, iteration | Fast | Good |
| `eleven_turbo_v2_5` | Real-time, low latency | Fastest | Acceptable |

Always use `eleven_multilingual_v2` for final production. Flash/turbo for iteration only.

## Voice Settings

| Parameter | Range | Effect | Production Range |
|-----------|-------|--------|-----------------|
| `stability` | 0–1 | Low=expressive, High=consistent | 0.55–0.75 |
| `similarity_boost` | 0–1 | Voice matching fidelity | 0.80–0.90 |
| `style` | 0–1 | Emotional expressiveness | 0.30–0.70 |
| `use_speaker_boost` | bool | Clarity enhancement | `true` for narration |
| `speed` | 0.5–2.0 | **Top-level param, NOT in voice_settings.** Only works with flash/turbo |

### Proven Presets

**Neutral narration** (clean, informational):
```json
{ "stability": 0.75, "similarity_boost": 0.80, "style": 0.40 }
```

**Cinematic narration** (authoritative, confident):
```json
{ "stability": 0.55, "similarity_boost": 0.85, "style": 0.70, "use_speaker_boost": true }
```

**Warm/conversational:**
```json
{ "stability": 0.60, "similarity_boost": 0.75, "style": 0.55, "use_speaker_boost": true }
```

## Workflow

1. Generate TTS with timestamps (for timing QA)
2. Verify duration: `ffprobe -i clip.mp3 -show_entries format=duration -v quiet -of csv="p=0"`
3. If too slow: `ffmpeg -y -i clip.mp3 -filter:a "atempo=1.2" -codec:a libmp3lame -b:a 192k clip-fast.mp3` (max 1.35x sounds natural)
4. If delivery needs work: lower `stability` (more expressive), raise `style` (more emotional)
5. Mix into video — see [FFmpeg Audio Recipes](references/ffmpeg-audio-recipes.md)

## Constraints (learned from production)

- **`speed` param is silently ignored** by `eleven_multilingual_v2` — use FFmpeg `atempo` instead
- **`atempo` above 1.35x** sounds unnatural for narration
- **Hard step ducking** causes audible clicks — always use cosine-ease transitions
- **Flash/turbo models** produce longer output and lower quality for cinematic voices
- One voice can handle multiple languages — the `eleven_multilingual_v2` model auto-detects language from text

## Environment

| Variable | Required | Notes |
|----------|----------|-------|
| `ELEVENLABS_API_KEY` | Yes | Set in shell or `~/.config/video-research-mcp/.env` |

## References

- [FFmpeg Audio Recipes](references/ffmpeg-audio-recipes.md) — ducking, mixing, normalization, multi-element assembly
