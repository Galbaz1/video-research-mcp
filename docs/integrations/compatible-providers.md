# Selected compatible providers

The existing Gemini tools keep their account, schemas, defaults, File API,
video/audio handling and grounded-search behavior. Optional text, search and
page-extraction routes require their own explicit operator configuration and a
workflow submission grant. Presence of a credential does not launch a call.

`provider_capabilities` reports concrete configured operation families with no
network requests. Select `gemini`, `weaviate`, `text:PROFILE` or `vision:PROFILE`
and supply `required` capabilities to reject an unsupported choice. Configured
profiles declare capabilities; this inspection supplies no live model acceptance.
Credential-bearing text profile names or metadata block inspection before any
profile values are returned.

| Route | Entry points | Supported responsibility | Separate boundary |
|---|---|---|---|
| Existing Gemini | Existing research/content/video/search tools | Text, structured output, images, audio/video, file handling and grounding through their distinct tools | Each tool retains its own limits and source/upload authority |
| Compatible text | `text_generate` | String messages and an inline structured JSON object | Files, images, audio/video, tools, grounding, embeddings and rerank are refused |
| Existing vision | `vision_chat`, `vision_ocr`, `vision_grounding` | Configured images/video/structured JSON and inferred geometry | File API and grounded web search are separate operations |
| Selected search/extraction | `web_search_provider`, `web_extract` | Direct provider results and source page representations | API responses do not verify original webpage bytes or remote redirects |
| Existing Weaviate | `knowledge_search` and collection configuration | Selected OpenAI/Weaviate/Ollama vectorizer; configured Cohere rerank | Service/model/weight rights, credentials and live acceptance remain separate |

The current collection implementation supports `RERANKER_PROVIDER=cohere` only;
another value fails configuration rather than implying an unimplemented adapter.
Existing `WEAVIATE_VECTORIZER` selections remain `openai`, `weaviate` and `ollama`.
No new embedding/rerank runtime, automatic installer or provider registry is added.

## Structured text

`TEXT_BACKENDS_JSON` is a JSON object of named text profiles. Each profile requires
`base_url` and `model`; `provider` defaults to `dashscope` and can explicitly select
`local_compatible`. `api_key_env` is optional for local profiles and required for
DashScope; `structured_format` defaults to `json_object`. Profile names contain
at most 64 letters/digits/underscores/hyphens; configuration contains at most 32
profiles. Model IDs come from the operator's selected account and current
capability evidence.

For `provider=dashscope`, select an exact workspace-specific regional endpoint:
`https://WORKSPACE.REGION.maas.aliyuncs.com/compatible-mode/v1`. Supported origin
regions are `ap-southeast-1`, `us-east-1`, `cn-beijing`, `cn-hongkong` and
`eu-central-1`. Supply only that region/account's `api_key_env`, whose name ends
in `API_KEY`; missing, blank and unresolved environment placeholders are refused.
The route never borrows a Gemini/vision key or substitutes the
legacy non-workspace origin. For `provider=local_compatible`, explicitly configure
literal `127.0.0.1` or `::1`; an optional selected credential stays local. Hostnames,
private-network addresses, userinfo, query strings and fragments are rejected.
[Official DashScope Chat contract](https://www.alibabacloud.com/help/en/model-studio/qwen-api-via-openai-chat-completions)

Choose `json_object` or explicitly configured `json_schema` only when the selected
model supports that format. One nonstreaming `/chat/completions` POST sends the
complete instruction, context and schema in string messages, with
`max_completion_tokens` for the combined reasoning/answer output parameter.
There is no mapping from Gemini thinking levels, automatic tool invocation,
second attempt, malformed-JSON repair or cache. The actual endpoint/model must
support the requested parameter; current mock contracts do not qualify a live model.

`text_generate` requires `backend`, `instruction` and `output_schema`; `context`
is optional untrusted data. Default `dry_run=true` returns a bounded plan without
DNS or HTTP. Execution needs `dry_run=false` and `authorize_submission=true`.
`required_capabilities` allows the caller to check the intended operation before
transmission. Input/total-token and USD hard ceilings lack an exact meter and
therefore fail before submission when requested.

Create separate named profiles for summary, research, compression and report when
different selected models are needed. Each `text_generate` invocation chooses its
exact profile and output limit; controlled fixtures exercise all four selections.
This explicit sequence preserves the existing research workflow's single frozen
Gemini account. It supplies no automatic multi-provider agent execution. Requested
model identity and model/id reported by a provider are separate observations.

The request is at most128KiB serialized, schema32KiB, response256KiB and generated
JSON text128KiB. Output reservations allow1..8192 tokens. The inline object schema
is validated locally, with bounded complexity. Schema references and the regex
keywords `pattern` and `patternProperties` are refused before submission to keep
validation local and avoid unbounded regex work. The selected profile/account is checked again before
promoting the result. Refusal, length termination, extra choices, tool calls,
invalid/nonfinite JSON and schema violations remain errors. Usage is retained
when observed, including after an invalid answer; absent usage remains null.

The shared HTTP boundary pins a public DNS address, checks the connected API peer
before transmitting headers/body, rejects redirects/proxies/retries/compression,
and joins bounded cleanup on cancellation. Text HTTP submission has a configurable
deadline of 60 seconds by default, capped at 120 seconds. Preflight validation and
answer/schema validation occur outside that timer; shared HTTP cleanup has a
separate five-second grace.
Local operation permits only its exact configured loopback origin.

Execution reports the number of owned HTTP exchange attempts, response/request
hashes, observed usage and unknown physical-wire/currency bounds. An exchange
attempt can fail before provider transmission. It is not a billable-call count.
Model output remains unverified inference with `factual_success=false`. Credentials
are blocked in submitted data and echoed answers; foreign diagnostic bodies are
withheld. No response executes its text or changes instructions.

## Search and extraction

See [search provider contracts](search-providers.md) for the four exact adapters,
operator allowlist, deterministic automatic order and the direct URL acquisition
route. The original `web_search` remains the Gemini route. Search results and
provider markdown are data; URL/title/representation hashes are different from
independently acquired original page bytes and semantic citation support.

## Source and reuse

This change independently implements the requirements of audited Qwen search
backends at revision `07736672525443c7f8a3f6405eed37d2236f023f` and GPT Researcher
provider/retriever units at `0957c301ed06c2a5857b834358c7227c739041d4`. Both exact
root grants are Apache-2.0; the GPT package's MIT metadata is incorrect. No foreign
Python bodies, LangChain/MCP execution framework, model weights or assets are
copied, imported or automatically installed. Actual implementation receipts belong
to [the reuse ledger](reuse-ledger.json).

The supplemental archived `open_deep_research/configuration.py` at revision
`1b7d2e80db9faa586165c60e09096dbbfd483a64` is independently interpreted under its
exact MIT grant. Its role model/output selections are covered by explicit text
profiles. Its MCP URL/tool/auth/prompt fields declare configuration only; they
do not prove external execution, inner attempt bounds or authorization. Separately
selected external MCP integrations retain their own credentials and authority.

API subscription, content/output rights and local model licenses remain separate
from those code grants. This configuration does not authorize provider spend,
user uploads, held-out evaluation, hardware access or registry publication.
