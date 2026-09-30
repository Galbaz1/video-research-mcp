---
name: tts-production
description: Produces voiceover audio via ElevenLabs TTS API. Activates for TTS generation, voice tuning, audio ducking, or multilingual narration — not for voice AI agents, transcription, or music.
---

# TTS Production with ElevenLabs

Generate, tune, and mix voice-over audio using the ElevenLabs Text-to-Speech API. Provider/model guidance below was checked on 2026-09-29; re-check compatibility and price before execution.

This skill uses the official HTTP API; an ElevenLabs MCP connector is optional and its schema must be inspected if used. Confirm the voice, model availability, output format, and authorized spend before generation. Never infer a current connector failure from an old local incident.

## API Pattern

### Text-to-Speech with Timestamps (recommended)

```bash
curl --fail-with-body -sS -X POST "https://api.elevenlabs.io/v1/text-to-speech/${VOICE_ID}/with-timestamps" \
  -H "xi-api-key: ${ELEVENLABS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{
    "text": "Your text here",
    "model_id": "eleven_v4",
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
curl --fail-with-body -sS -X POST "https://api.elevenlabs.io/v1/text-to-speech/${VOICE_ID}" \
  -H "xi-api-key: ${ELEVENLABS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{ "text": "...", "model_id": "eleven_multilingual_v2", "voice_settings": {...} }' \
  --output output.mp3
```

### Sound Effects Generation

```bash
curl --fail-with-body -sS -X POST "https://api.elevenlabs.io/v1/sound-generation" \
  -H "xi-api-key: ${ELEVENLABS_API_KEY}" \
  -H "Content-Type: application/json" \
  -d '{ "text": "short sharp underwater splash blip", "duration_seconds": 1.0, "prompt_influence": 0.8 }' \
  --output sfx.mp3
```

## Model Selection

| Model | Use Case | Speed | Quality |
|-------|----------|-------|---------|
| `eleven_v4` | Current expressive narration model | Check live latency | Audition for the brief |
| `eleven_v4_turbo` | Current expressive real-time model | Low latency | Audition for the brief |
| `eleven_multilingual_v2` | Existing multilingual narration workflows | Established | Retain when voice or endpoint compatibility requires it |
| `eleven_flash_v2_5` | Fast drafts or realtime workloads | Low latency | Evaluate pronunciation and timing |

Verified on 2026-09-29 against [ElevenLabs models](https://elevenlabs.io/docs/overview/models). Newest does not guarantee the best result for a particular voice. Read the current endpoint/model support before using model-specific settings; do not silently fall back after a failed paid attempt.

## Voice Settings

| Parameter | Range | Effect | Production Range |
|-----------|-------|--------|-----------------|
| `stability` | 0–1 | Low=expressive, High=consistent | 0.55–0.75 |
| `similarity_boost` | 0–1 | Voice matching fidelity | 0.80–0.90 |
| `style` | 0–1 | Emotional expressiveness | 0.30–0.70 |
| `use_speaker_boost` | bool | Clarity enhancement | `true` for narration |
| `speed` | Verify endpoint range | Set inside `voice_settings`; 1.0 is normal pace |

### Starting Presets (model-dependent)

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
3. First adjust supported `voice_settings.speed` and audition. For existing audio, if too slow: `ffmpeg -y -i clip.mp3 -filter:a "atempo=1.2" -codec:a libmp3lame -b:a 192k clip-fast.mp3` (max 1.35x sounds natural)
4. If delivery needs work: lower `stability` (more expressive), raise `style` (more emotional)
5. Mix into video — see [FFmpeg Audio Recipes](references/ffmpeg-audio-recipes.md)

## QA and bounded repair

- Current [voice settings](https://elevenlabs.io/docs/api-reference/voices/settings/get) include `speed`. [Pace guidance](https://elevenlabs.io/docs/help-center/product/core-capabilities/text-to-speech/can-i-change-the-pace-of-the-voice) documents 0.7–1.2; verify the selected endpoint rather than using a historical unsupported top-level parameter.
- Treat 1.35x `atempo` as a starting QA limit, then listen; intelligibility depends on the actual voice and material
- **Hard step ducking** causes audible clicks — always use cosine-ease transitions
- Duration and expressive quality vary by voice/model; measure the actual output instead of assuming an ordering.
- One voice can handle multiple languages — the `eleven_multilingual_v2` model auto-detects language from text

Check that the HTTP request succeeded before decoding, the audio file is non-empty and playable, and alignment is present before deriving timing. Listen for pronunciation, omissions, clicks, and pauses. Changing speed with FFmpeg invalidates the original timestamps; rescale alignment by the same factor. Repair one specific defect at most once within the agreed budget, then return the verified file or preserved failure.

## Environment

| Variable | Required | Notes |
|----------|----------|-------|
| `ELEVENLABS_API_KEY` | Yes | Set in shell or `~/.config/video-research-mcp/.env` |

## References

- [FFmpeg Audio Recipes](references/ffmpeg-audio-recipes.md) — ducking, mixing, normalization, multi-element assembly

- [Create speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps) — request/response contract
- [Gemini 3.8 Flash TTS](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts) — optional alternate provider; requires structured `speech_metadata` directions and returns WAV by default. This plugin does not implement that provider directly.
