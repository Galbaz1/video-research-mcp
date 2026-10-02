# Local scene assets

The scene tools operate on a local file and a required full
`expected_source_sha256`. They return finite source-bound metadata with every
candidate decision, declared limits and bounded native image delivery. Install
the `images` extra for storyboards/frame similarity and the `audio` extra for
MFCC similarity. FFmpeg and ffprobe remain separately installed prerequisites.

| Tool | Outcome | Boundary |
| --- | --- | --- |
| `video_detect_scenes` | Actual hard-cut PTS and contiguous selected intervals | Visual cuts do not establish semantic scenes |
| `video_storyboard` | Source frames and a PNG with burned actual source timestamps | At most sixteen tiles in a selected window of at most 120 seconds |
| `video_deduplicate_frames` | Every submitted point, representative and dHash distance | Lossy similarity preserves similar and failed candidates |
| `audio_deduplicate` | Every submitted interval, PCM identity and MFCC cosine decision | At most 64 candidates, 30 seconds each and 120 seconds aggregate |
| `audio_clip_export` | Measured whole or one-sided audio selection as PCM WAV | At most 240 seconds, 16 kHz mono signed 16-bit, 8 MiB |
| `video_clip_select` | Whole or one-sided video selection through the existing clip encoder | Existing 60-second, 256-frame, 30-FPS and 8-MiB limits apply |

`media_info` provides the shared local metadata outcome. `video_clip_export`
continues to support its explicit required endpoints and display-coordinate crop.

All tools take a `request` object. For example, after obtaining the exact source
digest, select a storyboard from the original timeline:

```json
{
  "request": {
    "file_path": "/allowed/source.mp4",
    "expected_source_sha256": "replace-with-the-full-recorded-source-sha256",
    "start_seconds": 20,
    "end_seconds": 32,
    "columns": 4,
    "rows": 2
  },
  "include_image": true
}
```

Labels use the actual decoded presentation point relative to the full source
presentation origin. A frame selected at source second 20.4 is labeled 20.4 even
when the selected window begins at 20. Original PTS, time base and container
origin remain separate fields; labels do not invent an evenly spaced time grid.
The label PNG uses the installed Pillow builtin Aileron font. The manifest also
commits every sampled source frame, so changing an unshown tile rejects readback.

Frame comparison uses a 64-bit grayscale horizontal dHash and a declared greedy
Hamming threshold, default 6. Audio comparison uses bounded mono 8-kHz PCM,
256-sample Hamming windows, 128-sample hops, FFT 512, 26 mel bands and thirteen
mean DCT-II coefficients, with default cosine threshold 0.95. Candidate identities
and similarity scores establish different facts. Similarity does not prove equal
text, equal speech, speaker identity or permission to delete evidence. Silence,
invalid intervals, decode failures and other unusable candidates remain visible.

Omitted extraction endpoints select the whole available source within the tool's
limits. A lone start selects through the source end; a lone end selects from
source zero. Requests for empty, reversed, nonfinite or out-of-source windows
fail. Each successful export creates a unique private path and exact manifest;
caller-selected output paths and `overwrite` are rejected. Originals and prior
exports remain unchanged. Actual decoded source/output clocks and the declared
seek tolerance describe timing; no perceptual A/V synchronization is claimed.

Use `image_manifest_read` with the returned manifest path and expected digest
after restart. Its generic readback verifies the original source and every PNG,
MP4 or WAV artifact. A WAV retains text metadata and its path/hash rather than
being mislabeled as a native image.

The seven mapped Qwen scene-asset functions are source-inspected at
`07736672525443c7f8a3f6405eed37d2236f023f`. The local implementation independently
uses those requirements and the existing snapshot/process/timestamp/manifest
controls. No foreign source body, font, model weight, media or native executable
is copied into the core distribution. Optional dependency grants and exact
artifacts are accounted for separately in the reuse ledger and notices.
