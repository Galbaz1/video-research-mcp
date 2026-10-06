# Optional-capability onboarding

The npm command installs workflow files and a version-pinned core MCP declaration.
It does not install or start Python, fetch a model, invoke a provider, run a device,
or activate an optional Qwen process. The installed client may later execute its
MCP declaration; `uvx` can download the declared Python package at that point.
Select an already-installed, pinned local runtime when an offline launch is required.

## Inspect before changing a client

```bash
node bin/install.js --doctor --global
node bin/install.js --check --global
node bin/install.js --client-config claude
node bin/install.js --client-config cursor
node bin/install.js --client-config codex
```

These commands are read-only. Config examples go to stdout and contain no copied
credential values. Claude and Cursor receive `mcpServers` JSON; Codex receives a
`mcp_servers` TOML table. Review and merge the example in the selected client's
configuration yourself. The installer modifies only Claude's explicit `--global`
user scope or `--local` project scope; it never edits Cursor or Codex configuration.
For Codex, prefer the [native plugin](../PLUGIN_DISTRIBUTION.md#native-codex-plugin)
installed from a Codex marketplace: it packages the skills with the same pinned
server. The TOML example registers only the server, and keeping both declares the
`video-research` server twice.
The [OpenAI MCP configuration documentation](https://developers.openai.com/codex/config-reference)
and [client setup examples](https://developers.openai.com/learn/docs-mcp) describe
the client-side configuration families. Emitting a declaration does not prove that
the named client, server or package is installed.

Doctor reports executable **presence**, credential **presence**, interrupted
checkpoints and actionable missing prerequisites. It runs no subprocess and makes
no network request. Binary versions/compatibility, accounts, quota, reachability,
Python package installation, discovery and analysis quality remain unverified.
The selected scope's env file is read only for bounded key presence; values, endpoint URLs,
local paths and credential-store contents are never printed.

The detailed source-only [provider inspector](../../scripts/inspect_provider_readiness.py)
is reused as a manual prerequisite when available:

```bash
uv run --no-sync --locked python scripts/inspect_provider_readiness.py
```

The npm tarball does not bundle that Python CLI, its source contracts, development
fixtures or a Python runtime. An npm-installed doctor reports it unavailable and
names the source-checkout route. A successful npm doctor never implies that the
Python server or an optional provider works.

## Install and update in the selected scope

```bash
node bin/install.js --global
node bin/install.js --local
```

The same command performs an update. It adds missing workflow assets, updates
unchanged installer-owned assets and preserves user-modified or unmanaged files.
Equal bytes alone do not confer ownership of a preexisting file. The core MCP
entry is added when absent; an existing entry is updated only when its exact hash
matches the prior installation receipt. Existing customized or unmanaged entries,
unrelated servers and other client settings are retained. Optional Playwright and
MLflow declarations are available in the configuration module for deliberate
manual selection; they are not automatically registered or added as core extras.
The env template leaves model/provider settings unset so the selected Python
runtime owns their defaults. Global scope uses `~/.config/video-research-mcp/.env`;
local scope uses `./.config/video-research-mcp/.env`. Local registration sets
`VIDEO_RESEARCH_ENV_FILE` to that exact project path. The current
[Python loader](../../src/video_research_mcp/dotenv.py) honors it without falling back
to home credentials when the selected file is missing. Match the installed runtime to the selected package declaration; older
versions may behave differently. Doctor does not establish the running Python
version or its credential-file behavior.

`--force` explicitly replaces modified workflow assets. It does not force a
customized MCP entry or overwrite credential values. Every install/update creates
a checkpoint before the first managed write, including the original contents of
any asset replaced by `--force`. Config and manifests are promoted atomically.
Package identity, resulting hashes and checkpoint ID are returned as JSON.

## Roll back, restore and uninstall

```bash
node bin/install.js --global --rollback
node bin/install.js --global --restore CHECKPOINT_ID
node bin/install.js --global --uninstall
node bin/install.js --local --uninstall
```

Rollback restores the latest operation; restore selects its exact UUID receipt.
A completed uninstall can therefore be restored too. Recovery compares current
bytes with the checkpoint's expected outputs. Later user-modified assets and env
files are retained. When unrelated client settings have changed, only the still
unchanged owned MCP entry is restored; unrelated settings remain current. A
malformed later config is retained for manual repair. Recovery does not claim to
restore a file that it preserved as modified.

Legacy local checkpoints that captured a home env file have no explicit local
env scope and are refused before recovery writes. Restore that home file separately
only after its current hash matches the old checkpoint's expected output. New
local checkpoints bind their env slot to the project file.

The durable `prepared` checkpoint supports interrupted-process recovery. A new
mutation refuses to run while such a checkpoint remains; doctor identifies its
ID and the operator restores it explicitly. A handled write failure uses the
same hash-checked recovery path automatically. No provider retry or installation
repair is part of this operation.

Uninstall removes unchanged owned assets and unchanged owned MCP entries. It keeps
modified/unmanaged files, unrelated servers, shared credentials and recovery
history. It does not remove optional applications, Python environments or models.

Checkpoint files live under `.claude/gr-install-backups/` in the selected scope.
The directory is private and snapshots use mode `0600`; original configuration
and env bytes can contain secrets. They are local recovery material, never public
telemetry. Command receipts expose hashes/IDs and retained counts, not backup
contents. Snapshot and operation sizes are bounded. Preserve this private history
until recovery is no longer needed; removing it is an explicit user operation.

## Choose the persistence route

These stores have separate configuration and purposes:

| Data | Prerequisite |
| --- | --- |
| Session originals and derived profiles | Set `GEMINI_SESSION_DB` to a private SQLite path before startup. An unset value keeps sessions in memory; derived profile `get`/`set`/`delete` require persistence and explicit workspace/notebook scope. |
| Research, ingestion, batch and render jobs | Keep the SQLite file selected by `VRM_JOB_DB` and its retained artifacts. The default is `~/.local/state/video-research-mcp/jobs.sqlite3`. |
| Local corpus, collections, wiki and notebooks | Supply a local `.sqlite3` `index_path`. `corpus_retrieve` initializes the corpus; wiki/notebook citations require matching observations. These tools share the corpus independently of Weaviate. |
| Weaviate knowledge | Set `WEAVIATE_URL` for a reachable deployment and `WEAVIATE_API_KEY` where required. Configure a compatible vectorizer and its provider credentials. |

For Weaviate, `knowledge_schema` describes the accepted collection properties;
`knowledge_ingest` inserts those properties explicitly. `source_ingest` retains
and extracts originals but does not index them. See the
[knowledge-store guide](../tutorials/KNOWLEDGE_STORE.md) for deployment setup.
The first Weaviate client use creates missing collections and adds missing schema
properties. Vectorizer migration is disabled unless `WEAVIATE_AUTO_MIGRATE=true`;
review that choice before using an existing store.

`WEAVIATE_VECTORIZER` selects `openai`, `weaviate` or `ollama`. When unset, runtime
configuration selects `openai` if `OPENAI_API_KEY` is present, otherwise `weaviate`;
the deployment must support the selected module. The repository's Docker Compose
service uses `text2vec-openai` and an existing external data volume, so it needs
matching OpenAI configuration. `COHERE_API_KEY` enables Cohere reranking unless
`RERANKER_ENABLED=false`; `FLASH_SUMMARIZE=false` disables the optional Gemini
post-processing of knowledge-search hits. These provider operations have separate
account and disclosure requirements.

## Optional runtimes and client media support

The [Qwen integration manifest](../../integrations/qwen/manifest.json) records the
exact audited source, declared capability tags, applicable notice commitments and
external prerequisites. All fourteen foreign capability processes remain disabled;
no Qwen code, runtime, model, font, stock media or managed binary is bundled.
Smiley Sans, unattributed assets and the grantless renderer remain blocked. Any
future executable selection needs its own version/platform/hash, dependency lock
and source/license notices before a separately authorized installation.

Native image support must be verified against the **current server** discovery,
input/output schemas and actual MCP `ImageContent` transport. The current source
registers `image_crop` over the bounded PNG helper. It emits native PNG
`ImageContent` up to 1 MiB and the same typed structured metadata for
`include_image=false` text-only clients. Other image operations use the separate
`image_edit` tool. Package declarations select a pinned runtime; source
registration does not prove which package a client is running. For source-checkout testing, select its already installed environment
explicitly. Doctor reports transport as unprobed because it does not launch it.
The npm config examples do not establish native display, crop correctness,
provider-media accuracy or comparative acceptance.

For a live provider operation, use the separately reviewed
[development-run plans](PROVIDER_RUNS.md). Key availability supplies no upload,
output, spend, publication or device authority. Keep the human source audit and
independent heldout comparisons at the programme's final acceptance gate.
