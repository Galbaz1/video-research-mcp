# Evidence-linked canonical wiki history

`wiki_manage` adds human-readable, versioned concept/topic/entity/video pages to
the **existing canonical corpus SQLite database**. It reuses
`corpus_index.connect`, the corpus application ID and existing observation/source
identities. The wiki operation refuses an absent or foreign database. It creates
no independent engine database, content directory, provider store or service.

The registered implementation has passed source review and 89 focused checks.
A private installed candidate exposes `wiki_manage`; its actual public journey
and native acceptance remain open. Unit/mock results do not close `vrm-0e8.7.6`.

## Root integration

The shared registration in the existing root `server.py` is:

```python
from .tools.wiki import wiki_server

app.mount(wiki_server)
```

No dependency/config change is required. Existing corpus indexing supplies source
observations; wiki operations link their exact versions. Root also owns shared
manifest/reuse-ledger/Bead/release updates and the native user journey. Existing
Weaviate concepts remain available through their current tools; this local route
does not infer equivalence with them or mutate that graph.

## Workflow and identity

Every request supplies the same local `index_path` used by `corpus_retrieve`.
The configured local-file fence applies, with URI and symlink-parent refusal.

1. Index source observations through the existing corpus tool. Each observation
   carries its video/observation/source-revision/media-digest identity, exact
   original interval and artifact references. Wiki binding does no media
   processing, downloading or extraction.
2. `write` supplies an explicit `concept_id`, `kind`, `title`, caller `body`, tags,
   `expected_revision`, and 1–100 evidence contributions. Evidence fields are
   `evidence_id`, `collection`, `video_id`, `observation_id`, `source_revision`,
   `media_digest`, `attribution`, `claim`, and `stance` (`reported`, `unknown`, or
   `conflicting`). The corresponding canonical observation version must exist
   and match the supplied identity/digest.
3. Two sources supplied under the same explicit concept ID produce one canonical
   concept with two evidence links. IDs are case-sensitive and never inferred,
   normalized or merged from similar titles. Attribution labels and claims are
   caller supplied; they do not authenticate a speaker or establish verified fact.
4. Subsequent writes require the current **wiki page revision**, starting at zero
   for a new identity. They append evidence contributions and version caller
   prose. Reusing an evidence ID with changed attribution/claim/provenance refuses;
   use a new contribution ID for a correction. Existing contribution snapshots
   remain unchanged. Concept kind is fixed; title/prose/tags can change in a new
   revision. Corpus collection revisions remain unchanged by wiki writes.
5. `get` returns current or specified revision. `history` returns immutable
   revisions, newest first. `list` and `toc` return compact identity/title/type/
   revision/tag/digest records, with exact kind/tag filters. `search` performs
   deterministic SQLite FTS over current page titles, caller prose, attributed
   claims and tags. Query words are quoted literal terms, not raw MATCH syntax.
6. `remove_source` supplies `video_id` and `expected_revisions`, a map containing
   exactly all affected current concept identities and revisions. Removal is
   atomic across those pages; a missing/stale pin refuses before changes.
   Contributions from other videos survive. Prose is cleared after source removal
   so removed support does not leave stale current synthesis. A page with no
   remaining contributions becomes retired, retaining its identity/history.
   Current list/search excludes retired pages; explicit get/history still works.
   Corpus observations, media, and historical wiki revisions are never deleted.

For example, an explicit context-only question is:

```json
{
  "action": "ask",
  "index_path": "/private/local/corpus.sqlite3",
  "question": "What do these sources say about the mechanism?",
  "concept_ids": ["concept:mechanism"],
  "mode": "context",
  "context_bytes": 32768
}
```

## Revision and source integrity

Current heads, immutable page revisions and current-page FTS metadata reside in
the same corpus database. SQLite transactions join history append, head advance
and FTS replacement. SQL triggers refuse UPDATE/DELETE on revision rows. Payload
SHA-256 is checked during retrieval, and every revision preserves its original
page text, claims, source digests, observation-payload hashes, timestamped links
and artifact identities. These hashes detect byte changes; they are not signatures
or proof of source ownership.

