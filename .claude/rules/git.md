---
paths: "**/*"
---

# Git — Project Overrides

Extends `~/.claude/rules/git.md`. Current user authority takes precedence.

## Branch Protection and Release Merges

The remote layout is `main` and `dev`. Release changes reach `main` through a
reviewed PR from `dev`, using the normal protected merge flow.

The live `main` rules checked on 6 October 2026 require a PR, signed commits,
an up-to-date branch, `lint`, and `test (3.11)`, `test (3.12)`, `test (3.13)`.
They also prohibit branch deletion and non-fast-forward updates. The CI workflow
additionally runs Python 3.14, companion-package, and release-contract checks;
verify the candidate's complete CI results before a release merge.

Use an allowed merge method that satisfies signature and protection requirements.
Confirm required checks and applicable review requirements on the current PR
revision. If a signature or check blocks the merge, resolve it through the normal
signed-commit and PR process. User authorization for release merges does not
permit admin bypass, weaker protections, force rewriting, or skipped hooks.
Resolve conflicts with ordinary commits on `dev`; preserve other contributors'
work and update the remote through a normal fast-forward push when authorized.

## Claude Workflows and Account Routing

| Job | Source | Current trigger and condition |
| --- | --- | --- |
| `claude-review` | `.github/workflows/claude-code-review.yml` | PR opened, synchronized, ready-for-review, or reopened; skips same-repository `dev` and `codex/docling-ingestion-entry` heads |
| `claude` | `.github/workflows/claude.yml` | An `@claude` mention from an owner, member, or collaborator on a supported issue/comment/review event |

The same-repository `dev` review skip is intentional during the Codex account-2
routing override. Its `SKIPPED` status does not indicate a failed review or a
completed independent review. Fork PRs and other heads remain eligible under the
workflow expression. The interactive workflow has a separate mention gate; it
is not globally disabled by the review-job condition.

Do not create a Claude invocation while account-2-only routing is active. Root
collects independent Codex account-2 review evidence and owns integration. Read
workflow conditions and actual check results; do not infer review acceptance from
a skipped job or alter workflows to bypass a release gate.
