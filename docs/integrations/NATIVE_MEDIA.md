# Inspectable local media

The root MCP server exposes deterministic local metadata, still images, measured
video frames and bounded windows. It uses independently installed FFmpeg and
FFprobe. These tools perform no model inference, provider upload or source
download. An MCP host can send returned image blocks to its own model.

## Public entry points

| Tool | Result |
| --- | --- |
| `media_info(file_path)` | Exact source SHA-256/bytes, duration, container clock, stored/display dimensions, rotation, stream and chapter metadata |
| `image_read(file_path, max_pixels, include_image)` | First local PNG/JPEG/WebP/BMP/GIF/TIFF still as a bounded PNG; animation and multipage traversal explicitly absent |
| `video_frame(file_path, time_seconds, selection, crop_box)` | Requested time, actual decoded time, original integer PTS/time base, delta, exact PNG digest and crop |
| `video_frames(file_path, start_seconds, end_seconds, mode, fps, max_frames, crop_box)` | Actual sampled points, individual stills or a timestamped grid/filmstrip, enforced budgets and sampling completion |
| `video_frame_by_query(file_path, query, transcript)` | Lexical selection from supplied timestamped text, requiring the exact source digest; unverified transcript status remains explicit |

Times use the presentation clock relative to the measured container start.
The original PTS and its rational time base remain available. A precise point
returns the first decoded frame at or after the request. Its actual time can
differ from the request, particularly with variable frame rate. It fails when no
following frame exists. An approximate keyframe result reports the closest of
the first two decoded keyframes following the index seek, its candidate times and
its delta. It does not claim a globally nearest keyframe.

Windows are half-open: `start_seconds <= actual_seconds < end_seconds`. Uniform
selection keeps the first eligible frame, then uses actual PTS with a minimum
spacing of `1/fps`. It does not generate output timestamps with an FPS filter.
`frames` returns individual images; `sheet` returns a grid; `filmstrip` returns a
vertical strip. `scenes` selects actual scene changes at a fixed FFmpeg threshold
of 0.3, including the first eligible frame. `keyframes` selects decoded keyframes.
Scene/keyframe selection also obeys the requested maximum rate and other limits.

For a short UI change, select a narrow window, higher FPS and a crop around the
affected control. For example:

```json
{
  "file_path": "/allowed/recording.mp4",
  "start_seconds": 12.0,
  "end_seconds": 12.8,
  "mode": "filmstrip",
  "fps": 15,
  "max_frames": 12,
  "max_pixels": 50000,
  "crop_box": [320, 160, 240, 80]
}
```

Crop coordinates are integer `x,y,width,height` in the rotated source pixel grid;
crop precedes scale. Each sheet tile retains the selected frame's actual time,
original PTS/time base and exact frame digest. The library performs no similarity
deduplication, so changed text cannot be discarded as a near duplicate. It
performs no OCR; images are available for inspection and later separately owned
OCR/vision workflows.

Still-image EXIF orientation and embedded color profiles are not normalized or
verified. Generated PNGs omit source metadata, chapters and frame side data.
Use the original file when verified color/orientation fidelity is required.
Explicit non-square or invalid video sample aspect ratios return an error before
rendering; normalize them to a verified square-pixel source before using crops.
Absent SAR metadata uses the rotated stored-pixel-grid convention and explicitly
reports `pixel_aspect_verified=false` and its geometry basis. That convention
does not verify the physical display aspect ratio. An explicit valid 1:1 SAR
reports observed square pixels. Source-pixel crop coordinates follow this policy.

## Evidence, limits and ownership

`source.sha256` commits to the original bytes. A private stable snapshot is
decoded, and both the original and snapshot are verified before exposing output.
Symlinks, named pipes, URI inputs and paths outside `LOCAL_FILE_ACCESS_ROOT` are
rejected. Input paths are at most 4096 characters. Set `GEMINI_CACHE_DIR` within
the fence: owned outputs live under
`media/views/<invocation UUID>`. Timeout and cancellation join cooperative IO
workers and terminate/reap the owned native process group. Failed operations
remove only their own staging. Originals remain intact.