Evidence links store provenance snapshots, not duplicate source observation text
or media. Their exact source intervals come from canonical observations. Each link
also records UTC `linked_at` and the corpus revision at binding. Wiki history
survives interpreter restart and independent corpus removal. Ask exposes source
text only while the canonical observation's retained payload hash matches; changed
or absent observations are labeled explicitly. Current-source identity is distinct
from retained historical identity.

Artifact availability is `present_unverified_digest`, `missing`, or `refused`.
Availability checks paths without reading/reprocessing media bytes. Opening the
returned links and checking artifact integrity is a separate native acceptance
step. Collection cleanup consults the retention helper below before reclaiming
history-only artifact links. Independent file deletion remains outside these operations;
wiki history retains provenance and reports missing evidence honestly.

## Wiki history retention seam

`collections_wiki_refs.referenced_by_wiki(db, asset)` reads immutable revisions from
the same canonical SQLite connection already held by collection cleanup. It creates
no table, cache, pin state or secondary store and imports only the existing page
model, canonical size limit and local path fence. It checks current and historical
revisions, including retired pages, without filtering through current page heads.

The following import and one call are integrated at the start of the existing
`collections_media.referenced` function, inside its current canonical transaction:

```python
from .collections_wiki_refs import referenced_by_wiki

# Inside referenced(db, asset), before its existing corpus/asset checks:
if referenced_by_wiki(db, asset):
    return True
```

Source integration and its local delete/prune checks pass. Existing cleanup
catches `ValueError`/`OSError`, preserves the
bytes, and records a liability when reference validation refuses. No server,
configuration, schema, dependency or provider change is required for this seam.

Retention requires an explicit artifact reference whose canonical local path and
SHA-256 match the owned asset. An equal digest at a different path does not create
a link. The retained source `media_digest` has no physical media-path binding in
the current wiki schema, so digest equality alone never protects unrelated media.
A conflicting digest at the same linked path refuses cleanup rather than treating
uncertain identity as permission to unlink. Symlink/URI/outside-root references
retain the existing path refusal.

Every scanned payload is checked against its stored SHA-256, validated with the
existing `Page` model, and compared with the row's concept/revision identity. Bad
JSON, invalid typed provenance, tampered hashes, partial/altered schema and oversized
history refuse; they do not silently return unreferenced. A corpus with no wiki
schema returns `False` without initializing it. Validation continues after a match,
so a later corrupt retained revision is not hidden by an earlier positive result.

The scan uses the existing limits: at most 1,000 × 100 = 100,000 retained revisions,
128 KiB of UTF-8 payload per revision, and the canonical 64 MiB database ceiling.
It streams a query limited to 100,001 rows to detect overflow. Oversized payloads
are excluded from the returned payload column before Python page validation, then
refused. Exceeding the finite bounds refuses cleanup; these bounds do not alter
wiki admission quotas.

Removing a source from a current page, retiring a page, or deleting canonical corpus
observations does not release historical references. Immutable retained history
continues to require the physical artifact. There is no automatic release or new
release API in this seam.

Focused tests call the helper directly on actual retained SQLite payloads and dummy
owned files. They cover history/update/retirement and interpreter restart after
canonical observation removal, same-digest unrelated delete/prune, absent schema,
corrupt provenance, scan/payload overflow and path refusal. The scan-overflow unit
fixture reduces only the test's scan constant to exercise the boundary with three
rows; the production bound remains 100,000. Original 20 wiki and 41 collection source
cases remain preserved. The combined 89 source checks include both original
families and verify deletion refusal and prune preservation after current wiki
links and corpus observations disappear. Ten additional cases commit missing
history/head tampering before checking that delete/prune preserve bytes and state.
The independently reviewed completeness guard refuses these inconsistent histories.
Installed public journey acceptance remains open.

## Ask and synthesis

`ask` first freezes selected page revisions and evidence context within
`context_bytes`. Explicit concept IDs select the caller's scope; otherwise literal
FTS terms choose up to `top_k` pages. The response includes context, its SHA-256,
measured serialized bytes, and omitted-page count. A context budget too small for
any page returns explicit `no_evidence`, with no generation.

