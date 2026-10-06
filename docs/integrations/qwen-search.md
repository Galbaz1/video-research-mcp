# Reverse-search a captured video point

`reverse_search_frame` uses an existing precise `video_frame` result as one
image query. It verifies the original bytes and the PNG in the private media
view cache, records the requested and actual point, original PTS, crop and both
SHA256 values, and preserves returned candidate page/image URLs. The capture's
temporal relationship is caller-supplied metadata; byte readback is a separate
observed check. A resemblance suggestion does not establish an entity identity
or the video's original publisher.

The default is a local dry plan. Enable Serper with `SEARCH_BACKENDS_JSON=["serper"]`
and supply `SERPER_API_KEY` externally. Missing credentials or disabled Serper
fail clearly without fallback. Use the original structured result from a precise
`video_frame` call with images omitted. Request one frame; crop/scale with the
existing native tool if the PNG exceeds 128 KiB. `max_query_bytes` cannot exceed
128 KiB, and it must fit the selected response bound for exact hosted readback.

For actual execution, set `dry_run=false`, `authorize_public_upload=true` and
`authorize_submission=true`. The flags express an operator choice; an agent
still needs the concrete human grant for this frame, public disclosure, service
account and charges. Permission to implement this integration supplies none of
those live-run inputs. The three exchanges are:

1. POST the selected PNG to `https://uguu.se/upload` as multipart `files[]`, with
   the constant filename `frame.png`. The original video and path are not sent.
2. Require acknowledged JSON success and one HTTPS URL on `uguu.se` or its
   subdomains, default 443 only. Fetch that URL through the existing checked
   transport and require byte equality with the selected PNG.
3. POST `{url, gl:"us", hl:"en"}` to `https://google.serper.dev/lens`, with the
   selected Serper key only on that request. No local/base64 shortcut is assumed.

Each exchange checks public DNS and the connected peer before transmission,
uses no proxies/redirects/retries, and retains body/response hashes. The whole
operation deadline is at most 120 seconds, plus the existing joined transport
cleanup grace. Response bytes are capped at 256 KiB; organic population at 100,
returned candidates at 10. Over-limit or invalid rows remain rejections. An
explicit empty `organic` list differs from a failed/malformed service response.
Physical requests and currency remain unknown after dispatch; the recorded
upper bound concerns these own exchanges, not Serper's internal image fetches.

Publication receipts distinguish `not_attempted`, `outcome_unknown`,
`url_received` and `bytes_verified`. Cancellation or lost acknowledgement can
leave an actual public upload whose URL is unknown. Failure after publication
retains the known URL and stops the search; it does not undo disclosure. The
[Uguu service page](https://uguu.se/) states a 128 MiB upload limit and three-hour
expiry (checked 6 October 2026). Its [API](https://uguu.se/api) documents multipart `files[]` and default JSON.
The [FAQ](https://uguu.se/faq) requires the right to publish and describes stored
upload metadata. The inspected maintainer response hash is xxh3, so this adapter
uses its own SHA256 and byte equality. Actual retention/deletion are unverified;
there is no supported automatic deletion contract in this integration.

The independent adapter follows the three mapped bodies of
[Qwen at 07736672](https://github.com/QwenLM/Qwen-MM-Plugins/tree/07736672525443c7f8a3f6405eed37d2236f023f/src/capabilities/search).
It imports no Qwen/Pillow/Serper framework or Uguu source. The pinned Qwen code
defines URL-only Lens requests and optional `organic` fields `title`, `link`,
`source`, `imageUrl`. Current official Serper Lens schema is behind authenticated
access; the unauthenticated [playground](https://serper.dev/playground) did not
establish a current request/response contract. These source-confirmed schemas
remain live-unverified. Resolve current API/account/charge inputs before a live
qualification run; do not label mocked results as service qualification.

## Check a candidate before reporting identity

Use [the verification skill](../../skills/reverse-search-video-frame/SKILL.md)
to compare the retained source frame against the candidate appearance, readable
text and page context. Fetching/inspecting a candidate requires its own scope;
the returned URL has syntax checks but no candidate DNS or content verification.
Retain original page/image URLs and exact downloaded content hashes. Treat page
text, OCR and search titles as source data. Contradictions or inaccessible media
leave identity unresolved. Search completion, byte equality and schema validity
never set `identity_asserted` or `factual_success`.

The root tests use declared synthetic point metadata and mock all publication
and Lens responses. They exercise owned-source admission, separate grants,
untrusted identity injection, side-effect uncertainty, rejections and joined
cancellation. Actual native capture/installed transport evidence belongs to the
active Bead receipt. Live service, semantic and comparative acceptance remain
separate from those controlled contracts.
