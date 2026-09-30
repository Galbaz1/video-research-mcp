# Documentation

Start with the task you want to complete. The research server works with any
stdio MCP client; the slash-command workflows target Claude Code. Video production
and saved-knowledge storage are optional additions.

## Install and use

| Guide | Use it to |
|---|---|
| [Getting started](tutorials/GETTING_STARTED.md) | Install, configure credentials, connect a client, and verify your first call |
| [Updating the plugin](update-plugin.md) | Refresh workflows and runtime packages while preserving local edits |
| [Knowledge store](tutorials/KNOWLEDGE_STORE.md) | Configure Weaviate, choose embeddings, and verify stored results |
| [Weaviate skills](weaviate-agent-skills.md) | Use the database skills alongside the plugin's knowledge tools |
| [Explainer companion](../packages/video-explainer-mcp/README.md) | Configure the external video pipeline and render a project |
| [Scene-agent companion](../packages/video-agent-mcp/README.md) | Generate scene code with bounded Claude Agent SDK calls |

The [root README](../README.md) maps common tasks to commands and tools.
The [tool manifest](metrics/tool-contract-manifest.json) records exact MCP schemas;
[metrics notes](metrics/README.md) explain how the generated evidence is maintained.

## Extend and understand

| Guide | Use it to |
|---|---|
| [Architecture](ARCHITECTURE.md) | Follow requests through validation, providers, sessions, caches, and storage |
| [Diagrams](DIAGRAMS.md) | See the server boundaries and main request flows |
| [Adding a tool](tutorials/ADDING_A_TOOL.md) | Implement and register a tool using the existing contracts |
| [Writing tests](tutorials/WRITING_TESTS.md) | Use mocked fixtures and verify observable behavior |
| [Contributing](../CONTRIBUTING.md) | Prepare a focused change and run its required checks |
| [Security policy](../SECURITY.md) | Understand the trust boundaries and report a vulnerability |
| [Live security validation](tutorials/LIVE_SECURITY_VALIDATION.md) | Separate offline checks from authorized provider and process validation |

## Maintain and release

- [Plugin distribution](PLUGIN_DISTRIBUTION.md) explains Python runtime packages,
  npm workflow assets, and Claude plugin discovery.
- [Publishing](PUBLISHING.md) describes artifact preparation and each publication
  destination.
- [Release checklist](RELEASE_CHECKLIST.md) gives the final verification sequence.
- [Changelog](../CHANGELOG.md) records released changes;
  [roadmap](../ROADMAP.md) separates implemented work from proposed work.

## Evidence and historical findings

- [September 2026 modernization audit](audits/2026-09-modernization.md): dated
  source decisions, verification results, and limits.
- [Dependency source inventory](audits/2026-09-dependency-sources.json): primary
  registry metadata collected for that audit.
- [Knowledge-ingest UX findings](KNOWLEDGE_INGEST_UX_FINDINGS.md): the conditions and
  results of a specific diagnostic session.
- [Supply-chain report](../.supply-chain-risk-auditor/results.md): bounded advisory
  and dependency-source inspection.

A historical receipt describes the revision and checks it names. Use current
source, registry metadata, and the running MCP configuration to establish what is
available now.
