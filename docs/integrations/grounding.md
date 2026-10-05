# Grounded answers, abstention and bounded evidence escalation

`grounded_answer` (`tools/grounding.py`, server `grounding`) checks caller-asserted
claims against evidence retrieved by the canonical corpus query
(`corpus_retrieval.query`). It never writes answer text. Optional synthesis reports
`unsupported` because no authorized synthesis route is configured here.

The design reimplements the evidence-sufficiency idea from
`oxbshw/watch-skill@f1317c8fe64744a606c31867b05fbbe3144268c6` (MIT). No upstream code,
confidence weights or calibrated probabilities are copied or invented.

## Request

| Field | Meaning |
| --- | --- |
| `retrieval` | An unchanged corpus `QueryRequest` with pinned `source_revisions`. |
| `claims[]` | Caller-asserted `claim_id`, `text` and up to eight citations. |
| `citations[]` | `observation_id`, `source_revision`, cited `start_seconds`/`end_seconds`, optional verbatim `quote`. |
| `repair_citations` | Re-anchor a failed quoted citation to the first retrieved observation containing the quote (default `true`). |
| `verify_byte_budget` | Total artifact bytes hashed for citation availability (default 32 MiB). |
| `escalation` | Optional source `file_path`, `expected_source_sha256`, display `crop_box`, `max_pixels` and `budget` (`max_attempts` ≤ 8, `max_bytes` ≤ 8 MiB, `deadline_seconds` ≤ 120). |

## Citation rules

A citation is valid only when all of these hold:

1. It names an observation present in this retrieval's selected context.
2. Its revision matches.
3. Its interval lies inside the observation interval.
4. Any quote has nonempty text and occurs in the indexed observation text. Matching is case-sensitive; only whitespace runs are collapsed.
5. Every artifact reference still has its recorded SHA256.

Artifact paths pass the local fence and symlink checks. Each artifact must be a
regular file, opened nonblocking without following links, with its opened type and
identity checked. Reads are bounded by the admitted size plus one byte to detect growth.
A file larger than the remaining budget is reported `unverified` without being read.

A failed citation is either repaired, with a `citation_repaired` trace event that
keeps the original citation and the reason, or rejected with a `citation_rejected`
event. Unquoted citations are never repaired.

Quote checks use the indexed observation text. They do not show that this text
matches the artifact contents. Availability is not factual truth.

`claim_basis` is always `caller_asserted`. Each citation also carries an `evidence_basis`:

| Observation kind | `evidence_basis` |
| --- | --- |
| speech | `supplied_transcript_text` |
| OCR | `supplied_ocr_text` |
| description | `caller_asserted_description` |

## Outcomes

| Status | When |
| --- | --- |
| `grounded` | Every claim's nonempty text equals a verified quote after whitespace normalization. |
| `partially_grounded` | Some citations are available, but one or more claims lack exact verbatim support. Paraphrases and claims differing from their quoted text remain `citation_available_semantics_unverified`. |
| `abstained` | No claim has a valid citation, or there are no claims and retrieval found nothing. |
| `evidence_only` | There are no claims and retrieval returned evidence. |

When the result is not fully grounded, `missing_evidence` names the question-level
or claim-level gap. Semantic conflicts between observations are not detected.

## Escalation

The first valid citation of each semantically unverified claim may be escalated, but only when
the escalation source SHA256 equals the cited observation's `media_digest`.
Otherwise it is refused before any decode.

Points are the cited start, midpoint and end. Each point uses the existing
`media_frames.frame_at` precise route. Every attempt records:

- the requested time and the actual time derived from the decoded PTS;
- `original_pts`, `time_base` and `within_cited_span`;
- the crop box in display coordinates;
- the source snapshot path, SHA256 and bytes;
- the PNG artifact path, SHA256, bytes and size.

Escalation stops with `attempt_limit`, `byte_budget` or `deadline`. Before each
attempt, `4 * max_pixels + 65536` bytes are reserved. A frame that would exceed
`max_bytes` is deleted and kept as `discarded_byte_budget`. An attempt cut off by
the deadline is kept as `failed`.

No model interprets frames (`interpretation: not_performed`), and
`limits.auxiliary_calls` counts every decode attempt.

If discarding an oversized frame fails, the report retains the primary byte-budget
stop, the decoded time/source receipt and a separate `cleanup_error` containing
the remaining artifact's path and digest. No later frame is decoded.

## Quality evaluation

`grounding_quality.evaluate(cases, frozen_sha256, results)` scores a frozen cohort,
identified by its canonical SHA256, against declared expected outcomes.

The denominator is always the full cohort:

- missing results count as `unrun`;
- typed errors count as `refused` or `failed`;
- abstentions are retained;
- auxiliary calls are summed.

Results naming unknown cases are refused, and results never relabel a case. The
reported agreement is outcome agreement on fixtures. It is not semantic accuracy
or calibrated confidence.

## Integration status

The sub-server is mounted and source discovery exposes its tool. Source review
repairs and installed native qualification remain in progress. Unit tests use
authored corpus artifacts and the existing mocked native decode boundary. They
prove neither real-video decoding nor evidence semantics.
