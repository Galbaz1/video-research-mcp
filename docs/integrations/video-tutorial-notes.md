# Source-linked tutorial notes

`video_note_create` creates a local illustrated PDF from one exact video and 1–16 explicit source-absolute step proposals. It defaults to a read-only dry run. It adds no model call or second planner unless the caller supplies an explicit existing AV-perception submission grant.

```json
{
  "file_path": "/owned/tutorial.mp4",
  "expected_source_sha256": "FULL_LOWERCASE_SHA256",
  "title": "Tutorial title",
  "output_path": "/owned/tutorial.pdf",
  "steps": [{"title": "First step", "instruction": "Describe the demonstrated step.",
             "start_seconds": 0.4, "end_seconds": 0.6}],
  "dry_run": true,
  "overwrite": false
}
```

Replace the digest with the actual SHA-256. Intervals must be finite, positive, ordered without overlap and no later than 86400 seconds. Text supports the core Helvetica WinAnsi character set, with at most 160 characters per title and 2048 per instruction. Unsupported glyphs are refused rather than silently replaced. The renderer uses plaintext APIs, so source/model markup is not interpreted as HTML or links.

Input and output must be local regular paths within `LOCAL_FILE_ACCESS_ROOT` when configured. URLs, symlinks, input/output aliases, unsupported video extensions and existing output without explicit overwrite are rejected. The output parent must already exist. Dry run hashes the original and validates paths, the supplied plan and any optional perception source binding. It performs no probe, native extraction, rendering, provider submission, cache creation or directory creation. Source duration/clock remains unverified during dry run.

The shared runtime configuration can load the selected dotenv during cold bootstrap. Dry-run filesystem/network/native/provider nonmutation is qualified after isolated runtime configuration has initialized; cold-bootstrap environment nonmutation is not claimed. The tool does not select or modify a home environment.

## Actual generation and optional inference

Set `dry_run: false` for generation. Install the optional `video-research-mcp[tutorial]` extra for fpdf2 major 2 and pypdfium2 major 5. The PNG route uses the existing Pillow dependency; FFmpeg/FFprobe must already be available for the admitted source-frame extractor. Imports are lazy, and missing/incompatible PDF dependencies return an actionable error. The writer uses core Helvetica metrics and bundles no font assets, HTML renderer or raster-only PDF fallback.

PDFium can consult installed operating-system fonts during raster verification.
Those fonts are local viewer dependencies and are not copied or bundled with the
plugin. The controlled macOS qualification binds its current system-font files
before and after decoding; its four positive PDF pages match the previously
inspected pixels. Reproducing that qualification on another host requires that
host's selected native library and font population.

A single configured `MEDIA_ACQUIRE_TIMEOUT_SECONDS` deadline covers source hashing, optional inference, all frame extractions, rendering, verification and promotion. Native PDF work runs in a joined cooperative worker; it checks cancellation/deadline between bounded operations. A library call's process RSS or interruption latency is not certified. Caller cancellation joins that worker before removing owned staging, and publication cannot continue after cancellation.

An optional `perception` object uses the existing `AVPerceptionRequest` contract. Its local file and expected SHA must match the tutorial source exactly. Actual submission requires `dry_run: false` and `authorize_submission: true` inside that request as well as the tutorial generation request. Configured readiness provides no provider authority. Perception's ordered, source-absolute positive events may become labeled inferred steps only when the complete timeline fits the 16-step contract. Supplied steps remain intact in lineage and are retained as the working plan when inference fails, abstains, overlaps or otherwise cannot be admitted. Window outcomes, failed/unobserved counts, abstentions, attempts and the retained timeline remain separate from factual review. Raw provider/native diagnostics are withheld; safe warnings describe omissions.

For each working step the tool requests the midpoint through existing `frame_at(..., selection="precise", expected_source_sha256=...)`. The actual decoded point must lie inside that step's half-open interval. The retained PNG copy matches the exact immutable bytes passed to the renderer, full SHA, dimensions and observed original PTS/time base. A requested midpoint is never fabricated as an observed frame time. These are temporal illustrations; semantic relevance and instruction correctness remain unreviewed.

