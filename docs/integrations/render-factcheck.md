# Render fact-check

`explainer_render_factcheck` (video-explainer-mcp, `tools/render_factcheck.py`) checks an
existing project's evidence packet and reconciles what a render actually shows and says
against the approved claims. It is a deterministic, local check: no model, OCR, ASR,
renderer, provider or network call runs inside it.

The existing `explainer_factcheck` tool is unchanged. It delegates to the separately
installed explainer CLI and returns its stdout; a successful CLI exit is not a factual
result. The upstream checker's licence is unresolved, so nothing from it is copied or
imported here.

## Inputs

- `project_id`: a configured project containing `input/evidence-packet.json` (the
  version-one packet validated by `evidence.validate_evidence_packet`).
- `request.judgments`: optional asserted verdicts per claim (`supported`, `false`,
  `unsupported`) with `method` (`fixture_literal`, `author_review`, `model_judgment`),
  `judge`, and `correction_refs` (packet passages whose exact quotes correct the claim).
- `request.observations`: already-recovered rendered text per channel (`caption`,
  `overlay_text`, `voiceover_asr`, `frame_ocr`) with its `method`, optional interval and
  the renderer-declared `claim_ids`.
- `request.render`: optional receipt (`output_path` inside the project, `expected_sha256`,
  `status`).
- `request.sync_tolerance_ms`: start-time tolerance for synchronization (default 500).

## Verified support versus asserted judgment

Each claim reports both, separately:

- `verified_support`: `exact_source_text` only when every reference resolves to an
  integrity-checked original passage whose quote equals the claim text. Otherwise
  `no_exact_source_text`, `source_unavailable` (a referenced source failed to load or
  verify) or `abstained`.
- `judgment`: the asserted verdict, method and judge, always `verified: false`. Its
  corrections are resolved to exact original quotes; the verdict itself is not certified.
- `factual_status`: `supported` (method `deterministic_exact_quote`), `false` (an asserted
  `false` with verified correction quotes that differ from the claim), `unsupported`, or
  `unknown` (source unavailable or abstained). An asserted `supported` without exact
  support is never promoted; a conflicting assertion is listed in `judgment.issues`.

All of this is labelled `evidence_scope: deterministic_literal_fixture_evidence` and
`semantic_support: not_verified`. It is exact-text evidence, not general factual truth.

## Rendered additions

Every observation is matched independently of its declared claim IDs. The text is
normalized (casefold, punctuation and spacing dropped) and covered greedily by literal
claim token sequences. Uncovered runs are `additions`. Matched claims that are not
editorially approved and supported are `unapproved_claim_ids`; matches to claims judged
false are `false_claim_ids`. An observation is `reconciled` only when it has no addition,
no unapproved claim and its declared IDs equal the observed ones. ASR/OCR misreads show
as unreconciled text; they are never treated as a pass.

## Quality dimensions

`quality` keeps five dimensions apart, each with `status` (`pass`, `fail`, `UNKNOWN`),
`basis`, `reasons` and `details`:

| Dimension | Pass requires | UNKNOWN when |
|---|---|---|
| `factual_support` | claims present, no source/lineage error, every observation reconciled | no observation supplied |
| `narration_clarity` | never decided here | always (needs a listener or calibrated judgment) |
| `legibility` | every frame OCR observation recovers claim text exactly (a proxy, not human legibility) | no frame OCR observation |
| `synchronization` | same-claim voiceover/visual starts within tolerance | no claim observed with intervals in both |
| `render_completion` | receipt `completed` and current output bytes match its SHA256 | no receipt |

`factual_pass` mirrors `factual_support == pass` only. An empty claim set, a source load
failure or any unreconciled addition fails; no observations is `UNKNOWN`.

## Errors

A missing project, missing or invalid packet, or judgments naming unknown or duplicate
claim IDs return the package's structured tool error (`error`, `category`, `hint`,
`retryable`) and no factual result.

## Wiring

The companion source server mounts `render_factcheck_server`. Its installed public
journey still requires qualification. Literal reconciliation preserves numeric signs,
leading decimals and arithmetic/comparison operators, including standalone variable
subtraction. Hyphens also remain distinct from ASR spaces: the literal check cannot
determine whether a join is a word compound or subtraction. An unchanged compound
can pass; a changed join remains unsupported and needs review. This conservative
comparison remains a literal heuristic rather than semantic verification.
