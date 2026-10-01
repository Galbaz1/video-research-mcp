# Multi-source editorial video plans

The companion MCP server independently implements `explainer_plan`. It reads an
existing project's evidence packet and originals, persists revisions in project
SQLite, and exposes create/show/revise/approve without a stdin session or provider.
The separate upstream CLI remains optional for generation. No upstream code is
copied/imported/bundled; its pinned full licence grant remains unresolved.

Configure `EXPLAINER_PROJECTS_PATH` for local planning. The project must exist and
contain `input/evidence-packet.json`, original source files, and exact source
hashes/passages. Use the existing EvidencePacket version-one contract. Storage
of an unsupported draft is distinct from approval and factual acceptance.

## MCP actions

For a packet with two original sources and two approved exact claims:

```json
{
  "project_id": "lamp-example",
  "request": {
    "action": "create",
    "expected_revision": 0,
    "plan": {
      "title": "Two observations",
      "audience": "Demonstration viewers",
      "thesis": "Present each original observation with its source.",
      "concept_order": ["first", "second"],
      "scenes": [
        {"title": "First lamp", "concept": "first",
         "purpose": "Show the first lamp and original source label.",
         "claim_ids": ["claim-a"], "duration_seconds": 10.0},
        {"title": "Second lamp", "concept": "second",
         "purpose": "Show the second lamp and original source label.",
         "claim_ids": ["claim-b"], "duration_seconds": 10.0}
      ],
      "sources": [
        {"source_id": "source-a", "disposition": "included", "reason": "First observation."},
        {"source_id": "source-b", "disposition": "included", "reason": "Second observation."}
      ],
      "duration_budget_seconds": 30.0
    }
  }
}
```

Every packet source must have exactly one disposition. A rejected source remains
visible with a reason; no used claim can reference it. Every included source must
support at least one planned scene. Concepts must be unique, covered and ordered;
scene allocations must fit the total finite duration budget. Unknown fields and
malformed plans fail before accepted state is persisted. Plans are bounded to
1 MiB; actual JSON input/output files to 8 MiB. Aggregate selected citation
references are bounded to 512 KiB before persistence; complete durable state is
bounded to 2 MiB. SQLite page capacity enforces the 8 MiB database envelope, so
large repeated metadata rejects atomically rather than making the plan unreopenable.

Review with `{"action":"show"}`. Approve with
`{"action":"approve","expected_revision":1}` after actual editorial approval.
Replace content with `{"action":"revise","expected_revision":1,"plan":...}`.
Revision two has no approval or artifact bindings. A stale expected revision
fails without overwriting state. Show uses the current persisted content, original
hash checks and actual artifact readback. Approval requires exact original claim
text, an included support source, no abstention and `editorial_approved: true`.
It reports `factual_success: false` and `semantic_support: "not_verified"`.

## Production admission and output evidence

Creating a managed plan refuses an existing unmanaged `plan/plan.json`; preserve
or explicitly remove that plan first. Managed SQLite content is authority.
`plan/plan.json` is its derived external CLI wire, published only on approved
production admission. Each planned scene carries all original claim IDs, text,
passage/source refs, source revisions/hashes and the source-as-data role in
`key_points`. The upstream's first-document analysis does not silently discard
the second source from this compiled plan. Prompt inclusion alone does not prove
model compliance; actual outputs must pass the checks below.

Managed `explainer_generate` invokes supported individual script, narration,
scenes, voiceover and storyboard commands. It avoids the upstream whole-generation
plan overwrite and its source-visible storyboard invocation defect. Ranges must
be ordered within those five stages. Render separately. `force` is passed only
to stages whose public CLI supports it; storyboard is regenerated for readback.
An unchanged legacy project uses the original whole-generation arguments.

`explainer_step` and script `explainer_refine` use the same admission checks.
Originals/claims must remain unchanged before and after dispatch. The actual
script title and ordered scene titles must match. Narration is exactly the
referenced claim texts joined by newlines; visual description equals approved
purpose. Scene durations must stay within their allocations and declared totals
must agree. A paraphrase, invented addition, silent dropped input or different
purpose fails even if the CLI exits zero. Failed JSON is retained without a new
accepted binding; no provider retry is triggered.

The optional CLI reads project `config.json`. Declare `paths.storyboard` as a
relative project JSON file, normally `storyboard/storyboard.json`. Absolute paths,
escapes, missing-key directory fallback and overwriting plan/script/original
inputs fail before dispatch. Configuration changes during dispatch fail readback.
Storyboard IDs/titles/order/timing must match the actual bound script and budget.
Its metadata names the exact parent script SHA256. Actual storyboard does not
contain narration/purpose text; that evidence derives from the checked script
parent. Visual rendering, spoken delivery and semantic faithfulness are separate
unverified dimensions.

Accepted files carry `video_research_plan`: revision, plan/source commitments,
scene/claim provenance and explicit editorial/semantic boundaries. Show returns
`bindings.script` and `bindings.storyboard` with paths, SHA256 and `current`.
Mutation, path reconfiguration, old revision or changed parent invalidates these
checks. Managed render admission requires both current bindings; the existing
durable render controller independently freezes inputs and checks actual output.

## Concurrency and recovery

Plan changes and managed generation/refinement/injection share one per-project
SQLite write transaction. Contention returns a clear busy error immediately;
approval cannot be revised while an admitted producer awaits its owned CLI.
CLI timeout/cancellation uses existing bounded process cleanup. SQLite survives
restart; incomplete transactions roll back rather than grant new approval.
Sources edited after approval appear stale and require revision/approval again.
Raw external filesystem editing is outside that transaction; before/after hashes
detect changes, while ordinary local filesystem access remains operator authority.
Source/artifact reads use nonblocking descriptors and check the actual opened file
is regular before reading, so a FIFO/device replacement cannot block the server.

Local/mock/installed contract journeys establish original accounting, CAS,
admission, bytes and revision binding. They establish no paid model success,
native rendering quality, human audit, comparative advantage or publication.
