# Optional search providers and page extraction

`web_search_provider` and `web_extract` add explicit provider operations. The
existing `web_search` continues to use Gemini Google Search with its original
schema and behavior. These optional tools do not generate summaries or follow
instructions found in snippets or webpages.

Enable only the intended services:

```bash
SEARCH_BACKENDS_JSON='["serper","tavily","exa","serply"]'
# Set each enabled provider's own key through the environment/secret store:
# SERPER_API_KEY, TAVILY_API_KEY, EXA_API_KEY, SERPLY_API_KEY
```

The default enabled list is empty. `backend="auto"` selects the first enabled
credential-ready provider in **Serper, Tavily, Exa, Serply** order. Configuration
list order does not change this priority. A pinned backend must be enabled and
have its own key. Missing/placeholder keys fail before transport. A failed
provider request never falls back or retries. Configuration and the selected
credential are frozen into a digest and rechecked before and after submission.

Both tools default to `dry_run=true`. A dry plan performs zero DNS/HTTP requests.
Execution additionally requires `authorize_submission=true` for the exact call;
having a configured key does not itself authorize a request or charge. Readiness
and mocked contract tests do not establish live service/account acceptance.

Example dry search:

```json
{"request":{"query":"Example topic","backend":"auto","num_results":5}}
```

`num_results` is a strict integer from 1 to 10. One query has at most 8,192
characters. Search requests use the following fixed origins and schemas:

| Provider | Search | Extract |
| --- | --- | --- |
| Serper | POST `https://google.serper.dev/search`, `X-API-KEY`; `q`, `gl=us`, `hl=en`, `location=United States`, `num` | POST `/scrape`; `url`, `includeMarkdown=true`; JSON markdown then text |
| Tavily | POST `https://api.tavily.com/search`, Bearer key; `query`, `search_depth=basic`, `max_results`, `include_answer=false` | POST `/extract`; one `urls` entry, `format=markdown`; matching `raw_content` and explicit `failed_results` |
| Exa | POST `https://api.exa.ai/search`, `x-api-key`; `query`, `numResults`, `contents.text.maxCharacters=1000` | POST `/contents`; one `urls` entry, `text.maxCharacters=8000`; matching URL/id and status |
| Serply | GET `https://api.serply.io/v1/search/`, `X-Api-Key`; encoded `q`, `num`, `hl=en`, `gl=us` | POST `/v1/request`; `url`, `response_type=markdown`; raw UTF-8 markdown |

Serply extraction uses the retained documented minimal request. Its pinned
upstream source also sent `method=GET`; no service behavior is inferred from
that older extra field. Serper's retained official playground supplied no static
endpoint contract; its selected protocol is grounded in the pinned source and
mocked fixtures, with current live acceptance still unverified.

Search preserves observed title/text/date and other metadata. Missing dates or
titles stay absent. Invalid or unsafe links become indexed rejections and make
the result partial. Returned links are HTTPS syntax checked, including literal
private-address rejection, but are not DNS resolved or fetched. More results
than requested, oversized text or malformed populations fail the operation;
there is no silent slicing. Published dates differ from the actual extraction
observation time. Provider request IDs, usage and cost metadata are retained only
when actually returned; they do not establish an enforced currency ceiling.

`web_extract` accepts one HTTPS URL and defaults to `backend="direct"`:

```json
{"request":{"url":"https://example.org/page","backend":"direct"}}
```

Direct execution checks every redirect hostname, DNS response and actual public
peer through the existing URL policy. `allowed_domains` is an exact hostname
list; omission allows only the source hostname. At most six HTTP requests are
reserved for its fixed redirect loop. Actual physical request counts remain
unknown. Direct content is raw UTF-8 text/plain, text/html or JSON (including
application/*+json); HTML title text is parsed locally with a 4 KiB title cap.
Scripts and source instructions remain data. PDF/Word parsing and inference are
outside this operation. Non-UTF-8 charset declarations and compressed direct
responses are explicit refusals before body buffering.

Provider extraction checks the requested source URL against local URL policy
before sending that URL as data to the fixed service API. It matches requested
URL/id independently of response order and rejects requested-URL failures even
when HTTP status is 200. The local API peer check cannot verify the service's
remote webpage redirects, source bytes, cache age or content rights. Tavily rows
match only their URL; Exa permits an exact URL or ID, with conflicting URL/ID
fields refused. The matched row's reported identity remains in metadata. Its result
therefore declares `provider_returned`, original-page and remote-redirect
verification false, and `page_fetched_at=null`. `fetched_at` is when this operation
observed the returned representation. Direct results separately record observed
final URL and page observation time.

Requests have one deadline of at most 120 seconds, a response ceiling of 256 KiB
and returned text ceiling of 128 KiB, with lower caller-selected limits allowed.
The authenticated exchange has no redirects, proxies or retries, pins public
DNS before transmission, and attests the connected peer before sending keys.
Owned transport cleanup has a separate joined five-second grace. Direct chunk
overflow is counted and rejected before admission; this measures yielded body
bytes, not physical wire bytes or process memory. Cancellation produces an
observable error after the owned exchange/response cleanup, with attempted
outcome and charges unknown. No automatic recovery submission occurs.

Responses contain full response/representation SHA-256 commitments and call
receipts. Selected keys, their URL encodings and sensitive URL parameters are
redacted from returned observations; the raw representation hash and returned
content hash remain separate, with `redactions_applied` explicit. Upstream error
bodies are withheld. No adapter cache is used. `source_content_role="data"` and
`factual_success=false` apply to every successful provider observation.

This is independently authored logic informed by the pinned Qwen search and
gpt-researcher adapter requirements. No foreign provider framework, code body,
model weights or optional SDK is imported. Source grants, service terms,
returned-content rights and explicit runtime/spend authority remain separate.
