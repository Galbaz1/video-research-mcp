---
name: creative-concept-design
description: Develop distinct visual treatments for a video or explainer, select one for its audience, and hand an executable production brief to the existing media skills. Use before storyboarding or production when the creative approach is still open.
---

# Creative Concept Design

Turn a message into a chosen treatment and a testable production handoff. Use
[production-brief.md](templates/production-brief.md) in the project's output directory.
It is an artifact specification, not a task tracker. Preserve the user's chosen
concept, supplied assets, delivery constraints and existing execution authority.

## Find the useful departure

1. Define the audience's prior knowledge, viewing context, central misunderstanding,
   desired takeaway and intended action. Name what must be understood after viewing.
2. Name a baseline and its assumptions: for example chronological explanation,
   literal diagrams, continuous narration, photographic realism or generating every
   asset. Mark constraints that are fixed by the user separately from assumptions.
3. Develop a small set of distinct concepts, normally three. Each drops a different
   baseline assumption. State its hook, visual mechanism and a concrete consequence
   for comprehension, emotion, production cost or risk. Palette changes alone are
   variants of one concept. Use existing assets where they serve the treatment.
4. Rank concepts by audience comprehension, memorable takeaway and feasibility
   within the authorized time/budget. Choose one and explain the decisive tradeoff;
   retain the runner-up and the condition under which it would be preferable.

For example, a mechanism explainer could replace chronology with a failure-first
reveal, replace literal scale with a labeled analogy, or replace constant voiceover
with an observable experiment and deliberate silence. Choose based on what the
audience needs to infer, not the quantity of generated imagery.

## Make the treatment executable

Specify visual grammar (layout, framing, palette, type and readable text), audio
character, pacing and continuity anchors. Give each beat a narration line or
intentional silence, duration estimate, source asset or generation prompt, motion
purpose and measurable acceptance criterion. Name exact on-screen wording.

For designed compositions, read [art direction](references/art-direction.md) for
video-scale type, hierarchy and staging. For moving diagrams or multi-beat edits,
read [motion and rhythm](references/motion-and-rhythm.md); its Remotion guidance
applies only when that renderer is already selected and available. For narration,
read [narration audition](references/narration-audition.md) alongside TTS production.

Map factual statements to supplied sources and label inference or uncertainty.
Keep illustrative motion distinct from measured behavior: arrows, particle speed,
scale, time compression and before/after transitions can imply quantity or
causation. State what each represents and label analogies where misunderstanding
is plausible. Generated scenes cannot establish facts, geometry or experimental
evidence; leave unsupported claims out of narration and quantitative graphics.

Use only the route needed for the chosen treatment:

| Production need | Existing skill and handoff |
|---|---|
| Reference image or edit | [image-generation](../image-generation/SKILL.md): subject, context, style, source references and exclusions |
| Generated moving shot | [video-generation](../video-generation/SKILL.md): action, camera, duration, supported input mode and inspected anchor |
| Narration | [tts-production](../tts-production/SKILL.md): exact script, pronunciation, delivery and timing requirements |
| Assembly/export | [ffmpeg-production](../ffmpeg-production/SKILL.md): measured clip/audio timing, transitions, captions and delivery format |
| Multi-shot continuity | [video-production](../video-production/SKILL.md): accepted assets, shot decisions and final inspection |
| Companion explainer pipeline | [video-explainer](../video-explainer/SKILL.md): brief/script injection and ordered steps, after verifying the installed companion and upstream checkout |

These are workflow instructions, not bundled generation providers. Discover the
actual tool/API surface; preserve a prepared brief if a required route is missing.
Do not invent tool names, endpoint parameters or renderer capabilities.
Read [current media routes](references/current-media-routes.md) when choosing
OpenAI/Google generation, AV review or an existing authored 3D/motion route.

## Prove the treatment before full production

Before any paid request, check the latest official model/endpoint documentation,
live availability, supported settings and price. For TTS, check the selected voice's
live access and model compatibility plus current account quota/credits. Use the
compatible model that fits the brief; a dated skill snapshot is a discovery lead.
Quota does not establish eligibility for a particular voice. Preserve a plan/voice
refusal; switching to an eligible voice needs to fit the brief and existing budget,
and a subscription upgrade requires separate authority.
Keep keys, private voice identifiers, raw quota/account receipts and private source
material in the project's private execution record, outside the reusable brief.

Fix one cumulative spend cap, attempt cap, concurrency and repair reserve for the
whole production, including auditions, drafts, animatics, repairs and final output.
Reserve pending operations against that cap and measure complete media inputs for
duration-based quotes. Retain request settings, output paths, estimated/actual cost
and operation IDs in the private record; reconcile unknown outcomes before another
submission. Poll the existing operation after timeout rather than duplicating it.
Unknown spend is unresolved, not zero, and cannot justify exceeding the cap.

For narration, make a short representative audition with the difficult terms and
the intended pace, emotion and pauses. Listen to the actual audio and record the
file, inspected interval and pronunciation/delivery decision before generating the
full narration. If narration is intentionally absent, record that choice.

Build a short representative animatic, normally 8–15 seconds, covering the hardest
explanatory beat and a transition with the selected voice sample or intended silence.
Use target aspect ratio and representative text size. Watch its motion playback and
listen to the mix; judge comprehension, motion purpose, continuity, timing,
readability, pronunciation and music/voice balance before full render. Still-image
inspection proves composition only. Placeholder assets/audio leave their corresponding
criteria unverified; replace and inspect those elements before accepting the treatment.

Repair one observed defect at a time, at most once per affected asset/beat within
the cumulative caps. Preserve failed/refused outputs. Stop on repeated infrastructure
failure, terminal refusal or an exhausted cap; report a simplified treatment or
unresolved criterion rather than silently changing route or model.

## Deliver evidence

Hand the filled brief and accepted audition/animatic to the selected sibling skills.
After final assembly, inspect the actual final playback and audio through every beat,
transition and ending. Record artifact path, inspection coverage, criterion decisions
and gaps. Probe/decode checks establish file properties, not editorial, motion or
auditory quality. If playback or listening is unavailable, say which criteria remain
unverified and return a preview or prepared handoff. Keep prepared, inspected local
final and published states distinct; publication uses the user's destination authority.
