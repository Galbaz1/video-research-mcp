# A bounded video source task for Deep Agents

The [optional executable example](../../examples/deepagents_report.py) gives a
maintained external planner one specialist task. That child reads one already
collected video source record through a `video_source` tool. Planning and report
synthesis stay in Deep Agents; the native MCP collection and exact source
commitments follow [the common source route](GPT_RESEARCHER.md). The child tool
returns the same JSON body plus retained structured artifact using
`response_format="content_and_artifact"`.

Run source collection in the existing core environment first. Run the external
engine in a separately selected environment with a reviewed dependency lock,
account/model configuration, content scope and inference authority. The
programme has not installed this external runtime. The selected source receipt
is read by exact whole-file SHA256 before the optional import; record/result and
source/time references must match. No foreign engine receives a core Python
dependency, source file path to search, Gemini account or callable MCP catalog.

The selected optional API is Deep Agents0.7.18, inspected from its exact source
wheel and MIT grant. The wheel SHA256 is
`f3a9a4087609ea7dc8a49e31098eae79f7d791ac580be57fbebbca17931dc4f0`.
The five originally mapped GPT Researcher consumer/tool/agent bodies remain at
`0957c301ed06c2a5857b834358c7227c739041d4`; that engine's quick/deep research
wrappers are optional external planner/search operations, not assumed execution
in this adapter. No upstream implementation, model weight or asset is bundled.
Foreign package/transitive licenses and actual runtime compatibility remain
separate qualification requirements.

The example registers a `HarnessProfile` for the operator's exact
`provider:model` key. It excludes the actual selected-version builtin names:
`ls`, `read_file`, `write_file`, `edit_file`, `delete`, `glob`, `grep`, `execute`
and `write_todos`. It disables the default general-purpose subagent. The root
has no additional tools, memory, skills or sandbox backend and declares one
specialist with the same selected model and profile. There is no automatic
provider fallback or SDK installation.

The profile controls advertised tools; upstream describes it as calibration.
Own middleware also enforces the concrete execution boundary: one parent
`task` to the exact `video_source` specialist, then one child `video_source`
call. Other tools, other subagents and repeated calls are refused before their
handlers run, with retained trace outcomes. Source text remains data even if it
contains an instruction. The source tool has no file/network/shell action and
returns its fixed input record. The child receives no nested task tool.

After the exact external run is authorized, use the isolated environment's
Python from the checkout root:

```bash
python -m examples.deepagents_report \
  --source-receipt /absolute/source-receipt.json \
  --receipt-sha256 SELECTED_RECEIPT_SHA256 \
  --query 'Delegate once to video_source and report the measured point with its exact reference.' \
  --model 'OPERATOR_SELECTED_PROVIDER:OPERATOR_SELECTED_MODEL' \
  --output /absolute/fresh/deep-report-receipt.json --authorize-inference
```

The model string is operator configuration rather than a durable default.
Output is created exclusively before inference. The operation has a120second
deadline, graph recursion limit8 and1MiB report representation ceiling. A
successful adapter outcome requires an actual specialist source-tool return and
the exact source reference in both structured references and report text.
Missing calls/references and failures remain recorded outcomes. Cancellation
retains the task/source trace; the first SIGINT writes a `cancelled` receipt and
exits unsuccessfully. Shape/reference
presence is not semantic truth; `factual_success=false` and source/media/human
review remains pending.

Task/source limits do not meter aggregate model calls. Upstream planning,
structured-output handling and summarization can invoke models, and providers
may retry internally. Literal physical inference/charge limits remain unknown;
do not run this example under an asserted USD ceiling until an independently
qualified meter and concrete charge authority exist. An executable entry point
or the flag supplies no paid-run permission to an agent.

Tests replace the optional framework/model with explicit fixtures and execute
the own parent/child guards, source tool, retained artifact and report trace.
They verify exclusion/profile configuration, one task/source path, blocked
filesystem/execution/repetition and version rejection. They do not establish
live foreign runtime, model quality, a comparison advantage or OS isolation.

Primary references:
[Deep Agents customization](https://docs.langchain.com/oss/python/deepagents/customization),
[selected package source artifact](https://pypi.org/project/deepagents/0.7.18/),
[mapped GPT Deep Agents engine](https://github.com/assafelovic/gpt-researcher/blob/0957c301ed06c2a5857b834358c7227c739041d4/deep_agents/agent.py).