The configured input byte ceiling defaults to 512 MiB; the configured operation
timeout defaults to 120 seconds. A public combined sample/sheet operation shares
one timeout. Native-process cleanup can require its bounded termination grace.
Decoded visual input is capped at eight million pixels; output frames at one
million pixels each; aggregate output pixels at sixteen million, including sheet
padding. At most 48 frames and 30 selected frames per second are accepted.
Generated artifacts share an eight MiB byte ceiling. A conservative PNG byte
reservation can reduce the effective frame limit before rendering; the result
reports that limit and stop reason. `-max_alloc` caps a single allocation at
64 MiB; it does not establish a process RSS limit. Native stdout/stderr are each
bounded at one MiB. All native input protocols are file-only.

`coverage.sampled_points` lists returned source times. `decoded_count` counts
returned decoded artifacts, rather than every frame visited by the decoder.
`complete` says requested sampling finished. A cap stop remains `partial` with an
explicit reason. `watched_intervals` is always empty: extraction does not prove
continuous observation, transcription, factual accuracy or full-stream validity.
Metadata without an available clock remains unknown and cannot support timed
extraction.

Native transport rechecks every returned artifact's bytes and digest, including
text-only and inline-fallback paths. It emits at most
one MiB per image and eight MiB of total binary image data; base64 encoding adds
transport overhead. Larger images retain their paths, hashes and an explicit
fallback status. Set `include_image=false` for a text-only client. Both paths
retain the same source, artifact and temporal identities, with a native transport
status. A text-only client needs a local artifact viewer to inspect pixels.

Transcript-query selection accepts at most 256 supplied segments, 4096 characters
per segment and 64 KiB of aggregate UTF-8 text. It matches case-folded word tokens,
breaks ties at the earliest segment and abstains on zero overlap. A source SHA
mismatch fails before decode. The selected transcript remains
`caller_supplied_unverified`; lexical overlap is not semantic confidence or
verified spoken evidence. Session chat history is not used as a transcript.

## Pinned capability mapping and reuse

The three Qwen core tools map directly: `core.read_image` to `image_read`,
`core.media_info` to `media_info`, and `core.read_video` to `video_frames`.
The `direct.frames` aliases and workflows share these concrete operations:

| Audited source surface | Implemented behavior |
| --- | --- |
| guimatheus `get_frame_at`, mcptube `get_frame`/`get_frame_data`, ludylops `get_youtube_video_frame`, watch `get_moment` | `video_frame` after `media_acquire` when the source is remote; native PNG and text artifact identity |
| guimatheus `get_frame_burst`/`get_frames` | `video_frames` with explicit window/rate/caps |
| guimatheus `analyze_moment`/`analyze_video` | Bounded point/window artifacts for host inspection plus existing instruction-driven `video_analyze` when provider analysis is separately authorized |
| Video Context `peek_frame`/`crop_region` | Approximate `video_frame(selection="keyframe")`, measured delta and source-pixel crop; exact extraction remains separately available |
| Video Context `get_video_timeline`, vidlens `extractKeyframes` | `video_frames(mode="keyframes")` with actual points and frame digests |
| mcptube `get_frame_by_query` | `video_frame_by_query` from explicitly supplied source-bound transcript segments |
| Media Context `analyze_media`, sheet/frames/scenes/filmstrip workflow | `image_read`, `media_info` and the corresponding `video_frames` modes, with window/crop/FPS |

The bounded indexed-frame crop workflow uses the keyframe selection and crop in
one operation. The transcript-query workflow abstains when text is absent or
unmatched. Remote source acquisition retains its separate source/rights boundary.
OCR, embeddings, speech verification and other analysis stages have separate
programme owners; these native tools do not advertise those results.

The source inventory pins Qwen at `07736672525443c7f8a3f6405eed37d2236f023f`
and guimatheus at `9e476c02f8426f5c277ed5e7f5729c1aee75b31a`, with the supporting
sources retained in the pinned transfer inventory. This implementation is
independently authored and copies no upstream source body, assets, fonts, media,
weights or native executable. FFmpeg remains an external optional prerequisite.
Source code grants do not establish rights to source media.

Fixed original development fixtures cover CFR, VFR with B frames, a nonzero source
clock offset, rotation/audio and brief changed bitmap text. Fixture failures and
candidate results remain in private programme evidence with exact source/artifact
digests. These controls establish local extraction and transport behavior. They
do not establish provider accuracy, held-out superiority, a human audit result or
a distribution release.

[Local scene assets](SCENE_ASSETS.md) adds contiguous hard-cut intervals,
timestamped storyboard pixels, full frame/audio similarity denominators and
whole/one-sided extraction using these same source and artifact controls.
