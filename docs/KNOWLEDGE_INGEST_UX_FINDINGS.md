# Knowledge Ingest UX: Findings & Recommendations

Last updated in the original session: **2026-03-05 20:12 CET**.

This note records a March 5, 2026 usage session: GPT-5.4 video analysis,
cross-platform sentiment research by four parallel researcher agents, then
manual `knowledge_ingest` calls. It preserves that session's observations and
recommendations; it is not a benchmark of the current implementation.

## Problem

The session encountered eight failed calls before establishing a working manual
ingestion pattern. The caller could supply a properties dictionary, but the tool
did not expose the collection schema. Discovering names took three round-trips:
try plausible keys, receive an unknown-property error, inspect an existing object,
then retry.

The naming differences were concrete:

| Collection | What the caller had to discover |
| --- | --- |
| ResearchFindings | `claim` instead of `finding`; `supporting` instead of `sources` |
| ConceptKnowledge | `concept_name` instead of `name`; no `category` or `related_concepts` |
| CommunityReactions | `consensus`, `themes_positive`, `themes_critical` and `notable_opinions_json`; no `platform`, `reaction_summary` or `source_url` |
| VideoMetadata | `channel_title` instead of `channel`; no `local_filepath`, `source_url` or `screenshot_dir` |

## Root Cause

At the time, collection definitions in `weaviate_schema/` supplied the runtime
validation map in `tools/knowledge/helpers.py`, but the tool interface did not
expose those definitions. A generic `dict` parameter left callers to infer
property names from the collection's purpose. That inference failed when ordinary
words such as “finding” did not match the stored field name `claim`.

## Impact

The observed cost was eight failed calls and three discovery round-trips. The
original note estimated about 500–1,000 tokens per failed ingest/retry attempt;
it did not report a measured token total. It also identified likely friction
for new users and background agents that lacked a schema-discovery step. Those
adoption and agent-recovery effects were concerns, not separately measured outcomes.

## Recommendations

The session proposed three changes, with these approximate implementation sizes:

| Priority at the time | Proposal | Estimated size | Intended effect |
| --- | --- | --- | --- |
| Do now | Include allowed properties in validation errors | 1 line | Make a rejected call easier to correct |
| Next release | Add read-only `knowledge_schema` | About 30 lines | Expose names, types and descriptions before ingestion, without a cluster connection |
| Optional | Add field hints to the ingest docstring | About 10 lines | Help common calls, while accepting that a duplicated field list can drift |

The schema proposal required no collection change or migration. Its purpose was
to expose the existing definitions. The proposed error message would show both
unknown and allowed keys. A static docstring list was considered useful but
fragile because it would have to change with the schema.

### Current implementation note — 2026-09-29

The source now implements the first two recommendations:

- [knowledge_schema](../src/video_research_mcp/tools/knowledge/schema.py) returns
  `schemas` and `total_collections` from local definitions, even when Weaviate is
  disabled.
- [knowledge_ingest](../src/video_research_mcp/tools/knowledge/ingest.py) rejects
  unknown keys with allowed `name:type` pairs and a hint to call
  `knowledge_schema(collection=...)`.
- [Schema tests](../tests/test_knowledge_schema.py) cover single-collection,
  all-collection and no-Weaviate discovery, plus the enriched error message.

The recommended current sequence is to inspect the schema, supply its property
names and value types, ingest, then fetch the returned UUID. See the
[Knowledge Store guide](tutorials/KNOWLEDGE_STORE.md#using-the-knowledge-tools).
This source inspection does not establish that the March workflow was rerun or
that failed-call counts have decreased in real use.

## Session Evidence

### Successful ingests (after discovery)

| Collection | Objects recorded in the session |
| --- | --- |
| VideoAnalyses | 1 video analysis, with `key_points` as `text[]` |
| CommunityReactions | 1 cross-platform sentiment record with themes |
| ResearchFindings | 3 records: developer sentiment, Claude versus GPT-5.4, and #QuitGPT |
| ConceptKnowledge | 3 records: GPT-5.4, Extreme Reasoning, and the #QuitGPT movement |

These are recorded ingestion successes, not verification of the records' claims.

### Failed attempts before discovery

| Collection | Rejected input recorded in the session |
| --- | --- |
| VideoMetadata | `channel`, `local_filepath`, `source_url`, `screenshot_dir` |
| VideoAnalyses | `key_points` as a string rather than `text[]` |
| CommunityReactions | `platform`, `reaction_summary`, `sentiment_score`, `source_url` |
| ResearchFindings | `finding`, `sources`; three objects failed |
| ConceptKnowledge | `category`, `name`, `related_concepts`; three objects failed |

The original session counted **eight failed calls**. A call and an object are
different units, so the object counts above should not be added to reconstruct
that call total.
