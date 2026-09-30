# Interactions experiment: protected-contract evaluation

Keep the current GenerateContent generation, explicit cache and video-session
routes. Reject a wholesale merge of the Interactions experiment. Its JSON and
static video-window requests serialize through the installed official SDK, and
native interaction IDs offer a useful state mechanism, but the branch loses
protected history and advances unsuccessful responses as completed turns. No
production adapter is justified by this evaluation alone.

This is the bounded offline disposition for `vrm-0e8.2.1`, source unit
`own.interactions-compatibility`. It establishes local SDK compatibility and
specific counterexamples, not live inference quality, service parity, cost savings
or product superiority. The coordinator joins its retained-contract gates and
records acceptance in Beads.

## Authority and fixed inputs

The experimental source is the exact own MIT revision
`000434257e09dfd4eef93546442de2d6c597a53d`, inspected through local Git. Comparison
started from implementation HEAD `d0fe119fab4401cdebdfb859cc5b364b4dc09209`;
the private receipt identifies the final working-source hashes because other
authorized implementation lanes continued independently. The public baseline,
execution and human acceptance boundaries remain in
[LOOP.md](../loops/multimodal-capability-programme/LOOP.md).

The installed, locked SDK was `google-genai 2.25.0`. Original fixture inputs use
the current `ServerConfig` model and thinking defaults, disable Weaviate and
dotenv/tracing, and use a visibly synthetic credential. The actual public SDK
serializes requests into `httpx.MockTransport` at `original-fixture.invalid`;
no provider request, upload or remote interaction is created. The retry-error
probe uses a synthetic model identifier because no inference occurs.

Five exact own-source function bodies are embedded in the regression test so CI
does not require unpublished Git objects. Their decorators are excluded for
isolated invocation. Copyright and MIT attribution remain in the test, and
`copied-test-excerpts.json` records original file/line and fragment hashes. These
are test fixtures; no experimental production module is copied or registered.

## Disposition by functionality

| Functionality | Observed evidence | Disposition |
| --- | --- | --- |
| Generation, typed JSON, schema/tool errors | Current generation remains supported. Branch JSON `response_format` reaches the actual mocked SDK with its schema intact. | **Retain** current public generation; **retain as a compatible reference** the JSON request shape. |
| Static video windows | Original URI, FPS and `2s`/`4s` offsets survive SDK serialization. The SDK normalizes flat input to a `user_input` step. | **Retain** current bounded window route; **retain as a compatible reference** this static shape. Live coverage and absolute-time accuracy remain untested here. |
| Agentic video default | The branch selects `agentic` when no static metadata exists. Official schema permits it; this evaluation measures no frame selection, latency or budget behavior. | **Reject** silently replacing the current default. It requires a separately bounded experiment. |
| Multimodal and tool conversion | Binary inline video and GenerateContent `types.Tool` produce SDK validation errors before transport. Image/audio URIs become `document`, and history roles, function calls and signatures disappear. | **Reject** the converter. The wrong media discriminator is an observed payload defect, not a claimed live server rejection. |
| Model output and completion | The SDK text accessor exposes only trailing model-output text. Five mocked noncompleted statuses still produce an empty successful turn and promote the remote ID in the branch. | **Reject** text-only success handling and unconditional turn/ID advancement. Preserve status and relevant steps before committing state. |
| Persistence and signed replay | Branch serialization drops signatures, inline bytes and function parts; current Pydantic serialization round-trips the original content. | **Retain** current full-content persistence and replay. |
| Native interaction-ID chaining | Two local SDK requests preserve `previous_interaction_id`. An additive SQLite column survives restart, but an unadapted current `INSERT OR REPLACE` save resets it. An expired remote ID has no branch replay fallback. | **Retain as a useful compatible mechanism**, conditional on a concrete caller and complete writer/recovery adaptation; **reject** the branch persistence/session replacement. No unused adapter is added. |
| Explicit cache and session fallback | The branch deletes the cache-bridge test file and removes explicit-cache paths. Current cache preparation, TTL/model fallback, bounded history and signed response tests remain present. | **Retain** the current routes and tests. SDK field presence or implicit caching cannot establish equivalent service behavior or measured savings. |
| Credential handling and configuration | Current client-constructor log test preserves credential redaction. Branch model/default rewrites have no measured benefit under current configuration. | **Retain** current configuration, logging and public contracts. Do not restore sibling-branch defaults. |
| Nonidempotent creation retries | Installed SDK with `HttpRetryOptions(attempts=1)` makes two local create attempts on 503. Setting zero normalizes to one and still makes two; GenerateContent makes one under the same normalized setting. | **Reject** constructor settings alone as proof of a one-create bound. The coordinator must verify resource-specific retry policy before durable-job adoption. |

