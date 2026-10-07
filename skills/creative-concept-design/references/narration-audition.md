# Narration direction and audition

Use with [TTS production](../../tts-production/SKILL.md) after the treatment and
spoken claims are fixed. Keep the visible script and spoken form linked: write
numbers, acronyms and unfamiliar terms as the audience should hear them, while
preserving exact source values and identifying any deliberate approximation.

Write for listening: one idea per clause, varied sentence lengths and pauses
where a visual change needs attention. Read the script aloud before generation.
Words-per-second estimates are planning aids; accepted audio supplies actual
timing. A clear, shorter line is preferable to squeezing an untested fast delivery
into a fixed beat. Preserve intentional silence and the user's chosen language.

## Current Eleven v4 boundary

Checked 2026-10-07: `eleven_v4` supports `stability` and `similarity_boost` voice
settings. Do not send `style`, `speed`, `use_speaker_boost` or SSML for v4.
Delivery can use supported audio tags, natural punctuation and rewritten spoken
phrasing; audition their actual effect. The TTS `stream-input` WebSocket is not
the v4 route. `eleven_v4_turbo` uses Text-to-Dialogue WebSocket; it is not a
drop-in model change for a timestamps HTTP request.

Check the live model/endpoint, chosen voice access, target-language capability,
output format, account quota and cumulative project allowance before a request.
Quota and voice eligibility are separate: a library voice may require a paid plan
even with unused characters. Preserve `402` / `paid_plan_required` as a refusal.
Choose another eligible voice only within the brief and existing authority;
do not upgrade the plan or silently change model after a refusal.

## Listen before committing the full script

Choose a short excerpt containing the hardest term, a number, an emotional change
and a representative pause. Generate one audition under the production budget.
Listen to the exact saved audio, checking pronunciation, omitted words, language,
cadence, accent, tone and pauses. Record file and listened interval; waveform,
transcription and codec checks cannot establish delivery quality.

Repair one observed defect once within the cumulative caps. Prefer editing the
spoken phrase or supported settings to changing several controls together.
Generate the full script after accepting the audition, measure its duration and
listen through every clause and stitched boundary. Audition acceptance does not
prove the full narration. If time-stretching is used, re-check audible quality and
rescale/recompute alignment; original timestamps no longer match the new audio.

## Attribution and checks

This is newly written guidance informed by ElevenLabs' official
[TTS skill](https://github.com/elevenlabs/skills/blob/25bd9ad1c31af658fba6cc7d8ec1f1e2a715c049/text-to-speech/SKILL.md)
(repository [MIT license](https://github.com/elevenlabs/skills/blob/25bd9ad1c31af658fba6cc7d8ec1f1e2a715c049/LICENSE)),
[models documentation](https://elevenlabs.io/docs/overview/models) and
[timestamps endpoint](https://elevenlabs.io/docs/api-reference/text-to-speech/convert-with-timestamps),
checked 2026-10-07. No upstream code, voice identifiers or account receipts are
bundled. Dutch is documented as a supported v4 language; pronunciation and voice
eligibility still require the selected voice's live checks and audition.
