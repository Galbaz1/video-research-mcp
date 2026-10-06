# AV memory (`video_memory_av`)

One MCP tool that builds a persistent, source-bound memory of people, dialogue, semantic
facts and audio-visual evidence for one exact media file, and retrieves **evidence records
only**. No action returns a model answer; answering stays with the caller.

The root [server](../../src/video_research_mcp/server.py) mounts this tool. The tests
described here mock provider and media boundaries; they do not establish native
acceptance on a real source.

## Workflow

1. `status` — does a memory exist in `memory_dir`, which revision, which windows lack
   evidence.
2. `build` — fold exact-SHA tool results into revision 1:
   - one `audio_transcribe` result (`kind: transcript`) supplies utterances, anonymous
     speaker labels and the parent clock;
   - `media_caption_events` results (`kind: av_events`) supply visual, acoustic and
     audiovisual records; `role: environment` declares a result as setting evidence;
   - optional `av_route` runs `media_caption_events` itself per four 30 s windows and
     role. Without `authorize_submission: true` it only returns the planned calls and
     writes nothing.
3. `overview` — people (with `also_heard_as`), the complete fact-key directory, record
   counts, environment availability and the dense index description.
4. Targeted views — `people`, `person_dialogue`, `timeline`, `moment` (optionally with an
   exact-source clip via `export_selected_clip`) and `search` (`memory`, `dialogue`,
   `facts`).
5. `plan` — one caller-planned retrieval: `people`, exact `fact_keys` (`P001/role` or a
   resolved-name alias such as `Alice/role`), descriptive `queries`, `time_ranges` and
   `include_environment`. The `question` is echoed and also searched as text; every step
   reports `found` or `not_found` with its records.
6. Changes — `add_facts` (`supplied`, or `induce` through
   `GeminiClient.generate_structured`), `align` (identity revision) and `index`
   (embeddings). Each needs `expected_revision` and publishes exactly one new revision.

## Admission contract

Every artifact is read once (≤ 8 MiB each, ≤ 32 MiB and ≤ 16 per build), hashed against
the caller's SHA-256, parsed with nonfinite constants rejected, validated against the full
typed result model (`TranscriptResult` or `AVEventsResponse`), required to be `complete`,
and bound to the memory source by `source.sha256`, `source.bytes` and each AV record's
`source_sha256`. All artifacts must agree on `source.presentation_end_seconds` (±0.05 s),
and every record span must lie inside that clock. A schema tag alone is never accepted.
Admitted bytes are retained at `memory_dir/artifacts/<sha256>.json`.

## Records, people and facts

- Windows are fixed 30 s intervals. Record IDs are
  `{kind}:{source_sha256[:12]}:{window:04d}:{seq:03d}`; identical inputs give identical IDs.
  A record keeps its own source span and its origin artifact, operation and item.
- `basis` is `asserted` for caption transcripts and `inferred` for ASR and AV-event model
  output. Environment records are model inference from a caller-declared role; visual
  hard-cut intervals are not used as environment semantics.
- People are `P001…` by first appearance of a transcript speaker label
  (`binding: transcript_speaker_label`). Names start as `null` / `unknown`.
- Self introductions and turn-taking address produce nonbinding `suggestions`; model
  name candidates from `induce` are stored the same way. Only `align` changes a name,
  appending an `IdentityRevision` that cites stored records or suggestions linked to the
  person. `evidence_aligned` requires that same person's utterance to begin with an
  explicit self-introduction (`I'm`, `I am`, or `My name is`, optionally after a greeting).
  Mentioning or addressing someone, quoted introductions, and model suggestions do
  not establish identity. Other mappings require the explicit `user_asserted` basis.
  Records keep `person_id`; names resolve at read time.
- Facts are `subject/key = value` triples citing stored record IDs. Same value merges
  evidence; a different value supersedes the loser (higher confidence, then more
  evidence, then newer wins). Losers stay `superseded` with `superseded_by`.
- Every revision is a complete immutable snapshot `rev-NNNNNN.json`, serialized and
  size-bounded (64 MiB) before being published with create-only hard-link semantics; a
  concurrent writer of the same revision is refused.
- Status reports missing-window coverage as a count and inclusive ranges. Its
  output follows stored records rather than allocating an entry for every missing
  window in a long source clock.

## Retrieval, embeddings and costs

- Keyword: Okapi BM25 over record or fact text, plus a boost field of person IDs matched
  from capitalized query names by exact, soundex or edit-similarity match against
  resolved and suggested names.
- Dense: cosine over stored vectors, fused with keyword ranks by reciprocal-rank fusion.
  Vectors come from `GeminiClient.get().aio.models.embed_content` (google-genai) with an
  explicit `embedding.model`; they are stored as `f64:<base64 little-endian>` with the
  endpoint, model and dimension, so endpoint floats round-trip bit-exactly.
- Every search reports `mode: hybrid` or `keyword_only` with
  `dense_unavailable_reason` (`no_embedding_model`, `no_vectors`, `model_mismatch`,
  `not_authorized`, `call_limit_reached`, `dimension_mismatch`, `invalid_query_vector`,
  `endpoint_failed:<class>`).
- `costs.endpoint_calls` lists only attempted calls (status, inputs, characters and the
  usage the endpoint reported); unauthorized calls appear only in `costs.planned_calls`.
  Route calls report each `media_caption_events` execution block; induction reports the
  `ExecutionBudget` record. A failed optional route returns its accounting and writes
  nothing.

## Upstream mapping

Adapted (Apache-2.0) from
[QwenLM/Qwen-MM-Plugins@0773667](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/omni-memory)
(`LICENSE` sha256 `cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30`; no
NOTICE file at that commit). Changed files carry module-docstring attribution and change
notes; no upstream code or runtime is imported.

| Upstream | Here |
|---|---|
| `get_memory_status` | `status` |
| `get_memory_overview` | `overview` |
| `get_people`, `get_person_dialogue`, `get_timeline` | `people`, `person_dialogue`, `timeline` |
| `get_moment` (with `clip_path`) | `moment` (+ `export_clip`) |
| `search_memory`, `search_dialogue`, `search_facts` | `search` scopes `memory`, `dialogue`, `facts` |
| `plan_and_search` | `plan` (no `evidence_text`; `suggested_windows` instead of replay indices) |
| `build_memory.py` per-clip omni extraction | `build` fold + optional `av_route` |
| stage-2 semantic rollup | `add_facts` `induce` |
| name ledger / roster alignment | suggestions + `align` |

Not reproduced, by design or pending coordinator decisions:

- `replay_and_answer` and `watch_and_answer` return model answers; use `moment` clips with
  the existing media tools instead.
- Multi-video `--namespace` streaming, `--mode append` and `resume`; rebuild into a new
  `memory_dir`.
- Stateful previous-window prompt continuity and visual/lip person binding; people come
  only from transcript speaker labels.
- Acoustic diarization records as a speaker source (their contract is being repaired
  separately).
