# Persistent local collections

`collections_manage` provides named transcript, comment, media and mixed
collections, explicit workspace focus, compact prior-work recall, and bounded
owned-media cleanup. It uses the same SQLite database as `corpus_retrieve` through
`corpus_index.connect`, its application ID and its optimistic collection revisions.
Observation text, vectors, terms and source revisions remain in the existing
canonical tables. Additional tables contain workspace context, collection labels
and artifact references/reservations; there is no second content or index store.

This implementation is source tested. Root owns registration, independent review
and native acceptance; passing unit tests does not close `vrm-0e8.6.6`.

## Registration

Root must add the following shared mount in `server.py`, using its existing `app`:

```python
from .tools.collections import collections_server

app.mount(collections_server)
```

No dependency or startup service is required. Quota and owned root are explicit
arguments to `configure`, persisted once per workspace. Root also owns the shared
capability manifest, reuse ledger, Bead evidence and release documentation.

## Local workflow

All requests include `index_path` (a local `.sqlite3` file) and a `workspace` ID.
Workspace context scopes selection and these collection operations; it does not
authenticate a user or establish a multi-user tenant boundary. Existing corpus
tools continue to use their explicit collection and revision contracts.

1. `configure` supplies `owned_root` and finite `quota_bytes` (1 byte–1 GiB).
   Enroll only an empty private directory, outside the database and other owned
   roots. The root and quota are immutable for that workspace. Initialization
   rejects foreign application IDs before installing metadata tables.
2. `create` supplies `collection`, `kind`, `label` and `expected_revision`.
   An existing canonical collection can be enrolled at its current revision;
   its evidence is retained without copying. A new collection starts at revision
   zero. Creation advances the shared revision and returns the new value.
3. `select` supplies a collection ID, or explicit `null` to clear focus. Selection
   persists across interpreter restart. Clearing focus preserves all data.
4. `attach` references an existing local analysis, transcript, comment corpus or
   media artifact. `admit` creates an exclusive owned copy of supplied local bytes.
   Both require the current collection revision and an `evidence` object with
   `asset_id`, `video_id`, `source_revision`, `media_digest`, `kind`, `path`,
   `sha256` and `size_bytes`. The whole artifact hash and size are verified during
   attachment/admission. Neither operation downloads, processes or infers content.
5. `list` enumerates workspace collections and canonical revision/membership
   counts. `recall` returns existing observation text and exact original intervals,
   IDs, source revisions/digests and artifact metadata. Explicit `collection` wins;
   otherwise active focus applies, or all workspace collections when focus is
   clear. Named comment collections use the same local artifact-reference workflow;
   existing comment files retain their original bytes and IDs.
6. `pin` protects a collection or its `asset_id`. `delete` removes an inactive,
   unpinned collection's canonical observations/vectors/terms/sources, or removes
   one unreferenced artifact. Collection identity retains a revision tombstone to
   prevent stale callers from reusing revision zero. `prune` reclaims a finite LRU
   prefix of eligible owned artifacts. `health` reports quota reservations and
   paginated cleanup liabilities without providers or executable probing.

For example, after configuration and creation:

```json
{
  "action": "recall",
  "index_path": "/private/local/corpus.sqlite3",
  "workspace": "editing-session",
  "collection": "interview-transcripts",
  "limit": 20,
  "output_bytes": 32768
}
```

The configured local-file access fence applies to the index, owned roots and
artifact paths. Paths containing symlinks and URI inputs are refused. Another
workspace's owned media cannot be attached or admitted through this tool. Recall
reports `present`, `missing`, `size_changed` or `refused`; `present` means a regular
file was opened, with `digest_verification: not_rehashed_on_recall`. Supplied source
hashes are provenance, not a claim that current bytes were reauthenticated during
recall. Retained historical observations identify whether their source is current.

## Quota and cleanup receipts

Quota covers this workspace's owned media, including pending admissions, failed
copies and unresolved cleanup. External attached files retain external ownership
and are never unlinked. The canonical database retains its existing independent
64 MiB limit. Untracked or altered owned-root content blocks new admission;
untracked files are never adopted or pruned. An overflowing admission rejects
before opening/copying media or adding its reservation. It does not silently evict
evidence. The caller can explicitly prune, inspect the receipt, then make a new
admission decision.

Every tracked owned file is checked against its reserved size, including pending,
failed and cleanup states. Growth beyond the reservation refuses before a new
reservation or copy and leaves provenance, revision and existing liability intact.
A shorter unresolved partial file retains its full reservation; its unused physical
bytes do not enlarge the quota. Ready files also retain their recorded inode fence.

Admission holds a verified private-directory descriptor before committing its
reservation. Output creation is exclusive and nonfollowing, relative to that held
descriptor; promotion rechecks both the configured directory and the created
output's identity and metadata. The existing regular source opener and configured
input-size/deadline bounds apply. Descriptors close on success, copy failure and
reservation rollback. Substitution noticed before creation writes no output.
Substitution racing the final check can leave partial bytes in the original held
directory, but never redirects this creation into the substituted outside directory.
That outcome reports `partial`, retains the full quota reservation and liability,
and requires owner reconciliation of the moved directory; it is not a successful
admission or a claim that no bytes were written.

