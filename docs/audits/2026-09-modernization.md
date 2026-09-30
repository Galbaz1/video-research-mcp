# Plugin modernization audit — 2026-09-29

## Outcome and authority

The modernization run completed source acceptance and published a GitHub
prerelease for **0.7.0** at
`96f11b8c7d70a1bc4d73bfa500482f9811e4141f`. Core, installer and plugin versions
were 0.7.0; both companion packages were 0.2.0. The
[release](https://github.com/Galbaz1/video-research-mcp/releases/tag/v0.7.0),
[release gate](https://github.com/Galbaz1/video-research-mcp/actions/runs/36633416864)
and [hosted CI](https://github.com/Galbaz1/video-research-mcp/actions/runs/36633275514)
identify that result. This audit records the run's evidence; it does not certify
subsequent source changes, registry versions or an installed MCP server.

The authorized program covered supported models, stable dependencies, public
workflows, onboarding and release verification. It required complete tool
results, explicit cache behavior, typed errors, preservation of user configuration
and files, bounded worker ownership, and artifact acceptance. Authorization
included commits, pushes and GitHub artifacts. Registry uploads and PR merging
were separate actions; this run performed neither and made no paid provider
requests.

The baseline was `origin/main` at
`7b85c663a1e391dcb788de59bfff762c22e6d466`. The isolated modernization checkout
preserved existing local edits, the original `bd980e8` checkout, PR #63 and the
older partial Gemini migration. Local Beads epic `vrm-2g8` held the program state.
Three implementation lanes and one independent reviewer completed their work
before acceptance. Six focused PRs, #67–#72, were open and their branches pushed
at the recorded close of the run. The release was marked prerelease because its
tagged source was outside main.

## Verified decisions

The decisions below reflect the source and provider documentation inspected on
September 29, 2026. They are dated maintenance choices rather than permanent
provider inventories.

- Research and summary defaults were set to `gemini-3.8-flash`. Supported thinking
  levels were low, medium and high; unsupported minimal and explicit sampling
  overrides fail before provider work. Best/stable/budget presets used the
  inspected model IDs. See the
  [model specification](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)
  and [migration guidance](https://ai.google.dev/gemini-api/docs/latest-model).
- Explicit context caching remained on supported generateContent. The inspected
  Interactions API supported implicit caching, so moving every call would lose
  the existing explicit-cache contract. Deep Research used interaction
  steps, `output_text`, errors and the documented April agent. See
  [caching](https://ai.google.dev/gemini-api/docs/caching),
  [Interactions](https://ai.google.dev/gemini-api/docs/interactions-overview) and
  [Deep Research versions](https://ai.google.dev/gemini-api/docs/deep-research#supported-versions).
- Direct, build and development dependencies were checked against primary PyPI
  metadata and resolved in three exact locks. API-major bounds replaced
  open-ended constraints. The
  [dependency inventory](2026-09-dependency-sources.json) records package versions,
  Python support and source URLs.
- The resolved stable versions included FastMCP 4.0.10, Google GenAI 2.25.0,
  Weaviate client 4.23.1, Weaviate agents 1.8.0, Claude Agent SDK 0.2.162,
  Pydantic 2.13.5, pytest 9.1.1, pytest-asyncio 1.4.0 and Ruff 0.16.9.
  Installer Playwright MCP was 0.0.83, and CI used maintained Node 24 and the
  inspected action releases. Ruff's E4/E7/E9/F rules were made explicit because
  its new release broadened the defaults.
- Four transitive resolutions retained upstream bounds: grpcio 1.78.0 and
  protobuf 6.33.6 satisfied Weaviate's `<1.80` and `<7` requirements;
  pydantic-core 2.46.5 was Pydantic's exact dependency; websockets 16.1.1
  satisfied GenAI's `<17` bound. Forcing the registry's newest versions would
  violate those contracts.
- The agent wrapper used the inspected configurable Sonnet ID and disabled
  model tools, inherited MCP/workspace settings and shared environment mutation.
  Typed terminal errors, missing terminal results and exhausted turn limits
  fail. Limits bound turns, time and concurrency, not monetary spend. See
  [Claude models](https://platform.claude.com/docs/en/models/overview) and the
  [SDK reference](https://code.claude.com/docs/en/agent-sdk/python).
- Global MCP registration used Claude user scope in `~/.claude.json`; project
  registration used `.mcp.json`. Upgrades preserved custom environment/settings,
  local companion launchers, unowned files and edited or obsolete managed files.
  Corrupt, noncanonical, escaping, symlinked and hashless manifest paths fail
  safely. See [Claude MCP scopes](https://code.claude.com/docs/en/mcp).
- Media skills removed unsupported bundled-tool claims and personal helper paths.
  Active Sora instructions were removed after the documented September 24
  retirement. Omni/Veo/image/TTS capabilities were dated and sourced in the
  skills; the external explainer checkout remained authoritative for its own
  installed providers. See
  [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations),
  [Veo](https://ai.google.dev/gemini-api/docs/veo),
  [Gemini images](https://ai.google.dev/gemini-api/docs/image-generation) and
  [ElevenLabs models](https://elevenlabs.io/docs/overview/models).
- Public guidance used 34 root tools and 15/2 companion tools, optional companion
  installs, portable MCP access, and separate source, registry and runtime
  acceptance claims. Conflict-marker documentation was replaced. Orchestration
  inherited the configured model.

## Material review findings and corrections

The independent reviewer reproduced three P2 defects with offline scratch data.
The run corrected all three and verified each affected behavior:

| Finding | Correction | Focused evidence |
| --- | --- | --- |
| Consecutive final model-output steps lost earlier report text | Use SDK `output_text`; preserve the full report through status, follow-up and storage | 38 focused checks passed |
| Same-project concurrent renders could share one artifact | Admit only one render per resolved project before the first await; release the guard in `finally` | 31 focused checks covering blocking/background pairings, aliases, cancellation and independent projects |
| Manifest checks accepted dot traversal and symlinked ancestors | Validate canonical components, ancestors and ownership hashes during planning, install and uninstall | 13 actual installer journeys passed in scratch homes |

The run also verified complete SDK content and binary thought signatures across
SQLite session round-trips, serialized Deep Research launch admission with
queued/running states, and fresh nonempty render artifacts. Shutdown joined
owned tasks and reaped CLI subprocesses. Injection paths remained within project
inputs, and visualization workers preserved user files and processes.

## Local verification

These are the local results recorded by the modernization run, before the final
hosted receipt below. They are not new tests performed for this prose rewrite.

| Gate | Recorded evidence |
| --- | --- |
| Core, Python 3.14.7 | 801 passed after report-parser repair |
| Minimum Python 3.11.15 | 799 full-suite tests before that repair; 38 affected checks after it |
| Explainer suite | 129 passed after render-overlap repair |
| Agent suite | 51 passed |
| Lint and whitespace | All package Ruff checks and whitespace check passed |
| Installer execution | 13 journeys passed, including upgrade, uninstall, user edits and containment |
| Security | 9 smoke tests and 5 direct offline tool checks; 0 failures |
| Advisory scan | 103 resolved core all-extras dependencies; 0 known vulnerabilities reported |
| Metadata/contracts | Three core versions matched; 44 shipped mappings; 34 root tools and 15/2 companion tools |
| Skills/docs | 37 frontmatter files parsed; no pinned orchestration model; local links valid; invalid core-tool claims removed |
| Build artifacts | Three wheels and three source distributions built; all six passed twine checks; npm archive built |
| Installed core wheel | Stdio handshake, discovery of 34 tools and read-only configuration confirmed packaged defaults |
| Workflows/cloud scripts | actionlint and shell syntax checks passed |

Reproduction commands follow. Run companion tests and lint in the respective
package directory; the counts above belong to the recorded revision.

```bash
uv sync --locked --extra dev
uv run --locked pytest tests/ -q
uv run --locked ruff check src/ tests/
node --test tests/installer.test.js
./scripts/run_security_smoke.sh
PYTHONPATH=src uv run --locked python scripts/run_live_tool_security_checks.py
uv run --locked python scripts/check_release.py
uv build
uv build --project packages/video-explainer-mcp --out-dir "$PWD/dist"
uv build --project packages/video-agent-mcp --out-dir "$PWD/dist"
uvx --from twine twine check dist/*.whl dist/*.tar.gz
uv run --locked python scripts/smoke_built_mcp.py dist/video_research_mcp-*.whl
npm pack --dry-run
```

## GitHub publication receipt — 2026-09-29

The recorded release gate completed successfully for the final tagged commit.
[Preserved run metadata and job-log excerpts](2026-09-hosted-verification.json)
identify the tested commit and provide the hosted counts below.

Hosted CI passed 801 core tests on Python 3.11, 3.12, 3.13 and 3.14, 129 explainer
tests and 51 agent tests on 3.11/3.14, 13 installer journeys, nine security tests
and five direct offline tool checks. Lint, contracts, builds and the installed
wheel's MCP handshake/defaults also passed.

All seven downloaded release assets matched GitHub's SHA-256 digests. The
verification compared 122 wheel Python files and 50 npm source files with the
exact tagged Git blobs. This binds the inspected artifacts to the accepted
source; it does not establish registry installation or provider behavior.

The first hosted CI attempt failed because setup-uv v10.2.0 had no `v10` alias.
One controlled change to the actual action tag restored the required gates.
Hosted AI review remained incomplete: Codex encountered an account limit, an
earlier Claude run ended in a terminal error, and the final Claude action skipped
workflow-content validation. Software acceptance and the independent review
completed; no hosted AI-review approval is claimed.

The GitHub alert comparison found 67 open alerts against unchanged main at
`7b85c66`: three critical, 27 high, 25 medium and 12 low. No vulnerable range in
that comparison matched any upgraded lock. All three locks were unchanged from
`6560492` through the final `96f11b8`. This explains why open baseline alerts and
the upgraded environment's zero-known-vulnerability scan could coexist. Advisory
coverage and platform markers still limit both conclusions.

## Continuation and limits

The [maintenance skill](../../skills/plugin-maintenance/SKILL.md) defines fresh
observation, one bounded correction, verification, checkpointing and stop states.
Beads owns program status. A continuation needs the exact issue, checkout,
revision, job and last receipt; completed work in this audit does not substitute
for acceptance of a later change. Weekly dependency coverage includes both
companions, and CI/release gates verify locks and artifacts.

The run did not validate Gemini/Claude account entitlement, real inference
quality, generated-media quality or the upstream video_explainer pipeline.
Render admission and job state were local to one server process. SDK deprecation
warnings and the future gRPC minimum remained visible; upstream constraints
prevented the newer gRPC version. The advisory audit was bounded, not proof that
upstream code had no defects. Publication did not change user-installed
configuration, and this receipt makes no current claim about PyPI/npm releases.

The maintenance run reached its accepted terminal result. Later documentation,
security fixes, source integration, registry publication or provider acceptance
need evidence tied to their own revision and scope. The described workflow does
not prove uninterrupted unattended operation or transfer of an improved harness.
