# Refinement and revision-bound feedback

`explainer_refinement` (video-explainer-mcp, `tools/refinement.py`) probes which refine
phases the configured explainer CLI actually supports and keeps a durable feedback
lifecycle bound to managed plan revisions. The existing `explainer_refine` and
`explainer_feedback` CLI wrappers are unchanged.

The upstream refinement modules' licence is unresolved; nothing from them is copied or
imported. This is an independent implementation over the package's own plan machinery.

## Capability probe

`action: capabilities` runs only `refine --help` through the existing bounded `run_cli`
and parses the argparse choices of `--phase`. The result records the command, exit code,
help SHA256, the parsed phases and the flags present in the help text:

- `probed`: phases were listed; only those phases can be requested.
- `unparsed`: help had no `--phase {…}` choices; no phase is supported.
- `unavailable`: the CLI could not be run; no phase is supported.

A `cli_phase` request is checked against a fresh probe at `add` and again at
`apply`/`retry`, before any refine call and before a round is consumed. Flags such as
`--projects-dir` are passed only when the probe saw them.

## Feedback lifecycle

Feedback rows are stored in the project's existing `planning.sqlite3`, in table
`refinement_feedback`, and written inside the same fail-fast plan transaction as plan
revisions. A managed plan (`explainer_plan`) is required.

- `add` (needs `expected_revision` equal to the current plan revision) records the
  target: plan revision and SHA256, approval revision, scene index and scene digest, the
  SHA256 of every bound artifact, and for visual feedback the exact render bytes and frame
  time. Findings are stored as asserted (`observed_by` caller, model or fixture;
  `verified: false`).
- `show` lists all feedback or one item.
- `apply` processes one round. If the plan moved since `add`, the round is recorded as
  `stale_target` and nothing is changed.
- `retry` (failed or stale feedback only; needs the current `expected_revision`) rebinds
  the target to the current revision, keeps the previous target in `rebinds`, and
  processes one more round.

Every round is appended to `attempts` with its processor and result, including failures.
`max_rounds` (1–5, default 3) caps the rounds; once reached, the request is refused before
any processing.

## Processors

- `local_patch`: a typed edit of one scene field (`title`, `purpose`, `duration_seconds`)
  guarded by its `expected` current value. It refuses if the original sources or claims
  changed. The revised plan passes the existing plan validation and is saved as the next
  draft revision: approval and artifact bindings are cleared, as for any plan revision.
  The result lists the affected scene (recheck with before/after digests), the unaffected
  scenes, the bindings to rebind, and the unchanged source commitment.
- `cli_phase`: runs only a probed phase. Only `script` has a managed artifact binding, so
  it runs through the existing approved-plan producer (`produce`); other phases are
  refused before spend. The record keeps the command, exit code, stdout SHA256 and changed
  bindings; `refinement_quality` stays `UNKNOWN`, because a CLI exit is not a quality
  judgment.

## Visual review

Visual feedback must reference `render_path` inside the project, its `render_sha256`, a
`time_ms` and optionally a `frame_index`, plus at least one `legibility`, `composition`
or `incorrect_visual` finding. The tool hashes the current render bytes and refuses a
mismatch, so no finding binds to output that is not there. It does not decode, watch or
judge the render: results carry `watched_by_tool: false`, and whether the frame time lies
within the render duration is reported as `UNKNOWN`.

## Wiring

The companion source server mounts `refinement_server`. Feedback becomes stale when
its plan, approval, artifact bindings or referenced render changes, including artifact
replacement without a new plan revision. Cancellation records a counted unknown
processing outcome before propagating. If SQLite cannot persist that record, cancellation
still propagates with a persistence liability; the durable round count is then unknown.
Installed CLI effects, output quality and native cleanup require separate qualification.
