# Art direction for video

Use this when a chosen concept needs a designed frame rather than incidental
footage. Read the project's actual brand/asset specification first; retain its
palette, fonts and content constraints while adapting their scale to the video.

## Stage attention

- Give each beat one dominant focal subject and a clear secondary place for the
  viewer's eye to travel. A scene may be sparse when that helps the message.
- Arrange background, explanatory subject and labels as distinct visual roles.
  Add a layer only if it supports meaning, contrast, continuity or depth.
- Establish the subject before moving its evidence or adding a competing label.
  Reveal order communicates importance; do not animate everything at once.
- Use framing and empty space intentionally: a split frame can compare two
  states; a close detail can explain a mechanism; a held wide shot can establish
  relations. Keep essential text away from crop edges and caption overlays.
- Keep atmosphere quieter than the claim. Color, contrast and movement should
  point to the same focal subject. Effects must not obscure counts or geometry.

## Design for the actual viewing size

For 1080p, a useful first pass is 64–120px headlines, 32–48px body/captions and
28px or larger important data labels. These are starting values, not acceptance
thresholds: scale for the delivery format and inspect at the audience's expected
player size. A feed embed needs larger type than full-screen viewing.

Use fewer words and a readable hold instead of shrinking text. Contrast font
roles or weights deliberately; one expressive display face plus a restrained
reading face is often enough. Verify actual font files/weights in the selected
renderer; do not borrow HyperFrames' bundled-font assumptions. Keep stable digit
widths for changing numerical labels when the chosen font supports them.

Inspect representative rendered frames at target player size and after the chosen
encode. Check wrapping, contrast, safe area, glyphs and whether labels survive
motion and compression. A screenshot covers layout only; moving text still needs
playback. Report skipped mobile/feed inspection rather than claiming readability.

## Attribution and adaptation

This is newly written project guidance curated from HeyGen's HyperFrames Creative
[video composition](https://github.com/heygen-com/hyperframes/blob/0c3e244269aae698149214379280377a9f7a2f2b/skills/hyperframes-creative/references/video-composition.md)
and [typography](https://github.com/heygen-com/hyperframes/blob/0c3e244269aae698149214379280377a9f7a2f2b/skills/hyperframes-creative/references/typography.md),
checked 2026-10-07. The repository's [Apache-2.0 license](https://github.com/heygen-com/hyperframes/blob/0c3e244269aae698149214379280377a9f7a2f2b/LICENSE)
was checked. No upstream instruction text, code, assets or runtime is bundled.
Fixed decoration counts, font bans and universal ambient-motion rules are omitted;
the chosen audience and concept determine density and movement.
