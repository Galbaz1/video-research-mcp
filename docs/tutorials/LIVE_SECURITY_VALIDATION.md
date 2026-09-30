# Live Security Validation Runbook

Use this runbook after a policy change and before release to distinguish three
forms of evidence: mocked regressions, direct calls to local tool functions,
and validation through a running MCP client. An optional provider check exercises
one real Gemini extraction. Passing the offline checks does not establish
provider access or live MCP behavior.

## Validation layers

| Check | What it exercises | External requests |
| --- | --- | --- |
| `run_security_smoke.sh` | Nine focused, mocked regression tests | None |
| `run_live_tool_security_checks.py` | Five policy checks through the tool entrypoint functions in the current process | None by default |
| The script with `--run-online` | One additional Gemini-backed text extraction | A real provider request when credentials are present |
| Manual staging MCP calls | Client transport, the server's effective environment and allowed/blocked behavior | Depends on the selected calls |

The scripts are [run_security_smoke.sh](../../scripts/run_security_smoke.sh)
and [run_live_tool_security_checks.py](../../scripts/run_live_tool_security_checks.py).
Their names do not imply that they connected to a deployed server.

## When To Run

Run the offline checks after changes to URL, path, download, prompt or
configuration policy and before release. Repeat staging validation when the
server deployment, client transport or effective configuration changes.
Organizations can schedule additional checks according to their operating needs;
this runbook does not create an automation.

## Step 1: Enable Required Checks (One-Time)

In GitHub's branch rules for the protected integration branch, require the
checks actually emitted by [CI](../../.github/workflows/ci.yml): the `test`
Python matrix, `companion-packages` matrix and `release-contract` job.
The current matrix includes Python 3.11–3.14 for core and 3.11/3.14 for both
companions. Lint runs inside those jobs; the security scripts run in
`release-contract`.

Select the exact check names from a completed workflow when configuring the
rule. This repository's workflow file does not prove that branch protection
has been enabled.

## Step 2: Run Fast Security Smoke (No API Spend)

From the repository root, with the locked development environment installed:

```bash
uv sync --locked --extra dev
./scripts/run_security_smoke.sh
```

The current script selects nine tests covering URL policy and policy inheritance,
admin-token checks, upload deduplication, the local file boundary, document
preparation and source limits, redirect containment, and batch comparison.
Require all selected tests to pass. Test count is a property of this script,
not a general security-coverage measure.

## Step 3: Run Live Tool Security Checks

Run the five offline checks:

```bash
PYTHONPATH=src uv run --locked python scripts/run_live_tool_security_checks.py
```

| Check | Expected evidence |
| --- | --- |
| `non_https_url_blocked` | `URL_POLICY_BLOCKED` for a non-HTTPS content URL |
| `local_path_boundary` | `PERMISSION_DENIED` for a file outside the configured root |
| `infra_mutation_gate_disabled` | `PERMISSION_DENIED` when mutations are disabled |
| `infra_token_gate` | Wrong token denied; valid token accepted |
| `research_source_limit` | Too-many-sources error before document preparation |

The script uses temporary files and temporary environment settings. It calls
Python entrypoints directly, so these results describe that local process rather
than an MCP client session. A `FAIL` makes the script exit nonzero.

### Optional real-provider extraction

With explicit authority to make the provider request, supply `GEMINI_API_KEY`
through your environment or secret manager and run:

```bash
PYTHONPATH=src uv run --locked python scripts/run_live_tool_security_checks.py --run-online
```

`online_extract` passes when a real extraction returns a nonempty `summary`.
The output records the effective model. It can return `SKIP` if the shell lacks
a key or the provider reports an error classified as transient, including quota,
capacity or network failures. `SKIP` is not evidence of successful extraction,
and the script can exit zero with a skipped check.

To classify transient provider errors as failures:

```bash
PYTHONPATH=src uv run --locked python scripts/run_live_tool_security_checks.py --run-online --strict-online
```

A missing key still produces `SKIP`, even in strict mode. If a release requires
real-provider acceptance, require an observed `PASS`; do not infer it from the
process exit code alone.

## Step 4: MCP Client Live Validation (Manual)

Connect the actual MCP client to a staging server. Record the source revision,
server launch command and relevant effective settings, then exercise:

1. `content_analyze(url="http://example.com")`: expect `URL_POLICY_BLOCKED`.
2. With `LOCAL_FILE_ACCESS_ROOT` set, analyze an out-of-root file: expect
   `PERMISSION_DENIED`. Also verify an allowed file through the intended path.
3. With `INFRA_MUTATIONS_ENABLED=false`, attempt an `infra_configure` mutation:
   expect `PERMISSION_DENIED`.
4. With mutations enabled and `INFRA_ADMIN_TOKEN` set, test a wrong token and
   the valid token: expect denial followed by acceptance. Use a reversible
   staging setting and restore it after the check.
5. With `RESEARCH_DOCUMENT_MAX_SOURCES=1`, request two document sources:
   expect the source-limit error. Verify an allowed request separately if the
   acceptance scope includes real document processing.

Allowed content/document requests can reach providers. Keep their authorization
and output evidence separate from the rejection checks.

## Step 5: Release-Time Checklist

Before tagging a release, retain the offline smoke and direct-tool results with
the exact candidate revision. Block on a policy `FAIL` and repair the observed
failure. Attach the evidence to the release record or PR.

If the optional provider check encounters transient availability trouble, allow
one controlled retry with the intended configured model. If it still cannot
run, record the error and the unverified provider boundary. A release whose
scope permits offline acceptance may proceed with that limit; one requiring
real-provider acceptance has not met its gate.

The [September 2026 audit](../audits/2026-09-modernization.md) records a specific
accepted run. It is historical evidence, not a substitute for checks after a
new security change.
