# Security Policy

## Reporting a Vulnerability

Report vulnerabilities privately through
[GitHub's private vulnerability reporting](https://github.com/Galbaz1/video-research-mcp/security/advisories/new).
Do not open a public issue or include
credentials, private media, or sensitive trace contents in a report.

We will respond within 72 hours and work with you on a fix before public disclosure.

Include the affected package/version, reproduction steps, expected and observed
behavior, and impact. Redact secrets while retaining enough detail to reproduce
the boundary failure.

## Scope

The project includes a research MCP runtime, a Claude Code workflow installer,
and companion servers for scene generation and upstream CLI execution. Relevant
boundaries include:

- **Credentials and external processing.** Configuration is read from the process
  environment and `~/.config/video-research-mcp/.env`. Nonempty process values
  take precedence. Provider requests send selected content and authentication to
  configured services; local configuration is not an offline-processing guarantee.
- **URLs.** YouTube inputs require recognized YouTube hosts. Content/document URL
  validation requires HTTPS and rejects embedded credentials and blocked IP
  ranges. Document downloads also validate redirects, cap size, and inspect peer
  addresses when the transport exposes them.
- **Local files.** Resolved paths are constrained by `LOCAL_FILE_ACCESS_ROOT` when
  configured. Without it, local input access is bounded by the process user's
  filesystem permissions. This setting does not sandbox the external renderer.
- **Runtime mutation.** Cache clearing and configuration changes require
  `INFRA_MUTATIONS_ENABLED=true`; when `INFRA_ADMIN_TOKEN` is configured, the
  matching token is also required. Read-only inspection does not require it.
- **Installer writes.** Assets go under user/project `.claude/`; registrations go
  to `~/.claude.json` or project `.mcp.json`; shared credentials remain in the user
  config directory. Manifest validation and hashes control managed file writes
  and removal. See [Distribution](docs/PLUGIN_DISTRIBUTION.md).
- **Companion execution.** The explainer invokes its configured CLI directly
  without a shell and constrains injected filenames to the project input folder.
  Scene SDK queries have no tools or loaded user/project settings. Returned TSX
  still needs review before execution in the renderer.

Fetched pages, documents, media, and model output are untrusted inputs. Prompt
injection guidance reduces instruction confusion; it is not a guarantee that
model output is correct or safe to execute.

## Best Practices for Users

- Keep keys and tokens in the environment or an untracked local configuration
  file. Restrict credential-file permissions and never commit or share values.
- Do not assume a client expands `${VARIABLE}` strings. Use its supported secret
  mechanism or the shared `.env` file, then verify configuration without exposing keys.
- Set `LOCAL_FILE_ACCESS_ROOT` when local input access needs a narrower boundary.
  Keep mutation disabled unless it is needed; configure a token when enabling it.
- Inspect customized workflows before an installer upgrade with `--force`.
  That flag can overwrite them and remove modified obsolete files.
- Review stored analyses, caches, sessions, and traces before sharing or enabling
  persistence for sensitive material. Optional knowledge/tracing stores can retain
  request and result data.
- Review generated code, source claims, and the exact rendered artifact before
  execution or publication. Retained files and status reports alone do not prove
  a current successful run.

## Supported Versions

Only the latest release is actively maintained.