LRU uses a persisted logical clock, with artifact ID as its deterministic tie
break. Admissions, recalled artifacts and selection update recency. Pruning
preserves active collections, collection/artifact pins, every retained canonical
observation revision, and shared path references, including other collections.
It selects at most `max_assets` (1–100) toward `target_bytes`; a smaller reclaimed
total honestly reflects protected evidence or the finite bound. Collection delete
refuses more than 100 owned artifacts before retiring metadata; prune first.

Cleanup records intent in the canonical database before filesystem effects. It
rechecks protection under the write lock, confines unlink to the exact private
owned directory, verifies recorded device/inode, a single hard link, full hash,
size and unchanged metadata, and fsyncs the directory. Only confirmed successful
cleanup contributes to `reclaimed_bytes`. Failed or interrupted copies, changed
bytes, missing files and unlink/durability failures retain quota charge and a
cleanup liability. A successful unlink followed by failed durability confirmation
reports `partial` and zero confirmed reclaimed bytes; actual durable reclamation
remains unknown. Failed admissions are retained for explicit owner reconciliation,
not silently retried or automatically deleted under an unverified digest.

The second cleanup transaction is bound to the original workspace and immutable
recorded path, digest, size, inode and source provenance. If another cleanup has
removed that row, or a valid admission has reused its asset ID with another file,
the stale intent is skipped with zero reclaimed bytes. The replacement row and its
bytes remain untouched. Protection is still rechecked under the canonical write lock.

All metadata changes use canonical transactions. SQLite cannot atomically commit
a filesystem unlink. The persisted cleanup intent covers that gap; a crash after
unlink leaves a charged intent whose absent path requires reconciliation. Metadata
retirement can succeed while referenced owned media is preserved, which the delete
receipt reports. External mutation by another process is not controlled by SQLite;
the private-directory and identity checks provide the local operation's fence.

Wiki revision metadata currently has a separate physical artifact-retention gap:
it does not participate in this cleanup reference scan. Root owns that later
integration; these fences do not claim protection of media referenced only by wiki
history.

Bounds are 100 retained collection identities and 5,000 artifact identities per
workspace, 64 MiB per supplied artifact, and 5,000 retained observations per cleanup
reference scan (larger scans fail closed). Recall/list pages contain at most 50
records and 64 KiB under `output_bytes`, with explicit `next_offset`; offsets assume
no intervening membership mutation. Oversized first records refuse rather than
disappear. Health paginates liabilities and retains their full count. Media reads
reuse the configured input-size and acquisition-deadline checks.

## Source basis and qualification

Independent implementation informed by
[`thatsrajan/vidlens-mcp`](https://github.com/thatsrajan/vidlens-mcp/tree/edd1d9fba8cf2364343b4cbd07378a649f956f08)
at `edd1d9fba8cf2364343b4cbd07378a649f956f08`:

| Primary file | SHA-256 | Applied workflow |
| --- | --- | --- |
| `src/lib/knowledge-base.ts` | `4a34cb42904c76e4708ee51074444af5be0ce01c4ae9fb226d00b3c7b2acd147` | Persistent names, membership, list/select/clear/remove |
| `src/lib/media-store.ts` | `155f6a06fab8278d13bfbe6ccc072c8a25c22be92046b189a335469787550b47` | Asset provenance, listing, health and removal |
| `src/server/mcp-server.ts` | `fa42d920324d5fbe8687fcab00a310de366be53de928819e54e33a5633daf049` | Workspace recall and transcript/comment/media collection workflows |
| `LICENSE` | `1126322e2cc8d165adc4c792eeb195717de2bcc7b39be1ce77959d78e87ef685` | MIT grant at the exact revision |

Each allowed raw file was acquired once, HTTP 200, bounded to 1 MiB/20 seconds.
The exact license and source receipts are retained in the private R188 return.
The implementation imports no upstream runtime or dependencies and copies no
upstream implementation. The mapped workflow is provided by the local typed tool;
upstream download, embedding, visual inference and comment fetching remain outside
this collection/lifecycle outcome.

Focused tests use real canonical SQLite operations and dummy local artifacts:
restart and clearing; existing-index enrollment; exact source intervals/provenance;
availability and provider abstention; workspace refusal; quota refusal before OS
opens; deterministic LRU and pins; shared references; canonical projection removal;
digest/symlink/hard-link fences; and charged partial/durability liabilities.
Independent review, the Root mount and native acceptance remain open.

R206 adds deterministic competing cleanup/admission interleavings for absent,
same-workspace and cross-workspace replacement rows; growth and shorter-partial
cases in all three unresolved states; directory substitution before and at relative
creation; output/directory replacement before promotion; reservation rollback;
and size/deadline/durability failures with descriptor closure. The original failing
source epoch is retained separately from the repaired source checks.

Upstream MIT notice, retained with the source basis:

```text
MIT License

Copyright (c) 2026

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
