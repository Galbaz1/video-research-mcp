# Measured local footage edits

`media_edit_footage` provides two explicit actions: prepare measured scenes, then assemble an exact prepared revision with complete scene approvals. It produces a local linear H.264/AAC MP4 through an independently installed FFmpeg. The companion renderer and its external CLI remain separate.

The first-party adapter was informed by QwenLM/Qwen-MM-Plugins' footage workflow at revision `07736672525443c7f8a3f6405eed37d2236f023f`, under Apache-2.0. The qualified source packet contains 41 complete bodies (258,338 bytes), its complete Apache grant and 65 exact artifact bindings. No Qwen script is imported, copied into the adapter or executed. The upstream workflow's prose locks, partial checksums, advisory loudness failures and black-span exceptions are replaced by typed plans and exact local measurement gates. HyperFrames, GSAP, external fonts, SFX, provider/model assets and foreign creative engines remain unqualified and are not rendered by this route.

## Prepare

Supply a chosen brief, declared FPS and one to eight uniquely named scenes. Each scene binds a regular local source path and its complete expected SHA256; at most two exact sources are admitted. URI paths, symlink components and paths outside `LOCAL_FILE_ACCESS_ROOT` are refused. Source snapshots preserve exact original bytes, and source identities are checked again before artifacts are retained.

Each scene supplies a half-open `start_seconds`/`end_seconds` interval and explicit `timeline_start_seconds`. The ordered timeline starts at zero and has no gaps or overlaps. Source selection uses the existing original-PTS clip helpers: every selected decoded frame retains its original PTS, timebase, actual source time, source revision, decoded RGB hash and final timeline placement. Requested timestamps do not become measured timestamps. Scene clocks must fit the declared uniform frame grid; this route refuses implicit frame resampling. The entire edit is bounded to 256 frames, at most 30 FPS and one megapixel per output frame.

A scene can specify an integer display-pixel `crop_box: [x, y, width, height]`. Existing clip geometry checks the source boundary, bounds the output grid and rounds H.264 dimensions down to even pixels without padding. All scenes must produce compatible dimensions. The neutral grade is `contrast=1`, `gamma=1`, `saturation=1`; the available explicit bounds are contrast 0.94..1.08, gamma 0.94..1.10 and saturation 0.94..1.06. All selected frames receive finite signalstats measurements before treatment and after actual scene encoding. The comparison includes codec and pixel conversion effects and does not establish a color-managed or aesthetically correct look.

Audio is either `preserve` with gain -24..0 dB or explicit `mute`. Required missing audio refuses preparation. Mute is structural `-an` and has no invented loudness measurement. All scenes use the same audio mode; preserved source audio formats must agree. No music, narration, filler, SFX, automatic normalization or silent fallback is added.

`beats.mode` is `none`, `offbeat` or `declared`. A declared grid requires positive finite `bpm` and `origin_seconds`; the ledger records the distance in frames from every hard cut to the nearest declared beat. `declared` refuses a distance above the explicit tolerance (0..3 frames, default 1.5). `offbeat` records the mismatch explicitly. These are caller grid assertions, not measured beat detection or a music-analysis result.

Preparation returns `status: prepared`, exact scene MP4 artifacts, first/middle/last sample PNGs, a contact sheet, a font-free timeline overview and an exact manifest. The PNG RGB pixels are checked against the exact decoded scene-frame hash. Contacts use bounded Pillow thumbnails; their source identities and positions are in metadata. Every complete original lineage record is retained in `scenes[].frames`; each `timeline.frames` row references it by `scene_id` and `scene_frame_index` and retains its timeline placement. This preserves the full population without duplicating its clocks and hashes inside the bounded manifest. The graphical timeline shows sample positions. No final video is reported as delivered at this stage.

## Assemble and read back

Assembly takes only `manifest_path`, `expected_manifest_sha256` and complete `approvals`. Every approval has `scene_id`, `scene_sha256`, `prepared_manifest_sha256` and `locked: true`. The scene SHA commits the full actual MP4; the prepared digest binds the brief, sources, timing, grade/audio/beat decisions and measured scene revision. Missing, duplicate, unlocked, unknown or stale assertions refuse before final native work. Changing the prepared manifest invalidates previous assertions even if a scene file hash happens to remain equal.

