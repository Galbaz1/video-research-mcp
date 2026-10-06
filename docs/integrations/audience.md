# Durable comments and transparent audience heuristics

`tools/audience.py` defines the directly callable `audience_manage` tool and
`audience_server`, mounted by the root server. Independent source review found
no material defects. Installed bounded acceptance passed the 20-control R350
author-error-corrected epoch and R364 independent original-clause audit. The
original R328 result remains 19 PASS / 1 FAIL without rescoring; general audience
accuracy and platform completeness remain unqualified. No model, provider,
YouTube acquisition, external service or listener is started by these operations.

Use an existing canonical corpus SQLite index and an existing `comments` or
`mixed` collection configured through `collections_manage`. Every request names
`index_path`, `workspace` and `collection`; active selection is not an implicit
tenant or an authentication boundary. The importer joins the existing canonical
application ID, collection revision, filesystem policy and transaction/64 MiB
index bound. It stores immutable samples in one `audience_samples` metadata
table in that same database. There is no second database or search engine.

## Import and durable search

`action="import"` requires `expected_revision` and a `sample` with `sample_id`,
`source_revision`, `source` (`youtube` or `caller_fixture`), `source_url`,
`retrieved_at`, `sampling_method`, `sample_size`, optional `population_size`,
`comments`, and optional `videos`. Each comment requires `video_id`,
`comment_id`, `thread_id`, `posted_at`, and `quoted_text`. A reply also requires
`parent_comment_id` and `reply_id` equal to its own `comment_id`. A sampled reply
may retain a parent that is outside the sample; no parent text or identity is
invented. Exact Unicode, whitespace, newlines and timestamp spelling survive.
Timestamps must include a UTC offset; the importer does not guess one.

`sample_size` must equal the supplied comment count, including replies.
`population_size` is separately attributed caller metadata, never proof of a
complete platform census. Duplicate identities, ambiguous replies, missing IDs,
naive timestamps and denominator conflicts fail before storage. Existing sample
IDs are immutable: identical imports with the current expected collection
revision return `unchanged`; changed content requires a new sample ID. The
receipt returns the SHA-256 of the canonical UTF-8 sample payload. This digest
records supplied content identity, not independent platform authentication.

The existing `video_comments` / `YouTubeClient.video_comments` API is retained.
It currently returns text, likes and author, without the original comment/thread
IDs or posted time. That lossy result cannot be a provenance-complete import.
Supply an identity-bearing export or caller fixture instead; this tool refuses
missing fields. Existing `video_metadata` field names can populate the supplied
video snapshot after selecting the declared fields and explicitly adding format
and, when available, an opening quote. There is no automatic acquisition bridge,
new API wrapper, network flag, or inference fallback.

For example, after importing `sample-r1` into collection `comments`:

```json
{
  "action": "search",
  "index_path": "/explicit/local/corpus.sqlite3",
  "workspace": "creator",
  "collection": "comments",
  "sample_ids": ["sample-r1"],
  "query": "tutorial",
  "offset": 0,
  "limit": 20,
  "output_bytes": 65536
}
```

Search is `literal_unicode_casefold_substring_v1`, including literal `%` and `_`,
with deterministic sample/video/comment ordering. Returned quotes retain their
IDs, timestamp, sample identity/digest, source URL/revision, retrieval time and
sampling denominator. It performs no embeddings or API calls. Pagination exposes
`total_matches` and `next_offset`; overlapping samples remain attributed versions
and are not silently merged. Output overflow refuses the page and advises a
smaller page; it never silently clips a quoted string.

## Fixed deterministic analytics

`action="analyze"` requires one immutable `sample_id`, unique explicit
`video_ids`, and a named IANA `timezone`. Video snapshots require `video_id`,
`channel_id`, `title`, `published_at`, `duration_seconds` and caller-declared
`format` (`short` or `long`), with optional tags, view/like/comment counts and
`opening_text`. Missing counts remain missing. The fixed cohort digest binds the
sample digest, sorted video IDs and timezone; caller order cannot change results.
An absent cohort video or unknown timezone fails rather than filling metadata.

Results expose:

- Count ratios with their exact numerator, denominator and `defined`,
  `missing_data`, or `zero_denominator` state. Undefined ratios have `value=null`.
- `english_term_hit_balance_v1` sentiment with the complete disclosed positive
  and negative lexicons and actual matched terms in retained comment evidence.
  No hits and equal mixed hits remain distinct; English lexical counts do not
  resolve negation, sarcasm, multilingual interpretation or contextual meaning.
- `supplied_opening_first12_word_four_rule_checklist_v1` hook scores: question
  mark anywhere in the supplied opening, plus number, how/why, and imagine tokens
  within its first twelve word tokens. Each hit and the exact opening quote are
  exposed. Missing opening text stays explicit; a title is not substituted for
  an actual opening. The score is a checklist fraction, not a growth prediction.
- Short/long sample counts, observed mean views, duration medians, title-token
  and tag presence with video evidence and cohort denominators. Format is the
  caller's declaration, not an inferred or verified platform format.
- Observed upload weekday/hour frequencies in the fixed timezone, original and
  local timestamps including DST offsets, and within-channel inter-upload gap
  counts/medians. These are observed sample windows, not optimal posting advice.
- Named theme mention and sampled title/tag coverage denominators. Niche entries
  are only `sampled_topic_gap_candidate` records with retained exact comment
  evidence. The bounded `evidence_limit` can omit candidates; omitted themes and
  counts remain explicit. Market saturation is `UNKNOWN`; discovery completeness,
  platform-wide demand and economic opportunity are not inferred.

All analytics expose uncertainty, `calibrated_accuracy=null`,
`model_generated=false`, `provider_calls=0` and `model_calls=0`. Comment/reply
sampling counts are distinct from platform metadata totals and from an explicit
video subset's comment count.

## Bounds and source qualification

Imports allow at most 500 comments and 100 video snapshots per sample, at most
512 KiB canonical UTF-8 per sample, 100 retained sample identities and 5,000
retained comments per collection. The existing canonical 64 MiB database limit
also applies atomically. Stored payload lengths are checked before full reads,
and digests, typed provenance and canonical identities are revalidated on reads.
Search scans at most those finite retained bounds and returns at most 50 records;
search and analytics outputs have a 64 KiB canonical UTF-8 ceiling. Oversized
outputs fail closed. Collection retirement makes retained sample metadata
inaccessible through the existing collection scope check; retained rows still
consume canonical database space. This lane adds no deletion or quota framework.

The implementation is independently authored. The static mapped
`thatsrajan/vidlens-mcp@edd1d9fba8cf2364343b4cbd07378a649f956f08` MIT mapping is a
lead, not a verified per-file grant. No upstream source was downloaded, copied or
imported. Existing first-party SQLite/tool/error/tracing contracts are reused.

R266 checks use local SQLite/fixtures and the directly callable public tool under
network denial, including a fresh interpreter search. These source tests do not
establish installed/native acceptance or verified YouTube acquisition. Root owns
mounting `audience_server`, shared manifests/ledger/schema admission, independent
review and the original native criterion journey.
