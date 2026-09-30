---
name: plugin-maintenance
description: Audit and modernize this plugin's models, dependencies, skills, onboarding, or release workflow with verified sources and bounded repair cycles.
disable-model-invocation: true
---

# Plugin Maintenance

Use the current user mandate and checkout as authority. Installed plugin files
and a remembered model name are leads; the source tree, official provider
documentation and registry metadata determine what can change.

1. Read `AGENTS.md`, scoped instructions and the active tracker issue. Verify
   HEAD, dirty paths, remote and `scripts/detect_review_scope.py --json`. Preserve
   other work; isolate a new change when ownership requires it. Record the
   outcome, protected behavior, allowed writes and publication authority in the
   repository's tracker. If no tracker is configured, record that limitation.
2. Inventory runtime model IDs, dependency constraints and locks, installed file
   mappings, public tools and front-door docs. Verify newer stable releases and
   exact API contracts using primary provider docs and PyPI/npm metadata. Record
   URLs, inspection date and any deliberately retained supported API.
3. Choose one evidenced defect or upgrade. Implement the smallest complete
   correction with the affected tests and docs. Independent workers need disjoint
   write paths and a single integration owner; inherit the configured model.
   A newer model string is insufficient if its thinking, cache, response or
   session contract differs.
4. Run the affected check. Let fresh results select the next correction. Preserve
   failures and skipped checks in the evidence. After one controlled intervention
   repeats the same infrastructure failure, stop that path and record the gap.
   Continue independent authorized work. Stop when the accepted outcome is
   achieved, evidence shows no useful next action, access is missing, resources
   are exhausted, or the user stops the work.
5. Join required workers, then run the final gates once: locked tests and lint
   for all three Python packages; `node --test tests/installer.test.js`; security
   smoke and offline tool-security checks; `uv run python scripts/check_release.py`;
   Python builds and `npm pack --dry-run`. Re-run affected checks only after a new
   change or a concrete unresolved failure. Verify a built MCP artifact through
   tool discovery and a read-only configuration call before claiming packaging
   acceptance. Provider execution and generated-media quality need separate
   authorized evidence.
6. Record exact commits, checks, limitations and next eligible work in the tracker
   and an audit receipt. Commit explicit owned paths. Push, merge, registry upload
   and GitHub release creation only within the user's stated authority. Keep
   review slices single-purpose; distinguish a source release from a registry
   install and from a running provider-backed server.

For later runs, resume the issue and verify any active worker/job identity before
dispatching. One coordinator owns canonical writes. A scheduled prompt alone is
not self-improvement: promote a workflow change only after a recorded recurring
failure and a later independent check of protected capabilities. Use the host's
supported automation facility only when recurring continuation is authorized;
do not launch an unbounded paid loop from this skill.
