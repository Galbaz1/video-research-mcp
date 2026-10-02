# Media source acquisition and owned assets

The root server provides source inspection, metadata retrieval, bounded video
acquisition and persistent exact-byte assets. Acquisition returns a local path
that the existing `video_analyze` tool can consume. Metadata and acquisition
perform no Gemini inference or File API upload.

## Entry points

| Capability from the pinned inventory | Implemented entry point |
| --- | --- |
| `get_metadata`, `inspectVideo` | Existing `video_metadata` for YouTube; `media_metadata` for local, direct, HLS and Loom source metadata |
| `inspectChannel` | `youtube_channel_inspect` through YouTube Data API v3 |
| `listChannelCatalog` | `youtube_channel_catalog`, one uploads page with an explicit continuation token |
| `inspectVideoSource` | `media_source_inspect`, syntax-only routing with access unverified |
| `downloadAsset` | `media_acquire`, a bounded video asset with a full SHA-256 identity |
| `listMediaAssets` | `media_assets_list`, an identity-ordered page and explicit byte-verification state |
| `removeMediaAsset` | `media_asset_remove`, an exact catalog identity and owned-file deletion receipt |
| `watch_video` | `media_acquire` followed by existing `video_analyze(file_path=asset.path)` |

The three mapped workflows use these same entry points: acquire a platform video
and reuse its catalog path across restarts; choose a YouTube/Loom/direct/local
adapter; acquire a finite stream manifest or local source for analysis. This
slice transfers video acquisition and source lifecycle. Source options for audio
extraction, thumbnails/keyframes, browser capture and other social platforms have
separate programme owners; these tools do not advertise those options.

## Source boundaries

`media_source_inspect` reads no bytes and performs no DNS lookup. It classifies
canonical YouTube IDs, Loom share/embed URLs, supported local video extensions,
HTTPS direct video URLs and `.m3u8` stream URLs. Unsupported sources receive a
specific routing result; classification does not prove access or media quality.

`media_metadata` performs a checked HEAD for direct video and stream URLs.
YouTube uses Data API metadata. Local inputs use bounded local ffprobe and retain
a source digest. Loom accepts at most one MiB of HTML/JSON metadata containing an
explicit Open Graph video or `VideoObject.contentUrl`. The GET response type is
checked before its body is read. Authentication pages or changed metadata shapes
return an actionable error. The pinned upstream audit contains a Loom adapter
registration, but lacks its body; this parser is independently authored and live
platform compatibility remains unverified.

Every HTTP request checks HTTPS, DNS, each redirect and the actual connected
public peer. Environment proxy routing is disabled for this checked transport.
Body limits apply to streamed bytes, including responses with missing or misleading
Content-Length headers. Metadata headers remain provider claims.

YouTube downloads require an independently installed yt-dlp. The subprocess only
receives an eleven-character video ID in a canonical YouTube URL. User yt-dlp
configuration is ignored, retries are disabled, video dimensions are capped at
720p/1280 pixels and the configured byte limit is passed and checked again.
Optional cookies come only from an explicitly configured local file. No browser
cookie discovery runs. New downloads retain an exact SHA-256/byte-count/ID sidecar;
old cache entries without that receipt have unknown provenance and require an
explicit cache cleanup before retrying. Downloaded sessions use the actual content
digest for upload and context-cache identity.

HLS supports finite, unencrypted muxed MPEG-TS and fragmented-MP4 VOD. It follows
at most two master selections, downloads at most 200 segments and accepts at most
3600 seconds of declared duration. All resources share one aggregate byte limit
and timeout. Checked downloaded resources become generated local filenames;
FFmpeg receives a local-only rewritten manifest. Live streams, encryption,
byte ranges, external audio renditions and unsupported playlist tags fail with
specific errors. Probe results and retained digests are distinct from full media
decode or factual verification.

## Configuration and ownership

- `MEDIA_MAX_INPUT_BYTES` bounds input/download bytes; default 512 MiB.
- `MEDIA_ACQUIRE_TIMEOUT_SECONDS` bounds acquisition; default 120 seconds,
  configurable from one second to one hour.
- `MEDIA_COOKIES_FILE` optionally selects a nonempty regular cookies file of at
  most one MiB within `LOCAL_FILE_ACCESS_ROOT`.
- `GEMINI_CACHE_DIR/media` owns a private SQLite catalog, immutable content objects
  and temporary staging. No external storage service is required.
- Set `GEMINI_CACHE_DIR` inside `LOCAL_FILE_ACCESS_ROOT` when using that fence and
  analyzing acquired paths. Acquisition does not widen the analysis file fence.

Catalog adoption copies originals into owned storage. Exact bytes at another
source path reuse one object and retain source aliases. A catalog row alone does
not prove bytes: reuse and deletion check the current regular file and full digest.
Removal accepts an asset SHA-256, never an arbitrary path, and invalidates source
result caches. Original files remain intact. Missing or corrupt owned assets retain
explicit unhealthy states, preserving the page denominator when an owned slot is
unreadable, replaced by a symlink or nonregular, or missing. Listing verifies at
most the configured aggregate input byte ceiling per page; remaining records
retain unknown state and a budget reason.

Each asset retains at most 64 KiB of serialized source receipts. Admission at
capacity fails before committing or discarding history. SQL length guards reject
oversized stored receipts before their payload reaches Python. A page reads at
most one MiB of receipt metadata and returns a result dictionary whose serialized
JSON is at most one MiB; MCP may carry both text and structured copies. Selected
rows whose metadata cannot fit remain visible with explicit omission reasons.
Signed query values and fragments are redacted from public provenance; alias
hashes preserve locator identity without exposing them. Long credential-free
metadata is processed without restarting credential matches inside each token.

Subprocesses cap stdout and stderr at one MiB each. Timeout/cancellation terminates
and reaps the actual invocation's owned process group, including children retaining
pipes after their leader exits. Failed acquisition removes only its own staging.
Repeated cancellation during launch retains the actual process handle through
cleanup. Cached media and receipt reads reject named pipes and other nonregular
files before reading; they cannot leave a cache worker blocked on a FIFO.

## Evidence and reuse

The transfer inventory pins `guimatheus92/mcp-video-analyzer` at
`9e476c02f8426f5c277ed5e7f5729c1aee75b31a`, with supporting capability references to
`thatsrajan/vidlens-mcp` at `edd1d9fba8cf2364343b4cbd07378a649f956f08` and
`oxbshw/watch-skill` at `f1317c8fe64744a606c31867b05fbbe3144268c6`. Their verified MIT
grants are retained in the reuse ledger. This Python implementation copies no
external source body, media, weights or executable. ffmpeg/ffprobe/yt-dlp remain
independently installed optional runtimes; code grants do not establish media or
platform download rights.

Unit fixtures and real local FFmpeg/SQLite/MCP journeys verify adapter contracts,
byte commitments, restart reuse, cleanup, deletion and transport limits. Provider
calls remain mocked. They establish no live platform/inference result, held-out
comparison, human audit or distribution-release acceptance. Exact output/source
receipts live under the programme's private evidence directory and in Beads.
