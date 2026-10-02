# Recoverable session context and scoped derived memory

Sessions retain every accepted original SDK message, including opaque thought
signatures, inline media and provider URI references. Set `GEMINI_SESSION_DB` to
an operator-selected private SQLite path to recover those originals after restart.
An active-session timeout, LRU eviction or provider context-cache expiry does not
delete the SQLite archive. In-memory sessions have no restart guarantee. Legacy
rows retain their actual available history and explicitly report
`history_complete=false`; previously discarded messages cannot be recovered.

`video_create_session` accepts optional `scope` with exactly `workspace_id` and
`notebook_id`. Supply that same scope to `video_continue_session` and
`session_memory`. Existing unscoped sessions remain unscoped. Every memory request
also requires the original `session_id` and exact `source_id` from creation or
continuation metadata. Validation occurs before reading a profile or scanning
history. Scope selectors provide local isolation; they are not authenticated
multi-user identities or an OS access-control boundary.

Continuation builds a separate replay view. `GEMINI_SESSION_MAX_TURNS` bounds its
turn window, `GEMINI_SESSION_RECENT_TURNS` protects recent pairs (default2), and
`GEMINI_SESSION_CONTEXT_TOKEN_BUDGET` bounds its declared text-token estimate
(default32768). The deliberately conservative estimate counts one serialized
UTF8 byte per estimated text token, including source IDs, header, signatures,
references and the pending prompt. It is not a provider tokenizer measurement:
expanded media and cached-content tokens are unknown. No tokenizer dependency,
model summary call, provider savings or hard aggregate inference-token guarantee
is claimed. If protected recent messages, source metadata and the prompt do not
fit, the request fails before generation or appending a turn.

Selection reports the omitted original message range, full-history SHA256,
retained messages, budget/method and persistence/completeness state. Derived
memory is omitted separately if it cannot fit; that omission is disclosed. The
header identifies learned text as untrusted and non-authoritative, says originals
take precedence in conflicts, and supplies an exact original-refetch request.
This instruction and provenance are inspectable contract behavior; semantic
model obedience and factual success require separate evidence.

The deterministic local `session_memory` tool provides these bounded operations:

| Operation | Behavior |
|---|---|
| `history` | Return exact original SDK messages by offset/limit (maximum100). Pages above128KiB export private, content-addressed JSON with full SHA256/readback instead of oversized inline output. |
| `list` | List original logical message files such as `messages/00000000.json`; optional `pattern` performs a bounded glob on those names only. |
| `search` | Match a required literal `query` in original message text; no regex, host search or summary-derived matching. |
| `compact` | Inspect the same bounded selection with an empty pending prompt; originals are unchanged and no model is called. |
| `get` | Inspect one workspace/notebook/source derived profile. |
| `set` | Explicitly create/edit synopsis text at `expected_revision`, recording original session, source revision and history commitment. |
| `delete` | Clear derived content at its current revision; original history/media remain intact. |

Learned text is limited to32KiB. SQLite revision checks reject stale edits and
deletions, including across two connections. Content-free deletion tombstones
preserve monotone revisions; recreation uses `expected_revision=0` and advances
the old revision. Archive writes are limited to8MiB serialized SDK history and
reject shortened/divergent prefixes, decreasing turn counts or changed immutable
source/scope before mutating active state. Exports verify owned staging bytes,
then publish atomically without overwriting existing data. Cancellation removes
only staging; it cannot remove an export already returned to another request.
Repeat retrieval revalidates its bytes. Export files share the configured private
cache and its local filesystem access policy.

Local/uploaded sessions bind full original SHA256 and original path/origin
separately from expiring File API URIs. Continuation uses the existing account-
scoped upload reconciliation contract: creation retains the exact upload digest
through cache preparation and rejects a changed original before binding a session.
Exact original bytes must still be
available, one known-expired resource can be replaced, and an unknown prior
submission is not automatically repeated. A changed or missing original fails.
Refreshed aliases are applied only to the detached replay; archived messages keep
their exact original URI. Remote YouTube locator-only and legacy sources disclose
unknown byte revision. History retrieval itself performs no upload or provider
call; remote locator availability is not established by stored references.

Reuse is an independent implementation of the selected DeepAgents source-history
and store contracts at `1756bbe1eb348e20b925598ed49665b0d34b4b2d`.
Four mapped source bodies and both actual MIT grants were read/hashed before
implementation. No foreign code, package, host shell, sandbox or model is bundled.

| Mapped surface | Selected source-preserving equivalent |
|---|---|
| `compact_conversation`, automatic/manual compaction | Detached continuation selection and explicit `compact` inspection. |
| `read_file`, offloaded originals | Exact `history` page or hashed JSON export with original media/signature fields. |
| `write_file`, scoped store/memory | Explicit revision-checked `set`/`delete` on one exact profile. |
| `ls`, `glob`, `grep` | Bounded `list`/logical-name glob and literal `search` within the validated original session. |

Generic host filesystem/shell capabilities are outside the audited selected
history/memory responsibility. These source-scoped equivalents preserve the
mapped retrieval/edit/search workflow without granting unrelated file access.
Conversation originals, including previous model answers, remain conversation
data; learned summaries never become verified media evidence or source passages.
Live inference, human source/media audit, held-out comparison and release remain
separate acceptance stages.
