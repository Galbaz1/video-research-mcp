# Repaired prospective tiny-render qualification

This preparation addendum addresses two independent review findings in the
retained `.8.19` report: optional playback and an unconfirmed composition duration.
The old report, receipts and component outcomes remain unchanged. No render,
browser playback, installation or runtime qualification was performed here.

The coordinator read the complete pinned `remotion/src/Root.tsx` and the relevant
duration and audio ranges of `scenes/SceneStoryboardPlayer.tsx` at source pin
`c033e28`. The `ScenePlayer` composition has 30 FPS and calculates metadata from
the supplied storyboard using `Math.ceil(calculateStoryboardDuration(storyboard)
* 30)`. The duration helper sums audio duration, scene buffer and visual padding.
The proposed one scene has 1.000-second PCM audio, explicit zero buffer and zero
padding, so its composition duration is 30 frames. With one last scene there is
no transition padding. The global font loads still run at module import; a
font-free scene does not remove that prerequisite.

Freeze the first-party fixture described in the retained report: one frame-pure
solid card, one original 48 kHz mono PCM16 WAV, 1280×720 output, 30 FPS, no foreign
assets and the explicit zero buffer/padding. Before any invocation, hash the
authored files and source/config/runtime/browser bytes and resolve every blocker
in [render-education-spatial.md](render-education-spatial.md). Bind the actual
`ScenePlayer` selection, 720p resolution override and storyboard injection in the
invocation receipt. An absent or mismatched composition must refuse execution.
The fixture bytes and runnable invocation do not yet exist; this is the frozen
prospective design, not an executable or accepted trial.

Use concurrency one, one attempt, no application/provider retries, a 120-second
render limit and a 180-second total limit including decode, playback and cleanup.
Keep stdout/stderr at most 1 MiB each and the final output at most 16 MiB. A limit
failure remains a failure. Do not install or download missing components within
the trial, and do not permit undeclared browser/font network access.

Required output observations are:

1. A fresh nonempty regular `output/final-720p.mp4` belongs to this exact request;
   retain its SHA256, size, source and input hashes. A stale existing file fails.
2. ffprobe identifies H.264, 1280×720, 30 frames and duration 1.000 seconds within
   one frame (1/30 second). Record actual video profile/pixel format and audio
   codec; do not infer browser support from the codec name.
3. Decode the entire video and audio streams and retain exit status and errors.
4. **Play these same hashed bytes in the qualified browser/player.** Bind its
   exact version, supported input transport and visible video element to the
   receipt. Require nonzero decoded-frame progress, advancing `currentTime`,
   expected dimensions/duration, no media error and an `ended` event by the
   deadline. A captured frame must show the authored card. Missing playback,
   unsupported codec or a successful decode without playback cannot pass.
5. Missing browser/modules, a changed storyboard path, stale output and mismatched
   request/output identities fail before completion. Their actual check outcomes
   belong in the same retained denominator.

The render remains blocked on the rights-holder grant, exact package/browser/font
grants, Remotion eligibility, compatible runtime and applicable execution authority.
An operator can approve their own execution; they cannot grant another author's
rights. Component-only and mock receipts stay separate. Actual parent `.8.9`
acceptance requires the current-request decoded and played artifact, even if this
preparation plan is accepted.
