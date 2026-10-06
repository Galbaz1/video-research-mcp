# Local and explicitly configured stock materials

This companion source seam provides three typed tools on `materials_server`:
`explainer_materials_assemble`, `explainer_materials_search`, and
`explainer_materials_download`. The companion source server mounts these tools;
Root owns installation, review, adoption and native admission. Source tests use dummy
media and mocked network/codec boundaries. No native media or provider journey
has been run. They introduce no dependency, root asset catalog, database schema,
provider activation, inference or renderer framework.

Assembly uses an existing project selected through the companion's configured
projects root. Inputs are canonical relative project paths and caller-observed
SHA256 values. The companion's existing `confined_path`, `open_regular`,
`file_pin`, `project_object`, `plan_transaction`, `atomic_write`,
`run_media_process`, `codec_executables`, and `qualify_render` contracts are
reused directly. The planning transaction serializes cooperative project
writers; it is not an authentication or filesystem isolation mechanism.

## Local assembly

Each `MaterialsRequest` contains an explicit principal and an ordered list of
clips. Each clip binds one unique scene ID and a caller supplied script ID to an
existing local source and a separate pinned rights JSON file. This seam does
not infer entity matches or script truth. It accepts MP4 video and PNG/JPEG
still images, produces silent H264 MP4 at 720p or 1080p, and supports cover,
contain and optional still-image zoom. Narration and storyboard timing retain
their existing owners and contracts.

Example clip, inside `clips`:

```json
{
  "scene_id": "scene-01",
  "script_id": "script-01",
  "source": {"path": "assets/local.mp4", "sha256": "<exact64hex>"},
  "rights": {"path": "assets/local-rights.json", "sha256": "<exact64hex>"},
  "kind": "video",
  "use": "illustrative",
  "start_seconds": 0,
  "duration_seconds": 2,
  "fit": "cover"
}
```

The renderer copies stable exact inputs into a private temporary directory and
retains its actual FFmpeg argv. Its filter graph trims in the original source
clock, resets clip presentation timestamps, applies the selected fit, fixes
frame rate and concatenates in request order. It requires full MP4 decoding,
the requested dimensions and total duration within one requested frame of the
declared sum. The command and source/rights/codec hashes are retained with the
ordered recipe. A source test checks that recipe and the mocked boundary;
actual native ordering, visual fit, codec availability and playback remain
UNRUN. No factual or semantic correctness follows from decoding.

An evidentiary clip additionally pins an existing `EvidencePacket` and an exact
original source ID. Existing evidence validation checks original bytes and
observation record integrity. The binding must match the clip path, digest and
modality; a video span must fit inside a retained observed original interval.
The receipt preserves source revision, digest, packet digest and original
timestamps. Claims, paraphrases and semantic truth remain `not_verified` and
`factual_success` remains false. Downloaded stock materials remain illustrative.

## Rights and stock sources

`MaterialRights` requires `source_sha256`, `source_url`, `license`,
`license_url`, `credit`, timezone-aware `retrieved_at` and `valid_until`,
`principal`, and `clip_use_allowed`. Unknown, pending, empty and unlicensed
license declarations are refused. The rights file is checked before work and
again before final assembly/download success; an expired declaration cannot
be rescued by a cache hit. These are explicit caller retained declarations,
labelled `caller_declared_unverified` and `rights_verified: false`. They do not
authenticate a principal or independently verify an asset license.

Remote tools require a separate pinned project `StockConfig` JSON record with
`provider` (`pexels` or `pixabay`), `api_key_env`, exact `download_hosts`,
`principal`, explicit `search_allowed`/`download_allowed`, and an absolute
`valid_until`. Both permissions default to false. Configuration or principal
changes, absent credentials for search, stale permissions or missing clip
rights refuse work. Download needs independent clip-use permission and an
expected digest; a search response never supplies that permission. Credentials
are read from the named environment variable; no environment/account setting
is mutated and no credential is retained in receipts or page errors.

The search adapters use the endpoint and response shapes inspected in pinned
MoneyPrinterTurbo source: Pexels `/v1/videos/search` with Authorization and
`video_files`, and Pixabay `/api/videos/` with key query and `hits[].videos`.
Bounded `page` pagination is source tested against fixtures. The retained
upstream implementation itself does not demonstrate pagination, and no
official provider/API compatibility or live endpoint acceptance has been
verified in this lane. Root must qualify these contracts before native remote
admission. This is an independent implementation and is not a provider
recommendation or promise of available service.

Acquisition accepts only HTTPS with exact configured hosts, no userinfo or
nonstandard port, and public DNS addresses pinned to the TLS connection with
hostname verification. Authenticated search redirects are refused. Public
media redirects allow at most three hops, each checked against configured
hosts, without forwarding search credentials. Credential-bearing media URLs,
private addresses, malformed bodies, excessive metadata and non-200 responses
are refused; provider errors are not retried. Search exposes retained partial
results and the failed page when later pagination fails.

