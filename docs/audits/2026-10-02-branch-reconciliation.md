# Retained branch reconciliation

Authority: user-requested repository-wide reconciliation, Bead
`vrm-0e8.10.3.3`. The comparison starts from main
`cc63813004dfcaa76aeee2e92db985708733388b`, delivered by PR #76. Its complete tree
matches the qualified programme source `f255d0083f059bf855ad55095c9874f50580dba0`.
This audit distinguishes retained history from missing product behavior.

## Delivered and superseded work

| Retained source | Evidence and disposition |
| --- | --- |
| Programme and plugin-upgrade branches | Their source lineage is included in the qualified programme tree, which equals delivered main. Retained branch names do not imply missing implementation. |
| Documentation release `7ee8c34` and advanced README `b1646ca` | `git cherry` identifies equivalent patches in the delivered programme. No additional source merge is required. |
| Older default-model branch `491e6af` / PR #65 | Its default is superseded by current configuration. Restore no older defaults. Close the obsolete PR with the configuration and test evidence. |
| Local windowing `e326fde` and upload recovery `bd980e8` / PR #63 | Bead `vrm-0e8.3.1` accepted the useful behavior in `6dcf3444e68823f7b075001d6717d875043f2ed4`, included in main. Current normalized FPS/start/end metadata, static processing, window-specific cache identity and source timestamps replace the older implementation. Retained upload identities are checkpointed before waiting; recovery uses the same resource under the current execution budget. Close the older PR as superseded. |
| Interactions experiment `0004342` | [Protected-contract evaluation](../integrations/INTERACTIONS_EVALUATION.md) explicitly rejects a wholesale merge. The frozen experiment loses typed media/tool/history parts, cache behavior and unsuccessful-turn state. Compatible JSON/static-window/native-ID mechanisms remain references; they require a concrete caller and complete recovery before production adoption. Preserve the reference and counterexamples. |

The retained lineage includes `codex/main-publication-verification`,
`codex/multimodal-capability-programme`, `codex/multimodal-signed-integration`,
`codex/oss-video-landscape`, `codex/plugin-modernization-2026-09` and
`codex/plugin-upgrade-{1-core,2-companions,3-media,4-workflows,5-onboarding}`.
Their exact heads are recorded in the verified backup inventory. The separate
`codex/documentation-release-0.7.1`, `codex/readme-advanced-entry`,
`codex/gemini-3-6-flash`, `codex/gemini-3-8-interactions` and
`feat/local-video-windowing` references have the dispositions above. The two
remote-only review branches have the security disposition below. Local `main`
was fast-forwarded from its stale ancestor to the verified remote main without
switching any existing checkout. `codex/branch-reconciliation` owns this audit.

The windowing outcome does not promise observed frame coverage, successful live
File API processing, a fixed 600-second wait, or provider-managed session parity.
Those remain separate from tested source behavior and operation budgets.

## Historical security branches

The independent Herdr review accounted for all **23 unique production-changing
commits** in `codex/review-mainline` (`3d96606`) and `codex/review/i07`
(`0e824b7`): the original review classified 11 as covered, six as superseded
and six as containing missing proposals at the comparison source. The focused
follow-up corrected the security interpretation of the two fail-fast directory
proposals: only the traversal visit ceiling is a security control. No commit
classification was uncertain.
The reviewer reproduced the gaps with 15 offline probes. Passing probes in that
original review establish the defects, rather than proving that main was safe.

The corrective slice repairs F1–F4:

- F1: fence batch discovery and compare reads. Reject parent/absolute glob
  traversal and matching symlinks outside the configured file root before
  inference or job submission.
- F2: read regular files through the existing descriptor checks, enforce the
  configured byte ceiling and reject changed or growing content.
- F3: enforce an aggregate comparison byte budget before reading, then retain
  that budget through the actual reads.
- F4: bound actual directory-entry visits, including nonmatches and revisits,
  to 5,000. Preserve the published `max_files` subset behavior for directory and
  explicit batches; historical fail-fast UX proposals are not adopted.

The optional F5 direct-text cap is **not adopted**. It narrows two frozen
published input schemas, and the public-baseline gate rejected that candidate.
The schemas and accepted direct-text behavior are preserved; no gate requirement
was relaxed. This proposal is retained as a rejected reference rather than pending
branch implementation.

The implementation uses the existing `DOC_MAX_DOWNLOAD_BYTES` ceiling for local
files and total compare bytes (50 MiB by default). It does not restore the
historical separate 100 MiB compare knob, additional concurrency knobs or old
prompt framing: current operator configuration and system instructions retain
those responsibilities. Discovery supports ordinary, nested and recursive globs, including a terminal
`**`. Directory-only patterns select no files. It does not follow directory
symlinks. Recursive revisits count toward the ceiling, so the unique-entry
capacity is lower for recursive patterns.

An adjacent regression (I1) was also reproduced: URL research documents downloaded
under a symlinked macOS temporary path or outside the local fence could not be
prepared. Downloads now use the existing private fenced view directory; completed
preparation removes the staging directory. Existing SSRF policy and upload
snapshot checks still apply. The architecture wording now reflects that URL
downloads reject a missing peer address. Bounded document/phase concurrency has
new execution checks; no new provider or model migration is introduced.

Enforcement: [batch discovery](../../src/video_research_mcp/batch_discovery.py),
[content reads](../../src/video_research_mcp/content_file_data.py),
[content comparison](../../src/video_research_mcp/tools/content_batch.py),
[video discovery](../../src/video_research_mcp/tools/video_batch.py) and
[document staging](../../src/video_research_mcp/tools/research_document_file.py).
The [regression tests](../../tests/test_branch_reconciliation.py) check fence
escapes, special files, byte ceilings, aggregate budgets, nonmatch traversal,
glob selection, bounded subsets, published MCP text compatibility, fenced URL
preparation and concurrency. See [operational limits](../integrations/LOCAL_CONTENT_BOUNDS.md).

