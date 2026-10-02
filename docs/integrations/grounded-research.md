# Bounded research and original-source packets

`research_execute` prepares or executes an explicit source route. It stores the
subquestions, original source population, source/domain rules and stop conditions
before provider calls. It retains every required subquestion, failed source,
failed round, contradiction, abstention and superseded proposal in the run report.
Source content is data; instructions embedded in it have no authority.
Private JSON artifacts have an eight MiB recovery ceiling. Executed frozen
source/claim/lineage context must serialize within four MiB before inference;
raw-byte allowances do not imply unlimited JSON expansion or model context.

The four modes have concrete meanings:

| Mode | Input and observed access |
| --- | --- |
| `model_only` | Topic and optional subquestions; no retrieved sources. Output is an unverified model draft. |
| `supplied` | An original `EvidencePacket` and `source_root`; bounded exact local bytes are copied and validated. Media snapshots record supplied observations; this route does not watch or transcribe the media. |
| `retrieval` | Explicit HTTPS seed URLs; protected response bodies are observed only when source access is authorized. No model-selected URLs are fetched. |
| `hybrid` | Both supplied originals and explicit permitted URL bodies, with separate access records. |

An existing `research_web` job remains the hosted route for broader grounded
discovery. Poll its actual job and preserve failures. Its citation URIs/titles
do not supply page bytes or original SHA commitments. Its SDK does not expose
enforceable internal search/token/charge ceilings. No route automatically switches
backends after failure. `research_deep` remains three-phase model-only synthesis;
CONFIRMED/STRONG INDICATOR model proposals become UNKNOWN and retain their original
proposed tier. `research_plan` produces a proposed plan, not executed research.

## Prepare and execute

All requests default to `dry_run: true`. Dry preparation makes no provider,
DNS or HTTP calls; it may copy bounded supplied originals into private run
storage. A planned URL records no observed access. Execute a distinct request
after the relevant real authority is established:

```json
{
  "request": {
    "topic": "What do the admitted trial reports say about sample sizes?",
    "mode": "retrieval",
    "urls": ["https://example.org/trial-report.txt"],
    "allowed_domains": ["example.org"],
    "subquestions": ["What sample size is stated?", "What limitations are stated?"],
    "dry_run": false,
    "authorize_source_access": true,
    "authorize_submission": true,
    "limits": {
      "max_calls": 8,
      "max_tokens": 60000,
      "max_output_tokens": 2048,
      "concurrency": 2,
      "max_revisions": 1,
      "max_source_requests": 6,
      "max_source_bytes": 1048576,
      "max_total_source_bytes": 1048576,
      "timeout_seconds": 120
    }
  }
}
```

Those authorization flags record the caller's authority; they do not obtain
permission from the human or turn a configured key into a spending grant.
Without submission authorization or an account, execution fails before provider
calls. Without source-access authorization, URLs are retained as rejected access
records. A sourced route with no admitted originals makes zero inference calls.
`max_cost_usd` blocks executed submission because this backend has no verified
USD charge ceiling. It remains visible in a dry plan.

Limits apply to the whole run, not individually to each subquestion. Up to four
branches share one call/token allowance and a semaphore; each may perform only
the declared zero-to-two revisions. Token counts and generations each consume a
provider call. Generation reserves the counted prompt, conservative schema UTF-8
byte allowance and output allowance before submission. Missing usage keeps the
reservation and unknown telemetry. A refused/truncated/invalid/oversized result
stays a failed round; there is no automatic JSON repair, provider retry or new
source search. Unchanged proposals, unresolved gaps, limits and cancellation are
explicit termination outcomes. All submitted branches are joined before return.

Only SDK calls and their reservations are bounded here. Physical transport
attempts and currency are unverified; a reservation is not a measured charge.
SDK retry options use one attempt, which does not prove a physical wire count.

## Source access and support

At most eight original sources are admitted. Local reads are bounded before
copying and preserve source IDs, revisions, hashes, extension fields, snapshots,
page metadata, original-clock intervals and all supplied claims/lineage. Derived
and synthetic assets cannot substitute for original support. Missing or changed
originals remain rejected records, including when other sources succeed.

URL access uses the protected HTTPS/DNS/peer/redirect policy. Domains match exact
hosts; an omitted allowlist means the explicitly supplied seed hosts. Every URL
reserves six possible HTTP requests before dispatch, covering at most five
redirects. Disallowed hosts are blocked before DNS and HTTP. Response bodies must
be UTF-8 text, HTML or JSON; no PDF/Word/transcription parser runs. Raw bytes and
their SHA are preserved. Received and admitted body counts remain separate,
including failed streams. Unknown-length overflow can consume one bounded
rejection chunk, then further body reads stop. These yielded-chunk counts do not
measure physical wire bytes. Cancellation joins source work and removes its
incomplete owned acquisition files.

Each finding retains its proposed tier and exact citation IDs. The curator
checks source IDs, exact quote presence and existing media passage IDs. Text
quotes may create stable quote passage IDs. Original media observations must use
their supplied passage ID and source clock; invented clocks are rejected. Exact
source text establishes quote presence only. Paraphrases, invented facts,
unknown IDs, contradictory passages and rejected citations remain explicit.
All new findings have `evidence_tier: UNKNOWN`, `editorial_approved: false`,
`semantic_support: not_verified` and `factual_success: false`.

The public response exposes the run report, source metadata, claim IDs and private
artifact paths. The saved `evidence-packet.json` holds exact frozen originals and
current new claims alongside all supplied claims and lineage. Older completed
rounds stay in the report with `retained_in_packet: false` when superseded; they
are not silently included as current claims. Configured account material is
redacted from model proposals/diagnostics and blocks source submission. Original
private input bytes are preserved for integrity, not rewritten as model text.

## Recovery and production

Save the executed `run_id` (32 lowercase hexadecimal characters). If recovery
must survive a disconnected response, supply a freshly generated ID before
execution. Repeating the
same request with this ID verifies the request/account identity, response/state/
packet commitments and original source bytes before replaying a terminal result.
Replay reports `replay_new_calls: 0`. Changing any committed artifact, original
source, topic, account or limits refuses replay. A dry request and executed
request have different identities; omit `run_id` when beginning the executed run.

A cancelled, timed-out or interrupted run without a complete result receipt
returns `RECOVERY_REQUIRED`; it preserves the attempted population, operation
failure and unknown usage. It does not submit again. Failed checkpoints cannot
certify later attempt counts: recovery exposes
`last_checkpoint_provider_calls` separately and reports `provider_calls: null`.
An in-memory failure response preserves known attempts even if its failure
checkpoint cannot be written. Unexpected wrapper failures report unknown counts.
Interrupted preparation
records its required population and incomplete state without claiming that an
unreturned body was observed. Inspect that exact run before authorizing a new
run. A concurrent collision also supplies no duplicate submission.

For `explainer_inject`, copy the exact original assets from the returned root to
the project's `input/`, changing only checked relative paths in the packet.
Preserve IDs, hashes, pages, original intervals, claims, approvals and existing
lineage. Keep the full research report alongside it, including failed branches
and contradictory/rejected citations. New claims need editorial review before
use as approved factual script text. Retain exact approved claim text and parent
IDs through script, narration, storyboard and rendered text, including actual
captions and voiceover. Inspect the companion's `evidence_validation` after each
revision. Renderer success, exact support and source integrity remain separate
from semantic truth, human audit, factual acceptance and comparative advantage.