The HTTP/body budget is30seconds per search and20seconds per download, with
individual socket waits at most10seconds and checked remaining deadlines.
The platform DNS resolver is synchronous and cannot be cancelled by this
helper; its scheduling/IO and a hard whole-call DNS deadline are unqualified.
Thread cancellation does not certify termination of remote IO. Root's native
admission must assess this limitation; the source-only unit result makes no
claim of a fully bounded provider runtime.

## Manifest, cache and failure boundaries

`materials-manifest.json` is a versioned, atomically replaced project manifest,
bounded to1MiB and64combined output/download entries. Existing malformed or
oversized data is refused rather than reset. A download receipt retains initial
and final URL, exact SHA256, size, configuration pin, rights/license/credit,
retrieval time, illustrative use and `media_qualified: false`. Assembly receipts
retain the source list, ordered recipe, codec identities and MP4 qualification.
No second catalog, shadow database or persistent queue is introduced.

Download cache identity includes exact source URL/hash, configuration file pin,
caller and rights pin. Assembly identity includes exact source and rights pins,
ordered scene/script recipe, format and codec hashes. Restart reads the same
manifest. Every hit checks current source/output bytes and rights; assembly
also requalifies output and rechecks the current source configuration for
downloaded materials. A changed path, recipe, size, digest or permission cannot
produce cached success. Immutable hashes detect byte changes; they do not
authenticate the manifest or its author.

Outputs are new exclusive project-root leaves created through an owned
directory FD without following symlinks. Inputs reject absolute paths,
traversal, symlink components and unstable regular-file reads. Publication
refuses an existing output. Manifest failure retains the primary error and
attempts cleanup only while observed output bytes still match; a changed
output or cleanup failure stays an explicit `cleanup_liability`. A crash
between publication and manifest replacement may leave an orphan; it is not
final success and cannot be silently overwritten on retry. Existing path
helpers and cooperative locking do not establish hostile filesystem isolation
against every concurrent parent-directory substitution; independent review and
native qualification remain open.

Product bounds are16clips,300seconds total,120seconds per clip,64MiB per
source/output,128MiB aggregate assembly input,90seconds outer assembly deadline,
15seconds render attempt plus the existing qualifier budgets. Search has at
most3pages,128renditions/page,1MiB per response and1MiB retained metadata;
downloads have64MiB response ceilings. Source tests use only small fixtures,
each command bounded to90seconds,2MiB log,1GiB sampled main-process RSS and
16MiB aggregate test artifacts. Ambient dependency IO remains UNKNOWN.

## Original acceptance mapping and grant boundary

| Original criterion | Implemented source behavior | Retained source evidence | Native gate |
| --- | --- | --- | --- |
| C1 local fixture, scene/script IDs, ordered fitted output | Explicit IDs, exact snapshots, ordered trim/fit/concat recipe, duration and full-decode checks | Local order/reverse-order, fit, image motion, source mutation, admission and cancellation tests | Actual R217 local MP4 journey, visual order/fit and playback UNRUN |
| C2 stock search/download with pagination/errors/redirects | Explicit configured source/caller permission, typed metadata, partial page failures, pinned exact acquisition | Both provider fixture shapes, wrong hash, absent authority, redirect/DNS/body/deadline refusal tests | Provider API, pagination and DNS whole-call bounds UNRUN/unqualified |
| C3 URL/hash/license/credit/retrieval/use | Durable receipts and explicit original evidence clock/revision binding | Restart/cache provenance and original evidence span tests | Asset grants and factual/semantic truth unverified |
| C4 missing rights/provider cannot be final success; source/config cache identity | Rights/config/source/output rechecks before success; refused stale hits | Denied/expired/unknown rights, altered cache/source, source permission change, missing codec and atomic failure tests | Independent review, installed/public journey, adoption and native acceptance OPEN |

Design reference is `harry0703/MoneyPrinterTurbo` at
`44e6d5e11832beccc2c3ce6b139bf437e920bb6a`. Four passive raw source reads were
retained: `LICENSE`, `app/services/material.py`, `app/services/material_cache.py`
and `app/services/video.py`. Its MIT application grant was inspected before
source acquisition. No foreign code was copied/imported and no foreign runtime
dependency is required at startup. The project implementation follows this
repository's MIT license. Neither MIT grant supplies stock media rights,
provider terms, download authority, credit requirements or factual support.

The companion source server mounts `materials_server` from
`video_explainer_mcp.tools.materials` with the three exact contracts. Configured projects,
codecs, asset rights and source permissions require qualification before native admission.
The remote transport connects to the selected public DNS address with its actual IPv4 or
IPv6 socket family and retains TLS hostname validation. No new dependency or provider
activation is required. Root alone updates shared registry, inventory, ledger and native status.
