# Original-source ingestion

`source_ingest` retains an original before extracting located elements. Supply
one local `file_path` or public HTTPS `url`, `source_format`, `source_id` and
`revision`. An optional `expected_source_sha256` binds the input to known bytes.
Local paths use the existing allowed roots and regular-file policy; URLs use
the existing HTTPS, public-DNS, connected-peer and redirect checks.

```json
{
  "request": {
    "source_id": "meeting-notes",
    "revision": "2026-10-01",
    "source_format": "markdown",
    "file_path": "/absolute/allowed/path/notes.md"
  }
}
```

The response contains a durable `job_id`, exact retained `original`, located
`extraction`, parser implementation commitments and a byte-verified manifest.
`source_ingest_read(job_id)` rechecks those bytes after restart. The existing
`job_status` also exposes its SQLite receipt. `source_ingest_cancel(job_id)`
requests cancellation; the owner acknowledges it after the bounded parser
joins. A cancellation request alone does not establish native termination.
Interrupted or expired work remains unknown and is never automatically rerun.

Identical original hash, source ID, revision and parser settings reuse the same
job, including failed extraction. Changed original bytes, revisions or parser
implementations get a new identity. Missing/corrupt retained bytes fail readback;
they do not authorize an automatic retry. Acquisition failures before a retained
source exists return an actionable tool error.

| Format | Preserved observations | Explicit limits |
| --- | --- | --- |
| PDF | Word text, page number, top-left XY bounds, raw layout and embedded-image descriptors; inferred rectangular cells; optional encoded image streams and source RGB pixels | Separately installed Poppler required; pixels also require installed PDFium. No OCR, semantic table guarantee, masks/compositing or nested image extraction |
| DOCX | XML paragraph positions, table/cell positions, embedded image bytes and relationship descriptors, equation descriptors | Rendered pages and bounds are unknown. External references are retained as data and never fetched |
| Markdown | Literal paragraphs and character intervals; simple pipe-table cells; image/link reference descriptors | General Markdown rendering and referenced image pixels are unavailable |
| HTML | Text/element and table-cell positions; literal reference/alt descriptors | No browser execution, CSS layout, network references or image pixel retrieval |
| Plain text | Literal paragraphs and character intervals | UTF-8 only |
| Audio | Full PCM16 WAV frame read, sample/rate/channel descriptor and source interval | No compressed formats, transcript, speaker identity or semantic speech claim |

PDF cells use aligned word geometry and report content bounds; ruling-line bounds
and semantic accuracy remain unknown. Their shared `pdf-tables.json` artifact
contains a `tables` array. Source-word ordinals are per page, include blank XML
nodes and are distinct from the returned `word-N` segment IDs.
Pixel extraction admits unrotated pages
with an explicit full-page MediaBox and matching measured effective bounds.
Poppler object descriptors and PDFium pixel occurrences have separate identities;
counting both representations does not establish a physical image count.
The descriptor's `pixel_bytes_exported: false` describes that descriptor artifact;
the separate pixel occurrence identifies its RGB artifact. Orientation, clipping,
Decode, color-key masking, masks and compositing remain unknown or unapplied.

The optional PDFium worker checks its selected interpreter, own source and complete
inventory of `pypdfium2`, `pypdfium2_raw`, `pypdfium2_cfg` and distribution metadata
before import and after extraction; `pypdfium2_cli` is excluded. It runs
in a separate isolated Python process within the shared extraction deadline.
The package includes this first-party worker, while the PDFium runtime is installed
separately. These checks do not establish an OS sandbox or a complete host/native
dependency boundary. An absent runtime retains descriptors and reports that pixel
extraction is unavailable.
Trusted worker and package installation roots are canonicalized; selected files
and untrusted input/output paths retain strict symlink refusal. An inherited
`DYLD_*` or `LD_*` name makes the parent abstain from pixel export and retain
descriptors. The isolated worker also refuses those overrides. Native exceptions,
custody drift and native-object exhaustion remain terminal. Native enumeration
has its own 4096-object ceiling; only exported image segments consume the remaining
4096-element output budget. Each parser process receives at most 30 seconds within
the caller's shared deadline. Custody-hashing latency has not been measured.
The worker uses `-B`; any external bytecode addition or mutation changes the
selected inventory, parser identity and job identity rather than silently reusing
an earlier job.

The acquisition ceiling is 50 MiB. Text parsing is bounded to 1 MiB, DOCX has
bounded ZIP expansion, and WAV is limited to 600 seconds. Extraction admits at
most 4096 elements, 8 MiB of derived artifacts and 64 artifact files. Optional
table cells or pixels may abstain before consuming capacity needed by retained
words and descriptors. Empty extraction, malformed
input, unsupported structure, exceeded limits and parser failure are terminal
failures with `indexed: false`. The original and its revision remain separate
from derived elements and notes.

The returned `source` can be supplied in an `EvidencePacket` to `research_execute`
with the returned `source_root`. The `document` modality binds binary-document
observations to the original hash and extraction revision. Text, geometry and
tabular originals retain their stricter original/snapshot equality rule.
Successful byte validation establishes extraction provenance. It does not prove
that a claim is true or supply editorial approval. Speech abstentions stay empty.

Indexing is a separate explicit `knowledge_ingest` operation. Extraction does
not insert into Weaviate, invoke a model, upload to a parsing service or transform
an extracted note into original evidence. Optional Docling/MinerU/content-core
service, OCR/model and speech workflows remain unqualified by this local route.

The LightRAG parser/sidecar requirements were inspected at
`453dce83d6d0354a06e46c8d4029a0895c4e054b`; this implementation is independently
authored and imports no LightRAG framework or parser service. Poppler is an
external GPL runtime: the package neither links nor redistributes its binaries,
dependencies or encoding data. Deployment owners retain their runtime license
and distribution obligations.
