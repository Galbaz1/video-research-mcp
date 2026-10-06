# Local image edits and source exports

These local operations require the optional `images` extra for
Pillow. From this checkout:

```bash
uv run --extra images video-research-mcp
```

Local video operations also require separately installed FFmpeg/FFprobe. OCR
requires the explicitly selected local backend. Core discovery does not import
Pillow, build Swift, download a model or contact an OCR service.
Verify that the selected installed server exposes the tool names below. Tool
discovery does not establish that its optional OCR or media runtimes are ready.

## Edit and inspect an image or source frame

`image_edit` combines image preparation, crop, resize, annotations, cutout and
PNG/JPEG/WebP/BMP/GIF conversion in one bounded request. It creates fresh private outputs
and preserves the original file. To edit a video frame, supply `time_seconds`;
the result retains requested time, actual decoded time, original PTS/time base
and the full video source digest.

```json
{
  "request": {
    "file_path": "/allowed/source.png",
    "crop": {"space": "pixel", "coordinates": [20, 10, 80, 40]},
    "resize": {"width": 160, "height": 80},
    "output_format": "png"
  },
  "include_image": true
}
```

Pixel crops use integer `x,y,width,height`. `normalized1000` crops use corner
coordinates `x1,y1,x2,y2` in the range 0–1000. Regions and annotations refer to
the oriented source display grid before cropping and resizing. Input EXIF
orientation is normalized; results retain stored and oriented dimensions and
forward/inverse homogeneous transforms in pixel-corner coordinates. These
matrices map measured geometry; they do not verify a model's proposed region.

Annotations support `box`, `circle`, `arrow`, `number` and `text`, with pixel or
normalized coordinates. Small boxes/circles produce padded close-up artifacts.
Text uses Pillow's installed Aileron font. Unsupported glyphs produce an explicit
warning, so replacement glyphs do not establish literal text correctness.
Annotations explicitly remain annotations rather than extracted visual facts.

Cutout uses supplied polygon rings, including holes, or a supplied background
seed and finite RGB tolerance. Seeded flood operates only on opaque prepared
pixels. Coverage, border and component warnings retain ambiguity; difficult
backgrounds require explicit geometry or a different authorized method. Flood
uses four-connected RGB distance from the seed; it retains all foreground
components and applies no morphology, component removal or feathering. The
actual alpha-mask artifact has its own digest and crop offset. Polygon summaries
are not a claim of exact mask replay or semantic segmentation.

Original format, mode and transparency are reported. Optional `include_exif`
returns bounded source tags and an explicit GPS privacy notice; it is disabled
by default. `quality` controls JPEG/WebP encoding. GIF palette/transparency
quantization and BMP background flattening are recorded. BMP/GIF exports retain
verified paths and text metadata with an explicit native-MIME limitation.

Still sources are limited to sixteen MiB. Images are bounded before pixel decoding
and before output allocation. Only the
first frame/page of animated or multipage image inputs is prepared. Outputs are
at most one megapixel per image and eight MiB in aggregate. Color-profile,
metadata and transparency handling remain explicit in the operation result;
JPEG conversion reports its background flattening and lossy encoding.

`include_image` emits actual image bytes up to one MiB per native block. Larger
images retain the same source, artifact and manifest identities in text, with
an explicit transport limitation. The server performs no model inference or
provider upload for these operations.

## Local OCR and geometry

`image_ocr` requires an explicit `engine`: `tesseract` or `vision`. It prepares
one source image/frame through the same crop, orientation and resize pipeline.
Tesseract uses one bounded TSV invocation and returns observed word/line boxes.
An unavailable executable returns a dependency error. `locate` performs bounded
lexical matching over recognized text; it does not establish that the text is
correct.

Apple Vision is an optional macOS backend compiled from the project's own Swift
source using the installed toolchain and system framework. It can observe text,
barcodes and document quadrilaterals. Backend normalized bottom-left coordinates
are retained with converted top-left prepared, oriented source and stored source
geometry. Native OCR/document observations do not establish semantic table
structure. The raw backend payload and its exact digest remain in the export
manifest. Backend confidence is an uncalibrated engine score, with no claim of
factual accuracy. No foreign OCR binary, framework or model is bundled.

## Export a finite source clip

`video_clip_export` accepts a required finite half-open interval, optional crop,
output resolution and explicit audio selection. Limits are 60 requested seconds,
256 selected source frames, a declared rate no greater than 30 FPS, one megapixel
per output frame and eight MiB per export. Unknown rates are measured under the
same bounded operation; exceeding a limit returns an error.

Original selected frame PTS and actual encoded clip timestamps/count/duration
are measured separately. An early encoder stop or frame-count mismatch fails
verification. Requested bounds do not become observed frame times. Audio and
video retain their source-relative timing instead of independently zeroing each
stream. Timing observations and unknown last-frame holds remain explicit;
successful encoding does not establish perceptual synchronization or factual
support.

Encoded clip export is a programme requirement. Qwen's `save_view` supplies
image exports; it is not an upstream encoded-clip implementation.

## Verify a retained export after restart

Every new edit, clip and OCR result returns a manifest path and full SHA-256.
Preserve that digest separately and call:

```json
{
  "manifest_path": "/allowed/cache/media/views/owned-slot/manifest.json",
  "expected_sha256": "the-64-character-digest-returned-by-the-export",
  "include_image": false
}
```

`image_manifest_read` verifies the expected manifest bytes, its payload digest,
the original source and every declared artifact. Changed, deleted, nonregular
or substituted files fail readback. This verifies byte lineage and operation
records; media correctness and human review are separate acceptance gates.
Manifests are bounded to 128 KiB. Artifact byte limits apply to raw OCR and mask
files as well as the primary image/clip.

## Source and reuse route

The implementation independently adopts the mapped requirements from:

- Qwen-MM-Plugins at `07736672525443c7f8a3f6405eed37d2236f023f`: both crop
  coordinate routes, five annotation types, close-ups, supplied polygon/flood
  cutout and local OCR localization.
- omni-image-tools-mcp at `4d191573b7e459519c3ec9414ade744456115a5a`: bounded
  preparation, crop, conversion and native geometry integration.
- vision-ocr-mcp at `4c9225ca81d1c237901d7c58a6b32f7895968415`: source-observed
  native OCR/region/barcode/document requirements. Its absent advertised
  `analyze_document_structure` tool is excluded.

No foreign helper body, font, media asset or executable is copied. Exact source,
implementation and dependency receipts remain in the reuse ledger. The legacy
`image_crop` contract remains available for its published PNG-only callers.

[Local scene assets](SCENE_ASSETS.md) uses the same manifest readback for
timestamped storyboards, whole/one-sided clips and standalone WAV exports.
