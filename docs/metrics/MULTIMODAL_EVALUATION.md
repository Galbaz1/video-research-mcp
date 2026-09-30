# Frozen multimodal evaluation protocol

The protocol for `vrm-0e8.2.7` is
[multimodal-evaluation-protocol.json](multimodal-evaluation-protocol.json).
It freezes the 74-package inventory, nine workflow families, baseline source
revisions, development/acceptance separation, metrics and decision thresholds
before product tuning. Beads owns readiness; this document describes the evaluator.

## Sources and baseline selection

The public product baseline is `a3d75f6ab87bd893c7d167394fb5bace717f23ec`.
Each family also names its capable specialist nominees and pinned revisions in
the protocol. Evaluate the public baseline and every capable nominee on the same
inputs, shared task prompt and bounded resources. Record the exact provider,
model, adapter, search/sampling settings and their configuration hashes before
execution. Choose the strongest *per-workflow development baseline* before tuning;
retain that selection receipt and every nominee's unsuccessful attempt. An
unavailable specialist cannot be silently replaced with a weaker competitor or
used as evidence of superiority. Optional hosted and restricted-runtime routes
retain their resource/license prerequisites.

The [GPT Researcher hybrid benchmark](https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/deep_agents/hybrid_benchmark.py)
motivates fixed local/web/hybrid inputs with archived distractors. The
[VideoRAG comparison script](https://github.com/HKUDS/VideoRAG/blob/c412a093a820ef7a0e0dda31076ed871136198b3/VideoRAG-algorithm/reproduce/quantitative_comparison/batch_quant_eval_calculate.py)
motivates per-domain comparison. This evaluator is independently written; no
upstream code, benchmark corpus, restricted implementation, model weight or
author-reported score is imported.

## Frozen inputs and independent acceptance

Public development inputs, labels, example outputs, source observations and the
shared prompt live in `tests/evaluation/fixtures`. These text observations test
contracts; they are explicitly marked as observations rather than real media
inference. The separate
[held-out manifest](multimodal-heldout-manifest.json) commits independently
authored original media, case inputs, labels, source snapshots and the prompt.
Answer-bearing files stay in the custodian's private bundle and must never be read
by the implementer or passed to the candidate's tools. Case IDs and hashes are
public commitments, not answers. The initial 27-case corpus is an offline contract
sample and has insufficient coverage/power for a superiority claim.

The independent owner must seal a powered cohort with at least 30 cases per
declared workflow before its tuning/live comparison. Each adopted workflow needs
positive, absent-evidence, failure and restart cases where applicable. Freeze
original source bytes, rights receipts, media sampling and timebase, labels and
case order. The protocol covers text, image, video, audio, geometry and tabular
evidence; visual-only and audio-only facts, precise intervals, ordering,
cross-video recall, contradictory/stale sources and long recordings are required.
The original named package acceptance remains authoritative.

Freeze the candidate revision before independent acceptance. If held-out evidence
informs a successor, retire that set and prepare a new independently owned cohort.
A failed comparison is retained. Increasing the denominator or moving thresholds
after a failure cannot produce an accepted comparison.

## Measures and materiality

Every assigned case remains in the completion denominator. Timeout, refusal,
unavailable source, error, malformed output, missing output and explicit abstention
receive separate status counts. A negative case may correctly produce an error
or abstention; that is successful contract behavior, not a factual answer.
Structural validity and correct failure handling do not establish factual support.

The deterministic judge compares short canonical facts with only case/whitespace
normalization. It separately reports fact recall, supported-claim precision,
citation precision/recall, timestamp precision/recall, structural validity and
case completion. Claim IDs are candidate-owned and reveal no reference labels.
Temporal slot IDs are in the input; exact reference boundaries remain withheld.
Duplicate claims, extra false citations and fabricated answers to absent evidence
cannot pass completion.

For text, the judge re-reads the hash-frozen source and verifies both the exact
quotation and its reference-label relationship to the claim. An unrelated real
quotation is not support. For binary media, it verifies original asset hashes,
separate private judge-snapshot commitments and source/interval bindings. A media
citation uses `quote: null`; construction descriptions are never shown to the
candidate. This is reference-contract checking, not semantic proof that a model
inspected the original media. Free-form prose and media interpretation need
independent source/media review before product acceptance.

Each fact's reference evidence is conjunctive: every listed source passage must
be supported. A cross-video or conflicting-source synthesis cannot pass by citing
one of the sources while dropping the others.

Timestamp tolerance is 500 ms at both interval boundaries, independent of prose.
Artifact bytes must exist, be nonempty and match the returned hash. Actual decode,
playback, geometry, document layout, source support and publication acceptance
need the appropriate independent artifact validator. A file hash alone establishes
only byte identity. Empty source/outcome cannot be labeled factual success.

The frozen materiality target is at least **10 percentage points of workflow
completion gain**, with a paired 95% bootstrap interval strictly above zero.
Fact/citation quality must reach **95%**, with at most **2 percentage points of
non-regression** against the retained baseline. Fabricated support is forbidden;
applicable timestamps must all pass. Full-job cost and latency may each be at most
**1.25 times** baseline. No composite score hides tradeoffs. The same gates are
reported by family and by workflow; a large family cannot conceal a weak workflow.
The bootstrap uses seed 20260930 and 5,000 paired resamples. These declared targets
may prove unreachable against a saturated baseline; preserve that outcome and keep
the programme's superiority claim open rather than relaxing the criteria.

All attempts, retries, failures and auxiliary work belong in full-job usage.
The replay scores one attempt per case; retries require separately retained
receipts and an independent complete-job aggregation at final acceptance.
Record inference, search, embedding, reranking, caches, review, maintenance and
human time separately where observable. Missing telemetry is `null`, never zero.
The arithmetic comparison returns numerical eligibility only. It always leaves
`material_advantage` false until the independent acceptance gate verifies the
cohort, strongest-baseline receipts, resource authority, all adopted workflows,
source audit and artifact validators.

## Replay contract

Inputs are a list of strict `Case` records; labels are a separate object keyed by
case ID. Outputs are a list of strict `Outcome` records. The typed schemas live in
`scripts/evaluation/models.py`. Keep every field in the receipt, including unknown
usage and `source_snapshots_sha256: null` when no private snapshot index is needed.
Before execution, freeze source/candidate/baseline revisions, provider settings,
shared prompt, budget, evaluator implementation, protocol, inputs/labels hashes
and exact ordered case IDs. After execution, commit the exact output hash. The
replay rejects changed controls, duplicate attempts, unknown cases, source drift,
path escapes and corrupt ground truth.

The hash-frozen `experiment.json` names candidate/baseline revisions and separately
pins each system's provider settings and revision. Replay matches settings to that
arm rather than requiring different specialist providers to have identical
configurations. The shared prompt, input corpus, evaluator and resource allowance
remain identical across arms.

Run from the repository root:

```bash
uv run --locked python scripts/replay_capability_evaluation.py \
  --bundle tests/evaluation/fixtures \
  --outputs tests/evaluation/fixtures/outputs.json \
  --receipt /absolute/path/to/frozen-development-receipt.json \
  --output /absolute/path/to/development-report.json
uv run --locked pytest tests/evaluation/test_replay.py -q
```

For comparison, supply `--baseline-outputs` and `--baseline-receipt`. Both arms are
replayed from their original outputs and source commitments. Editable summary
reports are not accepted as baseline evidence. Shared input, label, prompt,
evaluator, protocol, experiment and budget commitments must match; per-arm
provider settings must match the same frozen experiment.

The replay makes no network call and launches no provider, installation, upload,
recording, device or publication action. Such runs need the concrete resource
plan and authority in `vrm-0e8.2.9`. The fixed human audit sample is the first
opaque ID in each family plus every disputed support judgment, with an explicit
reviewer, source/media identity, verdict and receipt before a comparative claim.
