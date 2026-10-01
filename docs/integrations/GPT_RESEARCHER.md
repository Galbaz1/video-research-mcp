# Video sources for an external research report

The executable integration discovers this MCP, selects only `video_frame`, and
collects one source-bearing point result. It preserves original media identity,
requested versus decoded time, original PTS, extracted artifact metadata and the
complete structured result. An external planner/report writer receives this
record as untrusted source data. Core does not implement another research engine.

The [collector](../../examples/external_video_source.py) uses the existing
[native tool](NATIVE_MEDIA.md) and
[stdio settings](external-harness.json). It connects with FastMCP4.0.10 and
MCP2.2.0, negotiates the legacy handshake, and makes one uncached discovery page
plus one direct `ClientSession.call_tool` submission. Input-required and claimed
results are disabled; unexpected responses fail without another submission.
Only `video_frame` is selected from the advertised catalog. The external engine
receives no callable shell, filesystem, publication, upload or provider tool.

The settings declare transport, explicit whole-value `${ENV_NAME}` substitution,
dependency versions and required capabilities. Missing substitutions or changed
dependency/capability sets fail before spawning. There is no shell expansion,
auto-install, discovery cache, tool fallback or retry. Initialization is bounded
by10seconds, each request by30seconds, and the collection including connection
lifecycle by45seconds. Stdio has `keep_alive=false`. `LOCAL_FILE_ACCESS_ROOT`
fences the selected original media; `GEMINI_CACHE_DIR` holds extracted views.
FFmpeg/FFprobe must be installed independently. Native extraction invokes no
Gemini inference or upload; the explicit Gemini key satisfies current core
configuration only. The SDK default process environment still supplies normal
OS execution variables; this is not an OS sandbox.

Set `VRM_PYTHON` to the absolute Python executable of the already installed core
environment, `VRM_WORKDIR` to its working directory, `VRM_SOURCE_ROOT` to the
authorized source directory and `VRM_CACHE_DIR` to an owned cache directory.
Supply `GEMINI_API_KEY` externally. Select the expected source SHA256 before
collection; source text or an external planner must not select a different file.

```bash
uv run --no-sync --locked python examples/external_video_source.py \
  --settings docs/integrations/external-harness.json \
  --source /absolute/authorized/video.mp4 \
  --source-sha256 SELECTED_64_CHARACTER_SHA256 \
  --seconds 0.25 --output /absolute/fresh/source-receipt.json
```

The output is created exclusively before collection. A failed or cancelled
attempt retains its trace after the client context joins and has no promoted
source record. The first SIGINT during collection writes a `cancelled` receipt
and exits unsuccessfully. A successful record has `href`,
`title` and `body`; its `urn:sha256:…#t=…` reference identifies the original bytes
and actual decoded point, and is an evidence identifier rather than a web URL.
The structured result and JSON text mirror must agree. Point extraction is not
a visual/spoken fact, continuous watched interval or factual acceptance.
`tool_result_sha256` commits canonical finite UTF-8 JSON; the original media and
extracted artifact hashes commit their distinct bytes.

## Isolated GPT Researcher consumer

The pinned mapped source is
[GPT Researcher at0957c301](https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/gpt_researcher/agent.py),
package0.16.0. Its MCP dependency requires1.x, conflicting with core2.x. Keep it
in a separately selected and licensed environment with its own dependency lock;
do not install it into core. This programme has not installed or qualified that
foreign runtime. Actual root Apache-2.0 grant takes precedence over incorrect MIT
package metadata. Transitive runtime, service/account and output rights require
their separate receipts before actual imports or inference.

The [optional report consumer](../../examples/gpt_researcher_report.py) uses
only built-in Python before its explicit, version-checked optional import. It
reads the selected source receipt by exact whole-file SHA256, then checks its
record/result/reference commitments. It passes the retained JSON string to
`GPTResearcher(context=[…], visited_urls={…}, mcp_strategy="disabled", role=…)`
and `write_report(ext_context=[…])`. It does not call `conduct_research`, which
would replace the selected context and invoke planner/search. The exact version's
direct report hook reads `available_images`, normally initialized by research;
the example explicitly initializes it to an empty list. The existing external
engine owns report synthesis and its configured model. The source adapter owns
no external engine state, prompt execution or search credentials.

Once the concrete model/account, content, charge limit and operation are
authorized, run this example from the isolated consumer environment:

```bash
python /absolute/checkout/examples/gpt_researcher_report.py \
  --source-receipt /absolute/source-receipt.json \
  --receipt-sha256 SELECTED_RECEIPT_SHA256 \
  --query 'Report only the measured video point metadata and its exact reference.' \
  --consumer-config /absolute/selected-gpt-researcher-config.json \
  --output /absolute/fresh/report-receipt.json --authorize-inference
```

The flag records an operator choice; it does not supply human authorization to
an agent. The example bounds its report operation by120seconds and its report
representation by1MiB. It retains a missing reference as `missing_reference`,
including the report, and records setup/execution failures without a success
claim. Provider submissions, retries, usage and currency remain unknown because
the external report engine does not expose a literal aggregate meter here.
Do not interpret the operation deadline as a paid-call or USD ceiling.

GPT's existing quick/deep research and Deep Agents engines can plan/search and
then consume this source through the same explicit report context. Their planner,
search and nested-task executions require their own authorized limits; no
`quick_search`, `deep_research` or task is assumed to have run from a report or
configuration. The mapped native MCP selector also flattens tool output; the
explicit record route preserves the structured/source carriers it would lose.
See [the separate maintained Deep Agents route](DEEP_AGENTS.md).

## Verified boundary

The repository contract test opens an actual MCP client against a mocked source
server, discovers/selects the video tool, consumes the structured/text response,
and binds a mocked report's exact source references to result/record/report
hashes. A separate test runs the public GPT constructor/report hook against an
explicitly mocked optional engine. These prove adapter and source/report
contracts; they do not prove external model quality or a live foreign runtime.
Failures, refusals and missing citations remain outcomes. Installed stdio/native
journey evidence belongs to the active Bead receipt, not a documentation claim.

Primary API references:
[FastMCP client lifecycle](https://gofastmcp.com/clients/client),
[GPT MCP configuration](https://docs.gptr.dev/docs/gpt-researcher/retrievers/mcp-configs),
[pinned report writer](https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/gpt_researcher/skills/writer.py).
