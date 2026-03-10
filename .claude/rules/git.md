---
paths: "**/*"
---

# Git — Project Overrides

Extends `~/.claude/rules/git.md`. Project-specific rules take precedence.

## Branch Protection

`main` is protected. Direct pushes are blocked; all changes go through PRs.

**Ruleset name**: "Protect main"
**Owner bypass**: Galbaz1 has `bypass_mode: always` — full admin rights on all rules.

### Required Status Checks

A PR must pass all four checks before merge:

| Check | Description |
|-------|-------------|
| `lint` | ruff linter |
| `test (3.11)` | pytest on Python 3.11 |
| `test (3.12)` | pytest on Python 3.12 |
| `test (3.13)` | pytest on Python 3.13 |

Required signatures are also enforced on `main`, which is why `--admin` is always
needed to merge (it bypasses the signature requirement for squash merges).

### CI Workflows

Two Claude workflows exist — they behave differently:

| Workflow | File | Trigger | Expected on normal PRs |
|----------|------|---------|----------------------|
| `claude-review` | `claude-code-review.yml` | PR events (automated) | PASS or FAIL |
| `claude` | `claude.yml` | `@claude` mentions only (interactive) | **SKIPPED** |

`claude` showing **SKIPPED** is normal and expected for every PR that does not
mention `@claude`. It is NOT an error; do not treat it as a blocking failure.

### Merging PRs

Use `--squash --admin` unconditionally. The `--admin` flag bypasses required
signatures and any pending checks — this is intentional given owner privileges.

```bash
gh pr merge <N> --squash --admin
```

If the PR branch is out of date AND the update would cause a conflict, resolve it
locally on the PR branch and force-push before merging:

```bash
gh pr update-branch <N>          # fast-path: no conflict
# or, if conflict:
gh pr checkout <N>
git fetch origin main && git merge origin/main
# resolve conflicts, then:
git push origin HEAD:<branch> --force
gh pr merge <N> --squash --admin
```

## Preferred Merge Strategy

Always `--squash` for feature PRs. Dependabot and chore PRs: `--squash` as well.
