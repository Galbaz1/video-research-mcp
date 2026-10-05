# Original-source ingestion

For document questions, prefer Newton's existing original-PDF path: retain the
original bytes, bind the source hash and refer to the exact page. Use structured
extraction when you need reusable located text, cells or image artifacts. It is
an optional, narrower workflow; no comparative quality advantage over Newton
has been established, and Docling is not a required dependency.

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
| PDF | Word text, page number, top-left XY bounds, raw layout and image descriptors; inferred cells; optional measured page geometry/rotation, complete-grid regions, encoded streams and source RGB pixels | Separately installed Poppler required; optional native observations require installed PDFium. Narrow grid and original-image binding support; no OCR, semantic table guarantee, masks/compositing or nested image extraction |
| DOCX | XML paragraph positions, table/cell positions, embedded image bytes and relationship descriptors, equation descriptors | Rendered pages and bounds are unknown. External references are retained as data and never fetched |
| Markdown | Literal paragraphs and character intervals; simple pipe-table cells; image/link reference descriptors | General Markdown rendering and referenced image pixels are unavailable |
| HTML | Text/element and table-cell positions; literal reference/alt descriptors | No browser execution, CSS layout, network references or image pixel retrieval |
| Plain text | Literal paragraphs and character intervals | UTF-8 only |
| Audio | Full PCM16 WAV frame read, sample/rate/channel descriptor and source interval | No compressed formats, transcript, speaker identity or semantic speech claim |

PDF cells use aligned word geometry and disclose rectangular inference; semantic
accuracy remains unknown. Their shared `pdf-tables.json` artifact contains a
`tables` array. Cell bounds locate their text. A table's `content_bbox` retains
text content bounds; `bbox_role` distinguishes those from an optional measured
ruling centerline region. That region requires a complete, unambiguous,
axis-aligned native grid with every border and separator and matching indexed
cells (at least three rows and two to eight columns). It does not measure painted
border extent or establish stroke visibility. Incomplete/ambiguous grids,
rejected same-page paths/forms or multiple tables on a page abstain from the
measured region. Source-word ordinals are per page, include blank XML nodes and
are distinct from returned `word-N` segment IDs.

With the optional PDFium runtime, `pdfium-result.json` records measured dimensions
and clockwise rotation for every page, including pages without images, bound to
the original hash and measurement method. These are manifest-committed artifact
fields. Pixel export and ruling measurement admit only unrotated pages with an
explicit full-page MediaBox and matching effective bounds. A Poppler/PDFium page
count or dimension disagreement reports a limitation and skips only the optional
measured table refinement, preserving existing text, cells, pixels and table
bytes. Invalid source bindings and native worker failures remain errors.

Poppler image object numbers/generations and PDFium page/object ordinals have
separate identities; counting both representations does not establish a physical
image count. The descriptor's `pixel_bytes_exported: false` describes that
descriptor artifact; the pixel occurrence separately identifies its RGB artifact.
When correspondence is unique and verified, `pdf-original-image-bindings.json`
adds the original stream byte offset/length, object number/generation and source
DeviceRGB identity. Support is limited to a canonical classic xref with a live
root and exact object framing, direct `/Length`, and a flat RGB8/Flate image.
Source stream bytes and independently decoded RGB have distinct hash commitments.
The Poppler-to-PDFium occurrence correspondence is disclosed as inference.
Unsupported or ambiguous cases retain validated pixels/descriptors with unresolved
binding limitations. Raw pixel orientation, clipping, Decode, color-key masking,
masks and compositing remain unknown or unapplied.

One changed trial on the fixed original PDF met C1–C5 (original/page text,
geometry/rotation, measured grid and cells, source-byte/RGB binding, and disclosed
limitations) through manifest-committed artifacts. This is qualification for that
one original only. The historical 18-case cohort and two prior attempts, including
the earlier PDF partial result and URL failure, remain unchanged. It establishes
neither universal PDF acceptance nor a quality benchmark.

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

Indexing is a separate explicit `knowledge_ingest` operation. The default
`parser: "builtin"` preserves the local extraction route above. It does not
insert into Weaviate, invoke a model, upload to a parsing service or transform
an extracted note into original evidence. MinerU/content-core, OCR/model and
speech workflows remain unqualified by this route.

The LightRAG parser/sidecar requirements were inspected at
`453dce83d6d0354a06e46c8d4029a0895c4e054b`; this implementation is independently
authored and imports no LightRAG framework or parser service. Poppler is an
external GPL runtime: the package neither links nor redistributes its binaries,
dependencies or encoding data. Deployment owners retain their runtime license
and distribution obligations.

## Explicit optional Docling HTTP entry

Docling is an optional, separately qualified service for structured extraction.
It is not needed for the original-PDF/hash/exact-page workflow or the builtin
extraction route, and no comparative quality superiority is established.
For PDF, DOCX, Markdown or HTML, a request may select `parser: "docling"` and
`authorize_submission: true`. Both configured operator qualification and request
authorization are required before source retention. This entry does not install
or import Docling, launch a service or admit its runtime. The operator must qualify
the selected deployment separately; `runtime_qualified: true` records that
operator assertion and does not independently attest the deployment.

