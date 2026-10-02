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
| PDF | Word text, page number, top-left XY bounds and measured page dimensions; embedded-image page/object/dimension descriptors; raw parser layout | Separately installed `pdftotext` and `pdfimages` required. No OCR, table-cell reconstruction or image pixel export |
| DOCX | XML paragraph positions, table/cell positions, embedded image bytes and relationship descriptors, equation descriptors | Rendered pages and bounds are unknown. External references are retained as data and never fetched |
| Markdown | Literal paragraphs and character intervals; simple pipe-table cells; image/link reference descriptors | General Markdown rendering and referenced image pixels are unavailable |
| HTML | Text/element and table-cell positions; literal reference/alt descriptors | No browser execution, CSS layout, network references or image pixel retrieval |
| Plain text | Literal paragraphs and character intervals | UTF-8 only |
| Audio | Full PCM16 WAV frame read, sample/rate/channel descriptor and source interval | No compressed formats, transcript, speaker identity or semantic speech claim |

The acquisition ceiling is 50 MiB. Text parsing is bounded to 1 MiB, DOCX has
bounded ZIP expansion, and WAV is limited to 600 seconds. Extraction admits at
most 4096 elements and 8 MiB of derived artifacts. Empty extraction, malformed
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
