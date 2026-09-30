# Plugin modernization audit — 2026-09-29

## Outcome and authority

The authorized program updates supported models, current stable libraries,
public workflows, onboarding and release verification. The protected criteria
are complete tool results, explicit cache behavior, typed errors, preserved
user configuration/files, bounded worker ownership and artifact acceptance.
Publication authority covers commits, pushes and GitHub artifacts; npm/PyPI
upload and PR merging are separate actions. No paid provider requests were made.

Baseline: `origin/main` at `7b85c663a1e391dcb788de59bfff762c22e6d466`.
The modernization checkout is isolated from existing local edits, PR #63 and the
older partial Gemini migration. Tracker: local Beads epic `vrm-2g8`. Three
independent implementation lanes and one independent reviewer were joined.

Release target: core/installer/plugin `0.7.0`; companion packages `0.2.0`.
The GitHub tag identifies the final source; its gated Release workflow establishes
remote publication. A tag outside main is a prerelease. This receipt records
local acceptance, not a claim that registry latest or an installed server changed.

## Verified decisions

- Stable research and summary defaults are `gemini-3.8-flash`. Current supported
  thinking levels are low/medium/high; unsupported minimal and explicit sampling
  overrides fail before provider work. Best/stable/budget presets use verified
  model IDs. [Model specification](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash),
  [migration guidance](https://ai.google.dev/gemini-api/docs/latest-model).
- Explicit context caches continue on supported generateContent. Interactions
  currently supports implicit caching; converting all calls would discard the
  existing explicit-cache contract. Deep Research instead uses current interaction
  steps/output_text/errors and the documented April agent.
  [Caching](https://ai.google.dev/gemini-api/docs/caching),
  [Interactions overview](https://ai.google.dev/gemini-api/docs/interactions-overview),
  [Deep Research versions](https://ai.google.dev/gemini-api/docs/deep-research#supported-versions).
- Current stable direct dependencies were queried from primary PyPI metadata and
  resolved in three exact locks. Major bounds replace open-ended constraints.
  [Dated dependency inventory](2026-09-dependency-sources.json) records every
  direct/build/dev package's version, Python support and source URL.
- Resolved latest versions include FastMCP 4.0.10, Google GenAI 2.25.0,
  Weaviate client 4.23.1/agents1.8.0, Claude Agent SDK0.2.162, Pydantic2.13.5,
  pytest9.1.1/asyncio1.4.0 and Ruff0.16.9. Installer Playwright MCP is0.0.83;
  CI uses current action majors and maintained Node24. Ruff's original project
  rules E4/E7/E9/F are explicit because its new release broadened defaults.
- Four transitives remain at current compatible resolutions: grpcio1.78.0 and
  protobuf6.33.6 satisfy Weaviate's `<1.80`/`<7` bounds; pydantic-core2.46.5 is
  Pydantic's exact requirement; websockets16.1.1 satisfies GenAI's `<17` bound.
  Forcing registry-newest versions would violate those upstream contracts.
- The agent wrapper uses the verified current configurable Sonnet ID and disables
  model tools, inherited MCP/workspace settings and shared environment mutation.
  Typed terminal errors, missing terminal results and exhausted turn limits fail.
  Its limits cover turns, time and concurrency, not a monetary budget.
  [Claude models](https://platform.claude.com/docs/en/models/overview),
  [SDK reference](https://code.claude.com/docs/en/agent-sdk/python).
- Global MCP registration uses Claude user scope `~/.claude.json`; project
  registration uses `.mcp.json`. Upgrades preserve custom env/settings, local
  companion launchers, unowned files and edited/obsolete managed files. Corrupt,
  noncanonical, escaping, symlinked or hashless manifest paths fail safely.
  [Claude MCP scopes](https://code.claude.com/docs/en/mcp).
- Provider skill references replace fake bundled tool guarantees and personal
  helper paths. Active Sora instructions were removed after the documented
  September24 retirement. Current Omni/Veo/image/TTS capabilities are dated and
  sourced in the relevant skills. The external explainer checkout remains the
  authority for its own installed providers.
  [OpenAI deprecations](https://developers.openai.com/api/docs/deprecations),
  [Veo](https://ai.google.dev/gemini-api/docs/veo),
  [Gemini images](https://ai.google.dev/gemini-api/docs/image-generation),
  [ElevenLabs models](https://elevenlabs.io/docs/overview/models).
- Canonical guidance and docs agree on34+15+2 tools, optional companion installs,
  source/registry/runtime distinctions and portable MCP access. Conflict-marker
  documentation was replaced. Orchestration inherits the configured model.

## Material review findings and corrections

The independent review reproduced three P2 defects using offline scratch data.
All were corrected against that evidence:

1. Consecutive final model-output steps lost earlier report text. The extractor
   now uses SDK output_text; concrete split-step status/follow-up regressions
   verify the complete result reaches storage.38 focused checks passed.
2. Concurrent same-project renders could share one artifact. Admission now uses
   a resolved-project guard before the first await, with finally release. Tests
   cover all blocking/background pairings, aliases, cancellation and independent
   projects.31 focused pipeline checks passed.
3. Manifest namespace checks accepted dot traversal and symlinked ancestors.
   Canonical components, ancestor checks and required ownership hashes now protect
   planning/install/uninstall.13 actual installer journeys passed in scratch homes.

Video sessions preserve complete SDK content and binary thought signatures through
SQLite round-trip. Deep Research launch admission is serialized and preserves
queued/running status. Blocking or background renders require fresh nonempty
artifacts; shutdown joins owned tasks and reaps CLI subprocesses. Injection paths
cannot escape project inputs. Visualization workers preserve user files/processes.

## Local verification

| Gate | Evidence |
|---|---|
| Core full suite, Python3.14.7 |801 passed after report-parser repair |
| Minimum Python3.11.15 |799 full-suite tests before repair;38 affected tests after repair |
| Explainer full suite |129 passed after overlap repair |
| Agent full suite |51 passed |
| Lint and whitespace |All package Ruff checks; git diff --check passed |
| Installer execution |13 passed, including upgrade/uninstall/user-edit and containment cases |
| Security |9 smoke tests;5 direct offline tool checks;0 failures |
| Advisory scan |103 resolved core all-extras dependencies;0 known vulnerabilities |
| Metadata/contracts |Three core versions match;44 shipped mappings;34 root tools;2/15 companion tools |
| Skills/docs |37 frontmatter files parsed; no pinned orchestrator model; local links valid; no invalid core-tool claims |
| Artifacts |Three wheels+sdists built; all6 pass twine check; npm archive builds |
| Built artifact journey |Installed core wheel stdio handshake,34 tools, read-only configuration confirms actual defaults |
| Workflows/cloud scripts |actionlint and bash syntax checks passed |

Reproducible commands (run package commands in their package directory):

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

## Continuation and limits

The [maintenance skill](../../skills/plugin-maintenance/SKILL.md) defines fresh
observation, one bounded correction, verification, durable checkpoint and explicit
stop states. Beads owns status. Resume by reading the issue, exact checkout and
last receipt, then verify worker/job identity before dispatch. Required lanes join
before synthesis. Repeated infrastructure failure after one intervention stops
that path. Weekly dependency coverage includes both companions; CI/release gates
verify exact locks and artifacts. These mechanisms do not claim uninterrupted
unattended execution or demonstrated transfer of an improved harness.

External Gemini/Claude account entitlement, inference quality, generated-media
quality and the upstream video_explainer provider implementation were not tested.
Render admission and job state are local to one server process. SDK deprecation
warnings and the future gRPC minimum remain visible; upstream constraints currently
prevent the newer gRPC version. Advisory coverage is bounded, not proof of absence
of defects. PyPI/npm current releases and existing user-installed configuration
remain unchanged by GitHub publication.
