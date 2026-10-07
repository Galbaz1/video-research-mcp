---
name: tts-production
description: Produces voiceover audio via ElevenLabs TTS API. Activates for TTS generation, voice tuning, audio ducking, or multilingual narration — not for voice AI agents, transcription, or music.
---

# TTS Production with ElevenLabs

Generate, audition and mix narration using the ElevenLabs Text-to-Speech API. Model guidance was checked on 2026-10-07 against the official [ElevenLabs TTS skill](https://github.com/elevenlabs/skills/blob/25bd9ad1c31af658fba6cc7d8ec1f1e2a715c049/text-to-speech/SKILL.md) and [models documentation](https://elevenlabs.io/docs/overview/models); re-check the live endpoint, voice eligibility, quota and price before execution.

This skill uses the official HTTP API; inspect the actual schema if an optional connector is used. Use [narration audition](../creative-concept-design/references/narration-audition.md) for spoken phrasing, delivery and the audition decision. Keep voice identifiers and account receipts in the private execution record.

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
      "similarity_boost": 0.80
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
  -d '{ "text": "Your text here", "model_id": "eleven_v4", "voice_settings": { "stability": 0.75, "similarity_boost": 0.80 } }' \
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
| `eleven_v4_turbo` | Text-to-Dialogue WebSocket for real-time use | Check live latency | Separate endpoint, not a drop-in HTTP model |
| `eleven_multilingual_v2` | Existing multilingual narration workflows | Established | Retain when voice or endpoint compatibility requires it |
| `eleven_flash_v2_5` | Fast drafts or realtime workloads | Low latency | Evaluate pronunciation and timing |

Select for the actual voice, language and endpoint. Model language support does not prove that a chosen voice pronounces the script well. Preserve failed/refused requests; do not silently fall back after a paid attempt.

## Voice Settings

| Parameter | Range | Effect | Production Range |
|-----------|-------|--------|-----------------|
| `stability` | 0–1 | Low=expressive, High=consistent | 0.55–0.75 |
| `similarity_boost` | 0–1 | Voice matching fidelity | 0.80–0.90 |

For `eleven_v4`, use only `stability` and `similarity_boost`. Do not send `style`, `speed`, `use_speaker_boost` or SSML; these are not supported v4 controls. Supported audio tags, punctuation and spoken phrasing can direct delivery, but their result must be auditioned. The TTS `stream-input` WebSocket does not support v4.

### Audition starting points for v4

**Neutral narration** (clean, informational):
```json
{ "stability": 0.75, "similarity_boost": 0.80 }
```

**Cinematic narration** (authoritative, confident):
```json
{ "stability": 0.55, "similarity_boost": 0.85 }
```

**Warm/conversational:**
```json
{ "stability": 0.60, "similarity_boost": 0.75 }
```

## Workflow

1. Check current voice/model access and output-format eligibility separately from available quota. A voice can return `402` / `paid_plan_required` even with remaining characters. Preserve the refusal; another eligible voice must fit the brief and budget. A plan upgrade needs separate authority.
2. Allocate audition, full narration and any one targeted repair within one cumulative production cap. Retain request/operation IDs and measured usage; reconcile unknown outcomes before another submission.
3. Generate a representative audition with difficult words, numbers and intended pauses. Listen to the actual saved audio before accepting the voice and delivery.
4. Generate full narration with timestamps when the selected endpoint supports them. Measure duration with `ffprobe -i clip.mp3 -show_entries format=duration -v quiet -of csv="p=0"`; listen through all clauses and any stitched boundaries.
5. Mix the accepted audio into the representative animatic and final video using [FFmpeg Audio Recipes](references/ffmpeg-audio-recipes.md), then listen to both mixes.

## QA and bounded repair

- Adjust v4 pacing by improving spoken phrasing, pauses and supported delivery directions, then audition; do not add a `speed` parameter.
- If existing audio is time-stretched with FFmpeg, listen for artifacts and recompute/rescale alignment. No universal tempo factor guarantees natural speech.
- **Hard step ducking** causes audible clicks — always use cosine-ease transitions
- Duration and expressive quality vary by voice/model; measure the actual output instead of assuming an ordering.
- Check the target language and audition pronunciation with the selected voice; language support alone is insufficient.

Check HTTP success before decoding, and confirm non-empty playable audio plus alignment before deriving timing. Listen for pronunciation, omissions, clicks and pauses. Changing tempo invalidates original timestamps; divide timing by the tempo multiplier or realign. Repair one observed defect at most once within the agreed budget. Probe/decode and transcription checks do not establish delivery quality; report any missing listening coverage.

## Environment

| Variable | Required | Notes |
|----------|----------|-------|
| `ELEVENLABS_API_KEY` | Yes | Set in shell or `~/.config/video-research-mcp/.env` |

## References

- [FFmpeg Audio Recipes](references/ffmpeg-audio-recipes.md) — ducking, mixing, normalization, multi-element assembly

- [Create speech with timing](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps) — request/response contract
- [Gemini 3.8 Flash TTS](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash-tts) — optional alternate provider; requires structured `speech_metadata` directions and returns WAV by default. This plugin does not implement that provider directly.
