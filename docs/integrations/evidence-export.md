# Offline evidence export

`evidence_export` creates a new local directory containing `report.html`,
`report.md`, and `report.json` (or a selected subset). It uses canonical evidence
through `corpus_retrieve.query`, `wiki_manage.ask` in context mode, or
`collections_manage.recall`. It creates no new database, downloads no media and
invokes no model or provider. Collection recall retains its existing LRU use
bookkeeping; it does not delete or admit assets.

The root [server](../../src/video_research_mcp/server.py) mounts
`video_research_mcp.tools.evidence_export.evidence_export_server`. Registration
exposes the local tool; it does not establish installed or browser acceptance.

Example request, using an existing canonical corpus and an existing parent directory:

```json
{
  "source": {
    "kind": "corpus",
    "request": {
      "action": "query",
      "index_path": "/allowed/corpus.sqlite3",
      "collection": "evidence",
      "query": "copper",
      "source_revisions": {"video-a": "r1"},
      "mode": "fts",
      "top_k": 10,
      "token_budget": 4096
    }
  },
  "output_directory": "/allowed/new-review",
  "title": "Copper evidence",
  "missing_frames": "report"
}
```

Wiki selection uses `source.kind: "wiki"` and the existing `ask` request with
`mode: "context"`, a question and optional concept IDs. Its exported records
retain page revision/digest, exact citation, attribution, stance and matching
observation text. Changed or missing observations remain explicitly labeled;
they are not reconstructed from the attributed claim.

Collection selection uses `source.kind: "collections"` and a bounded `recall`
request with index path, workspace and optional collection/pagination. Asset paths
and digests are retained. Assets without timing/text remain untimed; thumbnail and
keyframe references can be illustrated. Other assets are metadata-only citations.
`next_offset` and omitted wiki pages are reported, without automatic pagination.

Explicit caller fixtures use `source.kind: "fixture"` and at most 50 validated
records. Their origin is always `caller_fixture`, even if a caller supplies another
origin. Supplied observed/inferred labels, model and method describe caller
assertions. Canonical observations that do not record these fields export
`basis: "unknown"`, `model: null` and `method: "not_recorded"`. Text, OCR, titles,
claims and identities remain evidence data, not instructions or verified truth.

The HTML contains only inline CSS, internal citation anchors and bounded data
images, with a restrictive CSP. It escapes all untrusted text. PNG, JPEG and WebP
signatures are admitted after exact digest verification; no SVG/HTML, scripts,
external image/link resources, audio/video decoding or external requests are used.
Byte verification does not authenticate depicted content or establish successful
image decoding. Frame captions retain the linked observation interval and state
that frame capture time is not recorded; no frame clock is invented.

Each frame is at most 256 KiB. `max_inline_bytes` defaults to 512 KiB and cannot
exceed 4 MiB. `max_export_bytes` defaults to 2 MiB and cannot exceed 8 MiB across
all selected output files, including escaping/base64 expansion and repeated image
references. Reads use regular-file and configured local-path fences and detect
growth/replacement. JSON retains provenance and artifact references without base64
duplication; Markdown retains the same identities, intervals, labels and citations.

Missing, changed, refused or oversized frames produce named `frame_issues`, a
`partial` status and `complete: false`. No image is emitted for that reference.
`missing_frames: "refuse"` instead rejects before creating the output directory.
An empty canonical selection produces `no_evidence`. Exports never overwrite an
existing directory. Outputs are private exclusive files, descriptor-bound and
read back before the success receipt; a write failure cleans only owned outputs.
The verified parent descriptor is held before evidence selection. Creation and
cleanup remain relative to that descriptor when pathname ancestry changes.
If cleanup is refused, the error retains the primary write failure and names the
remaining directory; it does not report a successful export or completed cleanup.

Implementation and tests are independently authored first-party code. The foreign
inventory entry is a static design lead; no foreign code, prompts, assets or runtime
were copied. The focused tests use dummy canonical stores and tiny authored image
fixtures. Native media/browser rendering, provider quality and release admission
remain separate Root evaluations.