Missing images preserve readable tutorial text with explicit warnings. Any observed source extent from extraction or admitted perception rejects intervals beyond it. If no duration/clock can be observed, text fallback retains the supplied intervals with an explicit unverified warning. Sampled points never become continuous watched intervals.

## Durable artifact and commit contract

Generation creates a unique private sibling artifact directory under the already checked output parent. It contains:

- Exact source PNG copies, a canonical `manifest.json` binding original source SHA/path, supplied and working plans, frame identities/PTS, inference populations, warnings and review boundaries.
- The final PDF's rasterized PNG pages and `layout.json`, which records each illustration's actual 1-based page and top-left position/size in millimetres on A4.
- A separate `receipt.json` binding the PDF SHA, manifest SHA, all retained PNG/page/layout identities and performed verification. No file claims its own hash.

The PDF visibly prints the original SHA, manifest SHA, step intervals, step-origin labels and actual frame PTS/PNG SHA captions. The plaintext fpdf2 renderer uses A4, core Helvetica, 11-point instruction text, 8-point provenance captions and 15-point step titles. Images are supplied from owned PNG buffers, never model/caller URLs or alternate paths.

PDFium is serialized under one lock covering import/init and the entire document/handle lifetime because the library is not thread safe. Every page is structurally opened, its text decoded, and its raster rendered at 72 DPI then copied to a verified complete PNG. Required title, instructions, source/manifest hashes and frame captions must survive text decode. Every native object closes before the lock releases. Deterministic rasterization does not certify visible layout or factual correctness; the retained pages support separate human inspection.

Bounds are 16 source frames/8 MiB, 40 PDF pages, 8 MiB PDF, 1 million pixels per raster, 24 million aggregate raster pixels, 32 MiB page PNGs, 64 retained files and 48 MiB aggregate artifact bytes. Metadata is capped at 256 KiB. These are explicit file/pixel/layout limits, not a process-memory certificate.

After generation, all retained artifacts and embedded frame buffers are rehashed. The original source is rehashed with its original file identity; the output parent and exact initial destination revision are rechecked. Only then does atomic replacement move the completed staged PDF to the exact output. The PDF is the final commit point. Any earlier failure or cancellation removes only owned staging and preserves an existing PDF; a concurrent destination change causes refusal. Successful artifact directories are retained for restart readback and inspection.

Success returns `status: "complete"`, exact PDF/manifest/receipt bindings, `artifact_directory`, page/frame counts, warnings and performed checks. A dry run returns `status: "dry_run"` with rendering checks unperformed. Both preserve `factual_correctness_verified: false`, `human_review: "pending"` and `final_model_review: "unperformed"`. No final model review, task execution, publication or rights audit is implied.

The verified local dependency profile uses fpdf2 2.8.9, the generic Python
FontTools 4.66.1 wheel, DefusedXML 0.7.1 and the macOS 13+ arm64 PDFium
5.13.0 wheel. Other native/platform wheels have separate qualification needs.
The writer remains a replaceable external dependency. See the prominent
[third-party notice](../../THIRD_PARTY_NOTICES.md), including the full
[LGPL text](../../licenses/fpdf2/LGPL-3.0.txt) and
[GPL text](../../licenses/fpdf2/GPL-3.0.txt). ReportLab was not installed: its
selected wheel includes font assets whose permissions remain unresolved.

Each successful native extraction is copied into the tutorial directory and its
owned temporary PNG/view is then removed, including on validation fallback.
Final artifact rereads check the overall deadline, followed by a last check
immediately before publication. A previously absent destination is created with
an atomic no-overwrite link; concurrent creation causes refusal. An existing
destination requires explicit overwrite and its identity is checked immediately
before replacement. This check does not lock out external writers.
