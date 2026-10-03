# Education research references: observed sources and remaining checks

Date: 2026-10-03. Bead: `vrm-0e8.8.20`, validating `vrm-0e8.8.7`.
Source baseline: `2ee875a96dcfd0fb6f77e7bfd927c9c5d030167a`.

The public Dutch and English candidates recorded in Beads now have actual caption
exports and bounded browser observations. This supplies reference identities for
prospective research. It does not accept spoken lesson production or replace the
original evaluation inputs. The recorded user scope permits public YouTube
research-reference selection without prior license clearance; it does not establish
a third-party license or authorize bundling these videos in the plugin.

## Source identities

| Reference | Captions observed | Cue starts | Player duration |
|---|---|---|---|
| [WiskundeAcademie: de abc-formule](https://www.youtube.com/watch?v=QcF25PYwIaM) | Dutch, reported auto-generated | 282, from 0 s to 752 s | 760.561 s |
| [Khan Academy: quadratic formula proof](https://www.youtube.com/watch?v=mDmRYfma9C0) | English, reported authored or unspecified | 140, from 0 s to 451 s | 453.5553741496599 s |

The native browser transcript-export API produced UTF-8 files of 12,436 and 7,091
bytes. Their complete SHA-256 identities are:

- Dutch: `ed4ae9f0772fd7026853816fa1aa358c37b316459dee626c2f8abd96bc4e11bd`.
- English: `ee35b5cfab64d83ae3e34e31cd4298da3eeecab2142bb54c7216e88ce1f97c7b`.

Both exports have nondecreasing cue starts within the observed player duration.
They provide second-resolution caption starts, without verified word boundaries,
cue ends or speaker labels. The Dutch export visibly corrupts mathematical terms;
caption text must be checked against the audio and diagram before serving as a
content reference. The English export's label does not verify authorship or accuracy.

Private exports and the receipt are retained under
`~/.local/state/video-research-mcp/capability-programme/2026-09-30/education-source-references-2026-10-03/`.
Full caption text and downloaded media are not shipped with this document.

## Observed media coverage

Both source pages identified the expected title and channel. Their native players
advanced from zero to approximately 13.6 s and 13.4 s, with `readyState=4` and no
reported media error. Both were paused, then sought to 40 s for a second frame
inspection. This does not establish uninterrupted coverage of the intervening
interval or an independently checked listening transcript.

The Dutch frames showed a presenter and Dutch captions. The English screenshots
showed advancing captions over a black video area at both inspected positions;
the cause remains unknown. Its visible mathematical diagrams are therefore
unverified. Neither observation proves playback of this project's generated MP4.

The web fetch route failed for both watch pages. Those failures are retained. The
native browser was the controlled alternative; the failed fetch was not repeated.
No video/audio file acquisition, provider inference, local model load, runtime
installation or third education cohort occurred.

## Use in the residual criterion map

| Requirement | What these sources supply | Remaining evidence |
|---|---|---|
| Actual narration durations and captions | Spoken-language caption candidates and source attribution | Measured spoken WAV segments and independently checked text for the fixed triangle, curve and circuit lesson. Quadratic-equation clips do not narrate that lesson. |
| English and multilingual adaptation | Concrete English/Dutch language references | Exact lesson translations, glyph/layout checks and independent audio/text review. Caption availability does not accept accented glyphs or arbitrary languages. |
| Finished geometry and frame checks | Candidate source pages for teaching structure | Existing source-derived lesson geometry and actual finished-frame checks remain authoritative. Black captured video is not mathematical visual evidence. |
| Delivery codec playback | Native playback started for third-party source players | Full decode and browser playback of the same-hashed generated H.264 yuv420p/AAC-LC derivative, with progress, ended and presented-frame evidence. |
| Twelve mapped templates | No additional accepted template execution | Each mapped template still needs an independently implemented or permitted route, source attribution and finished-layout checks. |

For a prospective bounded source audit, caption cues suggest Dutch 19–52 s and
English 19–56 s as introductory mathematical intervals. These are candidate
intervals; they were not watched continuously or word-aligned. Freeze the exact
source bytes, interval, labels and bounds before executing any new qualification.
Keep the original 17 controls and both prior attempts unchanged.

The existing [supplemental proposal](render-education-spatial.md#education-vrm-0e8820)
still requires measured speech segments, language adaptation and generated-output
playback. Qualified ASR must execute on Mac Studio; human listening findings require
an actual human review. The presence of captions supplies neither qualification.
