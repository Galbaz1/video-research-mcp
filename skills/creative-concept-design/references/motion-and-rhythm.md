# Motion and beat rhythm

Use this for animated explanation and transitions after choosing the treatment.
Define each beat by the viewer's new understanding, then choose its motion.

## Choreograph a reason

- Assign a purposeful verb: reveal the hidden part, trace a connection, compare
  two states, assemble a system, highlight a cause, or hold a consequential result.
  Motion that merely decorates a claim can compete with comprehension.
- Stage entry, readable hold and resolution. Fit these to the actual narration
  and complexity instead of applying the same timing percentage to every scene.
- Change rhythm where the argument changes: a brisk question, slower mechanism,
  held consequence and concise takeaway. Silence and stillness can provide emphasis.
- Keep object correspondence across a comparison. Position, color and labels
  should make clear whether it is the same item, a new example or a changed state.
- Motivate transitions: a matching move can preserve continuity, a cut can mark
  a new question, a dissolve can signal passage or continuation. Write the
  narrative reason and duration; do not assign an effect solely for novelty.
- Protect quantitative meaning. Eased counters, interpolated geometry and varying
  particle speeds are illustrative unless their values/timing come from evidence.
  Avoid implying a physical process by decorative acceleration or a seamless morph.

Watch the representative animatic with sound and through its transition. Check
where attention lands, how long reading takes and whether the motion expresses
the narrated relation. Then inspect final playback; the animatic is a direction
test, not proof of all final frames.

## When the existing renderer is Remotion

Inspect that project's package.json and lockfile for the installed Remotion/API
version. Use its existing entrypoint, composition structure and scripts; do not
upgrade, scaffold a second renderer or import new APIs just because upstream
examples use them. Read version-compatible official documentation for any API
that is not already present in the project.

Derive rendered state from `useCurrentFrame()` and `useVideoConfig().fps`, using
supported `interpolate`, easing or spring functions. Convert beat seconds to
integer frame boundaries and account for local frame zero inside a sequence.
Clamp interpolation where a held start/end is intended. Use deterministic seeds
for randomized decoration. Avoid wall-clock timers, `Math.random()`, CSS keyframe
animations/transitions and mutable playback state as animation clocks.

Use the project's supported asset-loading mechanism and verified fonts. Check
the same representative frame after seeking from different positions; it should
resolve to the same authored state. Inspect motion playback separately. Account
for overlap durations when scheduling transitions and derive timing from accepted
media rather than script duration estimates.

## Attribution and adaptation

Creative direction is an original synthesis informed by HyperFrames Creative
[beat direction](https://github.com/heygen-com/hyperframes/blob/0c3e244269aae698149214379280377a9f7a2f2b/skills/hyperframes-creative/references/beat-direction.md)
and [motion principles](https://github.com/heygen-com/hyperframes/blob/0c3e244269aae698149214379280377a9f7a2f2b/skills/hyperframes-creative/references/motion-principles.md)
(repository [Apache-2.0](https://github.com/heygen-com/hyperframes/blob/0c3e244269aae698149214379280377a9f7a2f2b/LICENSE)).
Technical facts use the official Remotion [skill entrypoint](https://github.com/remotion-dev/skills/blob/32b241b97f4e0e4ab61fe9a41b05e6e64503f8c5/skills/remotion-best-practices/SKILL.md),
[animation documentation](https://www.remotion.dev/docs/animating-properties) and
[seeded randomness documentation](https://www.remotion.dev/docs/random), checked
2026-10-07. The pinned Remotion skills tree has no repository license file;
no upstream text or code is copied here, and no redistribution license is inferred.
This plugin does not bundle or install HyperFrames or Remotion.