| Original commit | Intended change | Reconciliation |
| --- | --- | --- |
| `10ab053` | security(review-cycle): enforce URL policy in content_analyze (iteration 1) | Covered |
| `12a5945` | security(review-cycle): iteration 2 validation and boundary hardening | Covered |
| `009e918` | Iteration 3: external API failure-mode + idempotency hardening | Covered |
| `86abe58` | Iteration 4: infra auth gating and secret redaction hardening | Covered |
| `d4de0cf` | security(review-cycle): iteration 5 cache integrity hardening | Covered |
| `25dc6c3` | fix(review-cycle): surface document preparation failures in research outputs | Covered |
| `9f36236` | security(review-cycle): harden redirect and list validation contracts (iteration 2) | Superseded |
| `c5a5a2b` | feat(security): harden knowledge summarization prompt boundaries | Superseded |
| `bd17909` | fix(security): harden prompt boundaries and bound doc fan-out | Superseded |
| `2b10bda` | security: bound research_document phase fan-out | Covered |
| `08b8502` | security(review-cycle): make document concurrency caps configurable | Superseded |
| `c6ed9b2` | security(iteration-8): cap local content payload sizes | Repaired in this slice (F1, F2) |
| `229fc28` | security(iteration-8): cap compare payload and harden content prompt boundaries | Repaired in this slice (F3) |
| `a6c218f` | security(iteration-8): clean temporary document artifacts and record learning loop | Covered |
| `c2abb61` | security(iteration-8): cap research_document source cardinality | Covered |
| `842e85b` | security(iteration-8): tune batch fanout and harden extract prompt boundaries | Superseded |
| `ea604f0` | fix(iteration-8): resolve merge conflicts for batch guardrails | Superseded |
| `7cfb134` | security(iteration-8): align doc download ceiling and harden research prompts | Covered |
| `1e90f3c` | security(iteration-8): cap direct text payload ingress | Rejected optional schema narrowing (F5); frozen contract retained |
| `04d70df` | security(iteration-8): fail fast on oversized explicit batch paths | Covered |
| `12478d0` | security(iteration-8): fail fast on oversized content directory scans | Fail-fast UX not adopted; bounded published subset behavior retained |
| `197aac7` | security(iteration-8): fail fast on oversized video batch discovery | Fail-fast UX not adopted; bounded published subset behavior retained |
| `762de5b` | security(iteration-8): bound batch directory scan traversal | Repaired in this slice (F4) |

## Protected historical documentation

The original checkout retains two protected historical files:
`docs/metrics/installer-state-matrix.json` and `docs/update-plugin.md`. Their
working changes consist of nested conflict markers and a generation timestamp
discrepancy, rather than new runtime behavior. The exact bytes are protected by
[the published baseline](../metrics/public-baseline.json) and preserved in a
private backup. This reconciliation leaves that frozen baseline intact.

Main contains a valid installer-state JSON document and the current
[upgrade guide](../update-plugin.md). The old combined planning/UX document is a
historical record; it does not replace the current upgrade instructions. Original
configuration, the protected checkout, installed plugin files and immutable
release artifacts retain their independent identities.

## Verification and preservation

Fresh focused gate on the comparison source:

```sh
uv run --locked --offline pytest tests/test_interactions_compatibility.py \
  tests/test_video_window_metadata.py tests/test_video_upload.py \
  tests/test_video_core.py tests/test_video_file.py tests/test_config.py -q
```

Result: **143 passed**, one existing SDK deprecation warning. No live provider
inference or upload was used. Main CI run `37031949273` passed all ten jobs before
this reconciliation. The corrective candidate passed **129 affected tests**,
including 24 new checks, and the declared Ruff gate. After restoring the frozen
text schemas, **41 affected checks** passed again and the public-baseline gate
passed with no changes to its criteria. After the measured glob/subset refinements,
**77 affected checks** and Ruff passed, including all **26 final new checks**.
The original truncation tests are unchanged from main. Initial test collection/import and error-assertion
failures were repaired and retained in the private receipt. The source reuse
ledger validates 85 units and three unchanged dependency locks. Exact-head CI
and protected delivery qualify this source separately from the earlier main run.
The final independent review accepts the bounded corrective patch with no
blocking findings: all 26 new checks and ten final delta probes passed. Its prior
focused pass retained 17 additional probes, including descriptor-budget and
failure-cleanup checks. The reviewer is terminal with zero children.

Residual source limits are explicit: directory symlinks are skipped under recursive
patterns and rejected when traversed by a named/wildcard segment; file aliases
use the resolved target name. As in the existing media read contract, final-file
symlink checks do not prevent a parent-directory swap during the open race.
This bounded review does not qualify every filesystem threat or live provider.

Before reconciliation, all retained local and remote-tracking history was saved
in a verified complete-history Git bundle. SHA256:
`f3b83356695e55bf930254887ebcd72948bf8f8e4df9932041567ea9e90f13ca`.
A fresh bare restore verifies all 65 actual references, the four listed
pseudoref objects and full Git integrity. Worktree layout is preserved in the
original checkouts. The two dirty documentation snapshots and canonical handoff
were preserved separately. Removing stale remote-tracking refs does not delete remote branches
or original local branch history.

Source reconciliation does not close programme product acceptance, the pending
human development audit, held-out comparisons or final release acceptance.