Google documents `generateContent` as fully supported and describes Interactions
as a migration option. Its migration guide distinguishes trailing `output_text`
from complete interleaved steps. That supports retaining the existing route while
evaluating native mechanisms without a forced switch.
[Official migration guide](https://ai.google.dev/gemini-api/docs/migrate-to-interactions).

Storage is a behavior change: the branch omits `store`, while the documented
default is true. Disabling storage prevents stateful continuation/background
operation. Previous IDs carry history; system instructions, tools and generation
configuration must be resent. The documented limitations also distinguish
explicit caching and custom safety controls from GenerateContent. SDK request
acceptance alone does not resolve those service limitations.
[Official Interactions overview](https://ai.google.dev/gemini-api/docs/interactions-overview).

The API reference defines distinct image/audio/document inputs, JSON response
formats, static/agentic video processing, and completed versus other lifecycle
statuses. These are the schema comparisons used above; all service behavior
remains unverified by this local transport experiment.
[Official Interactions API reference](https://ai.google.dev/api/interactions-api).

## Concrete adaptation boundary

A future current caller needing provider-managed state can justify native IDs.
The smallest complete adaptation must preserve typed roles/media/tool conversion,
explicit storage policy and per-turn settings; reject unsupported parts before
creation; validate completed status and preserve relevant steps before advancing
state. An additive ID migration must update every writer and prove restart,
expired-ID handling and retained local replay. Existing cache, schema, security
and stdio behavior remains the regression denominator.

For durable creation, enforce the operation's attempt budget at the resource that
actually sends the request. The measured SDK bridge translates `attempts` to
`max_retries`, while its main API client normalizes zero to one. Separate retry
control needs an actual SDK MockTransport proof of one create after an ambiguous
failure, plus restart/cancel/status recovery, before it can authorize a live run.
This is a source-to-sink requirement returned to the coordinator, not an adopted
production implementation in this leaf.

## Verification and limits

The focused regression file passes **19 tests**. It exercises the exact frozen
branch functions, actual SDK serialization, current full-content round-trip,
isolated SQLite restart, negative completion handling and credential redaction.
The eight SDK transport invocations in the final test run are exclusively local:
four compatible request cases and four 503 attempts across two retry settings.
Ruff lint/format and exact excerpt/hash verification pass. Commands and output
hashes are in the private receipt; replay the focused gate with:

```bash
PYTHONPATH=src uv run pytest tests/test_interactions_compatibility.py -q
uv run ruff check tests/test_interactions_compatibility.py
uv run ruff format --check tests/test_interactions_compatibility.py
```

Two fixture-authoring failures remain in evidence: an incorrect raw `output_text`
fixture omitted model-output steps, and an assertion assumed the SDK kept flat
input. Both were corrected to the inspected SDK contract; no acceptance criterion
or production behavior was weakened. The experimental branch's deleted
`tests/test_cache_bridge.py` is retained, as are client, session, persistence and
security tests. The coordinator's fresh integration gate supplies the final
stdio/schema/cache/session/security receipt; this leaf does not rerun a full suite.

Provider quality, grounding, media coverage, remote storage/recovery, implicit-cache
benefit, live retry behavior, billed tokens and comparative advantage are unknown.
No held-out input, label or private source snapshot was consumed. Any paid or live
comparison requires the frozen evaluation inputs and separately granted resource
authority; available credentials do not supply it.
