---
date: 2026-09-30T09:16+02:00
thread: plugin-modernization-release
session_id: 01a0f119-eabd-7c13-a784-1db70d6dbc33
session_id_source: CODEX_THREAD_ID
topic: publication-followup-complete
domains: [runtime, documentation, distribution, release]
status: closed
---

# Handoff: video-research-mcp

The modernization, documentation rewrite, submodule repair, and all authorized registry publications are complete. Beads epic `vrm-jua` and its release follow-ups are closed. This is the single repository session handoff; Beads remains the tracker.

## Current source and authority

- User explicitly authorized continuation and full pushes in this fresh session. Both checkouts reported effective `no-git-ops: false`; no active developer Git prohibition was present. The older restriction in the preserved handoff is historical.
- GitHub main: `a3d75f6ab87bd893c7d167394fb5bace717f23ec`. Source repair: `7abc0c1599b926ed6e330dbf3ff3ed22152c1aa2`. The later commit adds one factual companion manifest comment to refresh the hosted graph; it does not change package behavior.
- Release tag `v0.7.1` stays at `7abc0c1`. Published history, tag identity, and package archives were not rewritten.
- Implementation checkout: `/Users/fausto_home/Coding/worktrees/video-research-mcp/modernization-2026-09`, branch `codex/main-publication-verification`. A handoff-only commit follows the validated source on that branch and is pushed separately; it is not a new runtime release.
- Original checkout remains branch `feat/local-video-windowing`, HEAD `bd980e834929c291ca3766180fb1a44d1f615efd`, with the two unrelated dirty documentation files preserved. All five files in `protected.json` retain their recorded hashes. Its canonical local handoff was updated separately.
- Source pushes used the repository's existing administrator bypass. The new local commits are unsigned; protection rules were not weakened. GitHub rejected the first unpublished commit for email privacy; only that unpublished commit was corrected to the account's no-reply email.

## Work completed

- Pinned `packages/video-explainer` to reachable upstream `c033e28d6eccae43c1762f4653f9c320b16b050e` and changed its clone URL to public HTTPS. A fresh recursive clone of published source succeeded.
- Aligned companion CLI selectors: `script` refinement, `720p`/`1080p`/`4k` render presets, and `mock`/`elevenlabs`/`edge` TTS providers. Refinement forwards its configured projects directory after the subcommand. Pipeline steps are unchanged.
- Made the three unconfigured project-tool tests explicitly supply an empty configuration, independent of a populated submodule checkout.
- Installed the pinned upstream CLI in its own ignored environment and verified general, refinement, rendering, voiceover, and pipeline help. No provider generation ran.
- Fresh local gates: core 801 tests, explainer 150, agent 51; all three Ruff checks passed. Installer 13 tests, security smoke 9, offline security checks 5, release contract, 34-tool discovery, and built-wheel secret redaction passed.
- Main CI run [36682488841](https://github.com/Galbaz1/video-research-mcp/actions/runs/36682488841) passed all 10 jobs at `a3d75f6`.
- Fresh Dependency Graph run [36682491335](https://github.com/Galbaz1/video-research-mcp/actions/runs/36682491335) passed at that exact source. Historical failed run 36673429069 remains preserved; GitHub would neither dispatch nor retry it.
- Hosted Dependabot run [36682117385](https://github.com/Galbaz1/video-research-mcp/actions/runs/36682117385) passed; its log identifies base commit `7abc0c1`. A fresh API read showed zero open Dependabot alerts. This is a point-in-time advisory result, not a general security guarantee.

## Publication and artifact verification

| Surface | Verified public version | Evidence |
| --- | --- | --- |
| GitHub latest | `v0.7.1`, not prerelease | Release run 36681773269 passed all 11 jobs; tag and seven downloaded asset hashes verified |
| npm latest | `video-research-mcp@0.7.1` | User approved passkey; registry archive exactly equals prepared tarball and integrity; isolated registry `--check` executes |
| PyPI core | `video-research-mcp==0.7.1` | Both immutable published asset hashes match earlier receipt; registry wheel exposes 34 tools and redacts secrets |
| PyPI explainer | `video-explainer-mcp==0.2.1` | Wheel/sdist equal rebuilt and GitHub assets; registry stdio exposes 15 tools |
| PyPI agent | `video-agent-mcp==0.2.1` | Wheel/sdist equal rebuilt and GitHub assets; registry stdio exposes 2 tools |

The GitHub core wheel is byte-identical to the existing PyPI wheel. The GitHub source archive contains the final CI/submodule/companion follow-up and release notes; the earlier PyPI source archive remains immutable. Local core sdist construction with the populated submodule also included upstream files; that local core sdist was not published. `github-asset-verification.json` records the exact differences.

The registry installer check reports the pre-existing user installation at 0.6.0 with 16 modified managed files. It proves the new registry installer executes; it does not claim the user's installed client was upgraded. No client restart or live provider inference is claimed.

## Decisions and remaining boundaries

- Keep exact source, hosted gates, registry bytes, and active client configuration as separate claims.
- Rebuilt companion archives replaced only unpublished preparation; no published version was overwritten.
- User created the companion upload credential in their own PyPI tab. It was saved privately in the existing credential file; the previous credential was preserved in a private backup. No token was printed or committed.
- Beads closures are local and durable. `bd dolt remote list` reported no configured remotes; no remote was created or unsupported synchronization claimed.
- There are no remaining release blockers or planned execution steps for this task. Future client upgrades, provider calls, and new releases are separate work.

## Hot files and receipts

- `.gitmodules`, `packages/video-explainer-mcp/`, `CHANGELOG.md` — published repair and CLI contract.
- `docs/PUBLISHING.md`, `docs/RELEASE_CHECKLIST.md` — future release procedure.
- Private evidence: `/Users/fausto_home/.local/state/writing-mastery/work/video-research-docs-2026-09-29/publication-followup-2026-09-30`.
- `source-artifact-receipt.json`, `github-release-receipt.json`, `github-asset-verification.json`, `npm-publication-receipt.json`, `companion-pypi-publication-receipt.json`, `companion-registry-runtime-receipt.json` — versions, hashes, comparisons, runtime discovery.
- `final-main-ci-jobs.json`, `dependency-graph-success.json`, `dependency-graph-success.log`, `dependabot-repair-verification.log`, `final-dependency-sbom.json` — hosted source verification.
- `pre-continuation-handoff.md` preserves the previous session state. Older receipts in the parent evidence directory remain historical; use this follow-up for final publication claims.