Configure `DOCLING_SERVICE_JSON` with a literal loopback origin, an operator
deployment revision and the SHA-256 of the **actual bytes** returned by that
deployment's `/v1/capabilities` route:

```json
{
  "base_url": "http://127.0.0.1:7777",
  "contract_route": "/v1/capabilities",
  "expected_contract_sha256": "<64 lowercase hexadecimal digits from qualified contract bytes>",
  "deployment_revision": "<operator-selected immutable deployment identity>",
  "runtime_qualified": true
}
```

The route must be enabled with version information. Before uploading any body,
the adapter reads and retains its capabilities bytes, checks the configured hash
and requires Docling Serve **1.36.0**, Docling **2.129.0**, core **2.96.0**, inbody
JSON, embedded images and no API key. Version reporting and routes follow
the primary [Serve capabilities implementation](https://github.com/docling-project/docling-serve/blob/07b1d3d3b515afd9196148e0353d54ea38de2a37/docling_serve/capabilities.py)
and [Serve application](https://github.com/docling-project/docling-serve/blob/07b1d3d3b515afd9196148e0353d54ea38de2a37/docling_serve/app.py).
The retained response must contain `DoclingDocument` schema **1.10.0**.
Core 2.96 is the minimum required by Docling Slim 2.129. Its
[schema constant](https://github.com/docling-project/docling-core/blob/0b55aca55b22f7109502d44db36f8246e238121c/docling_core/types/doc/common/constants.py)
remains 1.10.0. The pinned split models preserve the text/formula, table-cell,
provenance, page, reference and image fields consumed here; the exact version,
schema and boundary checks remain required. This source compatibility check
does not qualify a deployment or attest extraction fidelity.

Capabilities must admit `file` sources and explicitly include `max_file_size`
and `max_num_pages` as null or positive integers. Missing or malformed relevant
limits refuse submission. A finite file-size limit is checked against the exact
retained byte count before multipart construction. Source page count is unknown
before upload; no additional PDF parser or probe runs. The receipt states that
limit, and only the returned page population can be checked against it locally.

Exactly one synchronous multipart POST goes to `/v1/convert/file`. Its `files`
part contains the exact retained original, rechecked by path, byte count and hash;
the returned `document.filename` must match. OCR, picture description, picture
classification, code enrichment and formula enrichment are explicitly disabled.
Table structure and embedded images are requested. No external image URI is
followed. Existing bounded local HTTP transport enforces loopback peers, no
redirects and no automatic retries. Input is limited to 30 MiB and the response
transport uses a 240 KiB framing/body bound; headers consume part of that bound.

Private immutable `docling-profile.json`, `docling-contract.json`,
`docling-submission.json`, `docling-response.json` and `docling-lifecycle.json`
retain the selection, exact returned contract/body bytes, upload commitment and
lifecycle observations, when each is available. Returned bodies are retained
before JSON/schema interpretation, including HTTP failures and malformed JSON.
A transport failure can leave response bytes unavailable; its receipt says so.
Failed and cancelled durable jobs bind the retained evidence hashes and original.
PNG derivatives left by a later failed element are also bound without deleting
historical files. Failure evidence uses bounded regular-file reads and refuses
symlinks. If collecting that evidence fails, the durable failed/cancelled receipt
still records the original with a constant evidence-unavailable marker; upload
state is unknown and remote conversion may continue. Evidence-collection exception
details are not copied into that receipt. A lifecycle claims local exchange cleanup
only when an exchange was actually entered.
Identical failed/cancelled requests remain deduplicated and are never retried.

Timeout and cancellation await cleanup of the locally owned HTTP exchange. Once
submission is attempted, **remote conversion may continue**: the selected Serve
504 path still has an abort TODO, and remote termination is unproven. A local
owner acknowledgement is not remote termination. A fresh process can read the
same durable failure, original fields and ambiguity without calling the service.

Normalized text and formula segments retain element references; formulas have
kind `equation`, and the method retains the service label. Whitespace-only text
items are skipped with a count in limitations; references are not renumbered and
raw items remain retained. Only a single provenance span covering the whole text establishes
its box. Partial/multiple provenance remains in the raw response with geometry
unknown in the normalized element. Table cells retain table/row/column; a whole
table box is never assigned to a cell. A cell box requires an actual cell box and
one page provenance record. Strict indices, spans, grids, refs and finite numeric
geometry reject coercion and oversized populations before output allocation.
Finite zero-area or out-of-page element boxes retain the page with unknown bounds;
raw provenance remains available. Valid BOTTOMLEFT boxes preserve their origin.
Normalized-schema validation failures use a constant durable error, without
Pydantic's raw input values.
Embedded PNGs require matching media, strict base64, at most 256 KiB and 8 million
pixels, with at most **56 images**; Pillow is loaded only for such an image. Extracted PNGs are parser
derivatives, distinct from source pixels or a rendered page composite.

The adapter's mocked tests establish request/refusal, lineage and bounded mapping
behavior. Actual deployment identity, runtime/license admission, model behavior,
semantic fidelity, OCR and remote cancellation remain unverified. Service success
reports extraction; it supplies neither editorial approval nor parent acceptance.