These assertions and digests establish integrity of a selected revision. They do not authenticate a caller, establish human visual review, or prove semantic correctness. Preserve the actual scope of any supplied or assistant-produced approval; do not relabel it as human acceptance.

Assembly uses a fresh exclusive UUID view directory. It copies and rehashes approved scene bytes, makes the final, fully decodes and measures it, then rechecks the prepared manifest and original source bytes. A delivered manifest includes separately owned copies of the approved scenes, the final MP4 and actual final-frame previews. Later-scene previews use their full final-frame offsets. Failure or cancellation removes only newly created outputs; previous prepared and delivered views are preserved.

A final receives `status: delivered` only after all gates pass:

- Complete source and artifact SHA256 readback, including the final and owned scene copies.
- `ffmpeg -xerror` full video/audio decoding with a terminal frame-population receipt.
- Actual decoded frame count, PTS clocks, duration, dimensions and H.264 codec against the full timeline ledger. Frame-clock error is at most 10 microseconds; duration error is at most one declared frame.
- Black detection at `d=0.1:pix_th=0.10:pic_th=0.98`; every reported span fails, including head and tail.
- For preserved audio, complete finite terminal ebur128 I/LRA/true-peak fields, integrated loudness -24..-10 LUFS and true peak at most -1.5 dBFS. Missing, malformed, undefined or failed measurements are terminal failures. Results expose one-decimal display precision and do not claim EBU/ITU standards qualification.

Use `image_manifest_read` with the exact final or prepared manifest path and SHA to reverify every committed original and actual artifact after restart. This readback performs no rerender. Native-image and text-only calls share the same metadata and hashes; bounded inline previews are a transport choice.

## Runtime and evidence boundaries

Only the operator's installed `ffmpeg` and `ffprobe` selected by the existing PATH resolver are used. Their resolved regular-file paths, full SHA256 values and sizes are observed and rejoined around every invocation and before retention. There is no automatic installation or request-level executable override. Observing executable bytes is not a whole-package grant, source-build certificate, model readiness claim or operating-system isolation.

The existing native subprocess helper provides a bounded output ceiling, deadline and joined process-group cleanup. One caller deadline covers the complete serialized operation, including waiting for native ownership. Pillow is an optional image dependency; missing Pillow gives an actionable `video-research-mcp[images]` hint. No font is selected, including a system or default font.

The unchanged manifest limits are two sources, 64 artifacts, 8 MiB aggregate artifact bytes and 128 KiB JSON. The final's scene copies and previews count against those limits. Large or detailed edits can be refused below the 256-frame upper bound when byte or manifest limits are reached. No memory/RSS bound, perceptual audio synchrony, visual quality, content truth, human acceptance or provider/model execution is established by a successful technical result.

Primary tests exercise synthetic subprocess responses and real file/hash/manifest/lifecycle logic. No native executable is launched in that lane. The frozen 18-control packaged journey, actual native fixtures, independent review and native runtime qualification are root-owned gates; primary implementation and mocked tests alone do not establish their acceptance.

The accepted local candidate passed the frozen eighteen-control extracted-wheel
journey at attempt 2, including the two-scene 96-frame, four-second
320x240 H.264/AAC edit, strict failure controls, manifest restart and in-flight
cancellation. Root independently decoded twelve exact source/final frames, matched
their full RGB identities and viewed the first/middle/last and hard-cut seam.
The actual public journey made 37 MCP client calls and
1 direct public cancellation call, with zero
provider/socket attempts. All 3299 root tests and required gates passed.
The sole original review found measurement-before-first-file-hash ordering;
original regressions failed, and immediate post-encode commitments plus later
readback rejected in-flight changes. Original primary, controller and review
failures remain retained. This qualifies the chosen local linear workflow;
whole native source-build/grant certification, inferred musical beats, extended
creative engines, perceptual AV sync, human programme audit, comparisons and
registry release remain unverified.
