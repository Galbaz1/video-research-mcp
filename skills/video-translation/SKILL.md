---
name: video-translation
description: Translate existing video speech and produce an optional speaker-guided dub with exact source/VAD/transcript joins, local stems, bounded timing, executable technical QA and separate unresolved listening review.
---

# Video translation

Inspect one durable project with get_video_translation_state. Follow the first
applicable route: validate/listen to a current delivery, resume a validated plan,
translate accepted evidence, or prepare/analyze a new source.
Read [the integration contract](../../docs/integrations/qwen-dubbing.md) for
operator configuration, strict schemas, limits, source mappings and readiness.

The complete workflow is source video → local stems/VAD → reconciled transcript →
spoken translation groups/references → local dubbed render → technical QA →
separately supplied listening review. Preparation/rendering are executable;
source interpretation and translation remain agent work. The external service
and isolated Qwen ChatCut must be independently licensed/configured. Missing or
unready service is terminal readiness evidence. Never auto-download/launch models,
select a credit/provider fallback or treat readiness as submission/voice authority.

## Source analysis

With explicit authority for the source and external operations, call
check_dubbing_service and prepare_video_translation_project using the actual
SHA256, project directory and languages. Preparation extracts full PCM, invokes
separate_dubbing_audio and detect_dubbing_speech through the exact contracts, and
stores returned audio locally. Never use server-local paths.
Pass the requested analysis_only, translation_only, full or resume target and
retain the user-approved style_brief. Standalone separation supports the source
model selector; detect_dubbing_speech accepts strict VadSettings for the verified
threshold/hop/minimum-run/padding controls. synthesize_dubbing_speech executes one
approved utterance/reference pair and returns local PCM with unresolved listening.

Use independently configured isolated ChatCut omni_call for speech, visible
subtitles, speakers and approximate absolute times. The documented entry point
is pinned to Qwen-MM-Plugins 07736672525443c7f8a3f6405eed37d2236f023f; installation
and availability remain unknown until checked. Do not silently change providers.
At duration <=600 seconds, request the complete source once; longer recordings
require ordered bounded windows, complete coverage and reconciled overlaps.

Reconcile audio, visible subtitles, VAD, continuity and audible boundaries. VAD is
speech presence, not speaker/sentence authority; low overlap is a review flag.
Do not invent OCR when subtitles are absent. Write Transcript to
analysis/transcript.json with source/VAD hashes, detected language,
evidence_windows, ordered source segments and unresolved_issues. Material
unresolved facts block rendering. Analysis-only stops after transcript review.

## Translation and per-group references

Author TranslationPlan in plan/translation_plan.json. Copy exact source/VAD/
transcript hashes and languages. Preserve meaning, names, tone and natural spoken
delivery. Consume each transcript segment exactly once and in order; merge
adjacent same-speaker items when appropriate, recording exact IDs/text/span and a
concrete reason. Never merge across speakers or hide omitted meaning with speed.

Choose an evidenced reference independently per group: its own clean speech
first, preferably >=1.5 seconds; adjacent same-speaker items with gaps <=1.2 seconds
next; nearby clean same-speaker speech if needed. Record IDs, interval and reason.
Never select another speaker or use real enrollment/registry operations. The
service retains its default emotion settings.

Call validate_video_translation_plan. Duration estimates are only diagnostics.
Revise only the affected translation/group/reference when evidence is unresolved
or speech cannot fit. Translation-only stops after validation.

## Render, resume and listening

Review the complete background stem; omit it only after a whole-stem decision.
Keep include when uncertain. Call render_video_translation with the valid plan.
It cuts exact references, uses journaled TTS candidates, preserves short speech
pace, borrows at most 0.3 seconds/half adjacent gaps, centers silence/fades and
accelerates at most 1.18x. Known overlong speech permits at most three candidates
for that group when the estimate is <=1.35x; cached candidates count toward the
total. Unknown/interrupted effects stop for reconciliation without another request.

Voices retain their source timeline. The full background is mixed when selected
with normalize=0; measured two-pass normalization is applied once to the final
mix. Supported source video/subtitle streams are copied into Matroska with
lossless dubbed audio. QA checks output identity, all streams, duration, full
decode, stream preservation, replaced audio, actual decoded mix and source/stem/
segment accounting. Unsupported streams fail explicitly. Each content-addressed
render preserves its outputs/failures; full/current.json selects a report.
Resume only content-matching completed effects. Never reset or rename unknown
intent to make it runnable again.
After a listening issue, pass regenerate_segment_ids for only the affected known
groups; keep successful groups unchanged. Unknown effects block even across
changed plans and generation names. Exhausted overlong speech requires revised
translation. Full source/stem refresh uses a new prepared project with fresh
evidence joins, preserving the earlier project.

Surface output/report links, segment count, every timing/risk flag and all
unresolved listening segments with time range, translated text and reason.
Inspect acceleration >1.12x, fill <60%, short references, merged units, silence,
retries, order/overlap, meaning, pronunciation, identity drift and mix balance.
Listen end to end even with no automatic flags. Write ListeningReview beside
the selected report, bound to output/plan hashes, with all five checks per segment:
translation, timing, voice_reference, natural_delivery and mix. Retain FAIL and
UNRESOLVED cases.

Call validate_video_translation_delivery. Never manufacture listening PASS from
technical QA, duration estimates, model confidence or filenames. Report supplied
review assertions separately from independent listening/service/model/native
qualification and Root's product acceptance.

Protocol/workflow attribution: QwenLM/Qwen-MM-Plugins at the pin above,
Apache-2.0 original code/skills. This is an independently authored integration
workflow; no original implementation, launcher or model is copied/bundled.