Default `mode: context` calls no provider. `mode: caller` requires `caller_text`
and returns `synthesis_origin: caller_text`, `model_generated: false`. It does not
claim that caller prose is evidence-verified.

Explicit `mode: gemini` uses the existing `GeminiClient.generate_structured`
contract and configured `default_model` (or caller model override). It runs inside
the existing `job_submission` single-submission scope, supplies no external tools,
and has a 30-second deadline. The structured prose schema bounds text to 8,000
characters. The system instruction treats source text as untrusted data and
requires attribution of unknown/conflicting claims. Successful output exposes
`synthesis_origin: model_generated`, `model_generated: true`, model and citations,
alongside the exact retrieved context. Citations must be the supplied `citation_id`
values, derived from concept ID, local evidence ID and observation-payload hash;
this avoids ambiguous IDs across pages. Citation membership does not prove semantic
entailment. Mocked tests establish the contract; actual provider quality remains
UNRUN. A provider/schema/invalid-citation failure is a typed error and changes no
page history. If an existing execution budget rejects this system-context path,
that policy remains effective; this tool does not bypass it.

## Finite bounds

- Existing canonical database limit: 64 MiB, checked before write commit.
- 1,000 retained canonical page identities; 100 immutable revisions per identity.
- 100 evidence contributions and 20 tags per page; 128 KiB serialized revision.
- Get/history/list/search pages: at most 50 records and 256 KiB requested output,
  with explicit `next_offset`. An oversized first page refuses instead of vanishing.
- Ask: at most 10 selected pages, 64 KiB context, 2,000-character question,
  8,000-character prose and a 30-second generation deadline.
- Source removal: at most 100 affected pages, with all current revision pins.

Offsets assume no intervening membership mutation; exact historical revision IDs
and hashes remain stable. All local writes are transactional; source/raw media
is untouched. No model/provider/capture/device/service/browser/native work was
performed for this implementation outside mocked unit fixtures.

## Primary design receipt and behavior map

Passive source reads were limited to these four exact raw files from
`0xchamin/mcptube` at `e619bc1c0ab425ecb7b214819b9f434fdf4809a3`, once each,
bounded to 1 MiB and 20 seconds. All returned HTTP 200:

| File | SHA-256 | Independent behavior provided |
| --- | --- | --- |
| `src/mcptube/wiki/engine.py` | `c3e706c41c932fa60aa8339b1315f3888b72407adeda1dabed5049926be80a05` | Ingest/link, search, ask, page/list/TOC/history, remove-source workflows |
| `src/mcptube/wiki/storage.py` | `37bd616c900f480de3610a1aae8ff4764fa81b4c65052d29221fd561f4acc1b5` | Atomic page storage, current FTS projection, persistent revision history |
| `src/mcptube/wiki/updater.py` | `236db0af1c41c563a5a8f65aa5207c5568e355d3913f4cf29c7338049ee8f61a` | Append immutable attributed contributions and update explicit canonical pages |
| `pyproject.toml` | `957ac2728015edb78dd07f58610ae5101c4d956f1e00e8b95b7bb1af42a4a32d` | Observed MIT declaration; grant remains absent/unverified |

The assignment reports no standalone MIT grant. No LICENSE fetch, upstream import
or literal implementation copying was attempted. This is an independent
implementation of the required behavior on existing project contracts. Automatic
LLM extraction/entity merging is replaced by explicit caller concept/evidence
identities. All page kinds retain revision history; empty pages retire rather than
erase history. Optional prose uses this project's existing client.

Focused unit tests cover all four original criteria, real canonical SQLite
transactions, dummy interpreter restart, exact source intervals/digests, attributed
disagreement, page/source removal, SQL history protections, local path fences,
output limits, context/citation disclosure, and mocked provider success/refusal.
Actual transport, opening native evidence links and configured provider evaluation
remain open. Frozen evaluation cohorts
and prior implementation lanes are unchanged.
