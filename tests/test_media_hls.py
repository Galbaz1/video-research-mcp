"""Bounded HLS VOD acquisition with mocked HTTP and owned synthetic media."""

from __future__ import annotations

import hashlib
import asyncio
import json
import shutil
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest


def test_finite_media_playlist_retains_duration_segments_and_initialization():
    """Given a finite VOD, parsing binds its intervals and map to the final URL."""
    from video_research_mcp.media_hls_manifest import parse_manifest

    playlist = parse_manifest(
        '#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-MAP:URI="init.mp4"\n'
        "#EXTINF:1.25,\nfirst.m4s\n#EXTINF:2.0,\nsecond.m4s\n#EXT-X-ENDLIST\n",
        "https://media.example/redirected/list.m3u8",
    )
    assert playlist["duration_seconds"] == 3.25
    assert playlist["initialization_url"] == "https://media.example/redirected/init.mp4"
    assert playlist["segments"] == [
        {"url": "https://media.example/redirected/first.m4s", "duration": 1.25},
        {"url": "https://media.example/redirected/second.m4s", "duration": 2.0},
    ]


def test_master_playlist_retains_bounded_muxed_variant_candidates():
    """Given muxed variants, selection can use declared bandwidth without inference."""
    from video_research_mcp.media_hls_manifest import parse_manifest

    master = parse_manifest(
        "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=200000,RESOLUTION=640x360\nlarge.m3u8\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=100000,CODECS="avc1.42e01e,mp4a.40.2"\nsmall.m3u8\n',
        "https://media.example/master.m3u8",
    )
    assert master["variants"] == [
        {"url": "https://media.example/large.m3u8", "bandwidth": 200000},
        {"url": "https://media.example/small.m3u8", "bandwidth": 100000},
    ]


@pytest.mark.parametrize(
    ("body", "error"),
    [
        ("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nx.ts\n", "finite VOD"),
        ('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n', "Encrypted"),
        ("#EXTM3U\n#EXT-X-BYTERANGE:100@0\n", "Unsupported HLS tag"),
        ('#EXTM3U\n#EXT-X-MAP:URI="init",BYTERANGE="100@0"\n', "byte range"),
        ("#EXTM3U\n#EXT-X-PART:DURATION=1,URI=part.ts\n", "Unsupported HLS tag"),
        ("#EXTM3U\n#EXT-X-PLAYLIST-TYPE:EVENT\n", "EVENT"),
        ('#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=10,AUDIO="other"\nx.m3u8\n', "Separate"),
        ("#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=NaN\nx.m3u8\n", "bandwidth"),
        ("#EXTM3U\n#EXTINF:NaN,\nx.ts\n", "finite and positive"),
        ("#EXTM3U\n#EXTINF:0,\nx.ts\n", "finite and positive"),
        ("#EXTM3U\n#EXTINF:-1,\nx.ts\n", "finite and positive"),
        ("#EXTM3U\n#EXTINF:3601,\nx.ts\n", "3600 seconds"),
        ("#EXTM3U\n#EXTINF:1,\n#EXTINF:1,\nx.ts\n", "lacks a segment URI"),
        ("#EXTM3U\nx.ts\n", "lacks EXTINF"),
        ("#EXTM3U\n#EXT-X-ENDLIST\nx.ts\n", "after ENDLIST"),
        ("<html>sign in</html>", "missing EXTM3U"),
    ],
)
def test_unsupported_or_malformed_streams_are_precise(body, error):
    """Unsupported, incomplete and nonfinite streams never become acquisition candidates."""
    from video_research_mcp.media_hls_manifest import parse_manifest

    with pytest.raises(ValueError, match=error):
        parse_manifest(body, "https://media.example/list.m3u8")


def test_segment_population_is_bounded_before_any_download():
    """All 201 attempted segments belong in the rejected source's denominator."""
    from video_research_mcp.media_hls_manifest import parse_manifest

    body = "#EXTM3U\n#EXT-X-TARGETDURATION:1\n" + "#EXTINF:1,\nx.ts\n" * 201
    with pytest.raises(ValueError, match="200 segments"):
        parse_manifest(body + "#EXT-X-ENDLIST\n", "https://media.example/list.m3u8")
    boundary = "#EXTM3U\n#EXT-X-TARGETDURATION:18\n" + "#EXTINF:18,\nx.ts\n" * 200
    accepted = parse_manifest(boundary + "#EXT-X-ENDLIST\n", "https://media.example/list.m3u8")
    assert len(accepted["segments"]) == 200 and accepted["duration_seconds"] == 3600


class _Peer:
    def __init__(self, address="93.184.216.34"):
        self.address = address

    def get_extra_info(self, name):
        return (self.address, 443) if name == "server_addr" else None


def _mock_http(monkeypatch, routes):
    """Use the actual checked fetch path; only HTTP and DNS are synthetic."""
    import video_research_mcp.url_policy as policy

    calls, clients = [], []
    original = httpx.AsyncClient

    def handler(request):
        url = str(request.url)
        calls.append(url)
        route = routes[url]
        if isinstance(route, bytes):
            route = {"content": route}
        peer = route.get("peer", "93.184.216.34")
        body = (
            {"stream": route["stream"]}
            if "stream" in route
            else {"content": route.get("content", b"")}
        )
        return httpx.Response(
            route.get("status", 200),
            **body,
            headers=route.get("headers"),
            extensions={"network_stream": _Peer(peer)},
        )

    def client(**kwargs):
        clients.append(kwargs)
        return original(transport=httpx.MockTransport(handler), **kwargs)

    async def resolve(host):
        address = "127.0.0.1" if host == "private.example" else "93.184.216.34"
        return [(2, 1, 6, "", (address, 443))]

    monkeypatch.setattr(policy.httpx, "AsyncClient", client)
    monkeypatch.setattr(policy, "_resolve_dns", resolve)
    return calls, clients


async def _synthetic_hls(directory, container):
    """Generate three owned color segments with installed FFmpeg, without network."""
    from video_research_mcp.media_process import run_media_process

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("Locally installed FFmpeg/ffprobe required for owned media fixture")
    directory.mkdir()
    suffix = "ts" if container == "mpegts" else "m4s"
    command = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=32x32:r=2:d=3",
        "-an",
        "-c:v",
        "libx264",
        "-g",
        "2",
        "-keyint_min",
        "2",
        "-sc_threshold",
        "0",
        "-f",
        "hls",
        "-hls_time",
        "1",
        "-hls_playlist_type",
        "vod",
        "-hls_segment_type",
        container,
        "-hls_segment_filename",
        str(directory / f"segment-%d.{suffix}"),
        str(directory / "list.m3u8"),
    ]
    await run_media_process(command, 5, cwd=directory)
    return {file.name: file.read_bytes() for file in directory.iterdir() if file.is_file()}


async def _decode_owned_output(output):
    """Decode only our owned fixture; production acquisition does not claim this check."""
    from video_research_mcp.media_process import run_media_process

    await run_media_process(
        [
            shutil.which("ffmpeg"),
            "-nostdin",
            "-v",
            "error",
            "-protocol_whitelist",
            "file",
            "-i",
            str(output),
            "-f",
            "null",
            "-",
        ],
        5,
    )


@pytest.mark.parametrize("container", ["mpegts", "fmp4"])
async def test_checked_master_redirect_segments_remux_and_decode(
    container, tmp_path, monkeypatch, clean_config
):
    """A checked mocked source becomes playable local MP4 with exact acquisition lineage."""
    from video_research_mcp.media_hls import acquire_hls

    files = await _synthetic_hls(tmp_path / "synthetic", container)
    start = "https://media.example/master.m3u8?token=private"
    final = "https://media.example/cdn/master.m3u8?token=private"
    master = (
        b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=20\nlarge/list.m3u8\n"
        b"#EXT-X-STREAM-INF:BANDWIDTH=10\nsmall/list.m3u8\n"
    )
    routes = {start: {"status": 307, "headers": {"location": final}}, final: master}
    routes.update({f"https://media.example/cdn/small/{name}": data for name, data in files.items()})
    calls, clients = _mock_http(monkeypatch, routes)
    staging = tmp_path / "staging"
    staging.mkdir()
    sentinel = staging / "unrelated.txt"
    sentinel.write_text("preserve caller files")
    result = await acquire_hls(start, staging)
    output, provenance = result["path"], result["provenance"]
    assert output.is_file() and output.suffix == ".mp4"
    assert provenance["segment_count"] == 3 and provenance["manifest_depth"] == 1
    assert provenance["duration_seconds"] == 3
    assert provenance["output"]["sha256"] == hashlib.sha256(output.read_bytes()).hexdigest()
    assert provenance["downloaded_bytes"] == sum(
        resource["bytes"] for resource in provenance["resources"]
    )
    assert all("token" not in resource["requested_url"] for resource in provenance["resources"])
    assert provenance["source_url"] == "https://media.example/master.m3u8"
    assert provenance["decoded_media"] == "unverified" and provenance["rights"] == "unknown"
    assert provenance["ffmpeg_network"] == "disabled"
    assert not any("/large/" in url for url in calls)
    assert all(not client["follow_redirects"] and not client["trust_env"] for client in clients)
    assert sentinel.read_text() == "preserve caller files"
    local = output.parent / "local.m3u8"
    assert "https:" not in local.read_text() and "token=" not in local.read_text()
    await _decode_owned_output(output)


def _vod(*urls, initialization=None):
    lines = ["#EXTM3U", "#EXT-X-TARGETDURATION:1"]
    if initialization:
        lines.append(f'#EXT-X-MAP:URI="{initialization}"')
    for url in urls:
        lines.extend(("#EXTINF:1,", url))
    return ("\n".join([*lines, "#EXT-X-ENDLIST"]) + "\n").encode()


def _native_mock(monkeypatch, probe=None, output=b"owned synthetic output"):
    """Mock only the optional native executable boundary for failure-shape tests."""
    import video_research_mcp.media_process as process

    async def run(command, timeout, *, cwd=None):
        assert command[command.index("-protocol_whitelist") + 1] == "file"
        if Path(command[0]).name == "ffmpeg":
            assert not any(value.startswith(("https:", "http:")) for value in command)
            Path(command[-1]).write_bytes(output)
            return b"", b""
        result = (
            probe
            if probe is not None
            else {
                "format": {"duration": "1"},
                "streams": [{"codec_type": "video", "codec_name": "h264"}],
            }
        )
        return json.dumps(result).encode(), b""

    native = AsyncMock(side_effect=run)
    monkeypatch.setattr(process, "run_media_process", native)
    return native


@pytest.mark.parametrize("derived", ["variant", "initialization", "segment"])
async def test_private_derived_resources_are_blocked_before_fetch(
    derived, tmp_path, monkeypatch, clean_config
):
    """Every selected resource uses the root URL policy, including maps and variants."""
    from video_research_mcp.media_hls import acquire_hls
    from video_research_mcp.url_policy import UrlPolicyError

    unsafe = "https://private.example/resource"
    body = (
        f"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n{unsafe}\n".encode()
        if derived == "variant"
        else _vod(
            unsafe if derived == "segment" else "ok.ts",
            initialization=unsafe if derived == "initialization" else None,
        )
    )
    calls, _ = _mock_http(monkeypatch, {"https://media.example/list.m3u8": body})
    native = _native_mock(monkeypatch)
    with pytest.raises(UrlPolicyError, match="blocked IP"):
        await acquire_hls("https://media.example/list.m3u8", tmp_path)
    assert calls == ["https://media.example/list.m3u8"]
    native.assert_not_awaited()
    assert not list(tmp_path.glob("hls-*"))


@pytest.mark.parametrize("violation", ["private_peer", "private_redirect", "http", "credentials"])
async def test_derived_segment_transport_cannot_bypass_policy(
    violation, tmp_path, monkeypatch, clean_config
):
    """Derived media cannot bypass connected-peer, redirect, scheme or credential checks."""
    from video_research_mcp.media_hls import acquire_hls
    from video_research_mcp.url_policy import UrlPolicyError

    url = "https://media.example/segment.ts"
    resource = {"content": b"unfetched private media", "peer": "127.0.0.1"}
    if violation == "private_redirect":
        resource = {"status": 302, "headers": {"location": "https://private.example/secret"}}
    elif violation == "http":
        url = "http://media.example/segment.ts"
    elif violation == "credentials":
        url = "https://user:secret@media.example/segment.ts"
    calls, _ = _mock_http(
        monkeypatch, {"https://media.example/list.m3u8": _vod(url), url: resource}
    )
    native = _native_mock(monkeypatch)
    with pytest.raises(UrlPolicyError):
        await acquire_hls("https://media.example/list.m3u8", tmp_path)
    assert not any("private.example" in call for call in calls)
    assert len(calls) == (2 if violation in {"private_peer", "private_redirect"} else 1)
    native.assert_not_awaited()
    assert not list(tmp_path.glob("hls-*"))


@pytest.mark.parametrize(
    "failure", ["depth", "cycle", "aggregate_bytes", "manifest_bytes", "not_media", "invalid_utf8"]
)
async def test_resource_graph_and_byte_limits_cleanup(failure, tmp_path, monkeypatch, clean_config):
    """A rejected graph never invokes native media and removes only its owned partial files."""
    from video_research_mcp.media_hls import acquire_hls
    from video_research_mcp.url_policy import UrlPolicyError

    base = "https://media.example/"
    master = b"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\n"
    ts = (b"G" + b"\0" * 187) * 2
    routes = {
        base + "list.m3u8": _vod("one.ts", "two.ts"),
        base + "one.ts": ts,
        base + "two.ts": ts,
    }
    error = "size limit"
    if failure == "depth":
        routes = {
            base + "list.m3u8": master + b"second.m3u8\n",
            base + "second.m3u8": master + b"third.m3u8\n",
            base + "third.m3u8": master + b"fourth.m3u8\n",
        }
        error = "depth 2"
    elif failure == "cycle":
        routes = {base + "list.m3u8": master + b"list.m3u8\n"}
        error = "cycle"
    elif failure == "aggregate_bytes":
        monkeypatch.setenv(
            "MEDIA_MAX_INPUT_BYTES", str(len(routes[base + "list.m3u8"]) + 2 * len(ts) - 1)
        )
    elif failure == "manifest_bytes":
        routes = {base + "list.m3u8": b"#EXTM3U\n" + b"#comment\n" * 16384}
    elif failure == "invalid_utf8":
        routes = {base + "list.m3u8": b"#EXTM3U\n\xff"}
        error = "UTF-8"
    else:
        routes[base + "one.ts"] = b"#EXTM3U\nfile:///etc/passwd\n"
        error = "container"
    calls, _ = _mock_http(monkeypatch, routes)
    native = _native_mock(monkeypatch)
    sentinel = tmp_path / "caller-owned.txt"
    sentinel.write_text("keep")
    with pytest.raises((ValueError, UrlPolicyError), match=error):
        await acquire_hls(base + "list.m3u8", tmp_path)
    native.assert_not_awaited()
    assert not any("fourth.m3u8" in call for call in calls)
    assert not list(tmp_path.glob("hls-*"))
    assert sentinel.read_text() == "keep"


@pytest.mark.parametrize(
    "probe",
    [
        None,
        {"streams": [], "format": {"duration": "1"}},
        {"streams": [{"codec_type": "video"}], "format": {"duration": "NaN"}},
        {"streams": [{"codec_type": "video"}], "format": {"duration": "100"}},
        {"streams": [{"codec_type": "video"}], "format": {"duration": "0.2"}},
        {"streams": [{"codec_type": "video"}], "format": {"duration": "3601"}},
        {"streams": [{"codec_type": "video"}], "format": {}},
    ],
)
async def test_probe_errors_cannot_report_acquired_media(
    probe, tmp_path, monkeypatch, clean_config
):
    """Container metadata errors retain a failed acquisition rather than a usable asset."""
    from video_research_mcp.media_hls import acquire_hls

    base = "https://media.example/"
    _mock_http(
        monkeypatch, {base + "list.m3u8": _vod("one.ts"), base + "one.ts": (b"G" + b"\0" * 187) * 2}
    )
    if probe is None:
        monkeypatch.setenv("MEDIA_MAX_INPUT_BYTES", "1024")
    _native_mock(monkeypatch, probe=probe, output=b"x" * 2048 if probe is None else b"owned output")
    with pytest.raises(ValueError, match="HLS remux"):
        await acquire_hls(base + "list.m3u8", tmp_path)
    assert not list(tmp_path.glob("hls-*"))


class _PendingBody(httpx.AsyncByteStream):
    """Expose partial bytes, then wait so timeout/cancel cleanup is observable."""

    def __init__(self):
        self.started = asyncio.Event()

    async def __aiter__(self):
        yield b"#EXTM3U\n"
        self.started.set()
        await asyncio.Event().wait()


@pytest.mark.parametrize("stop", ["timeout", "cancel"])
async def test_overall_timeout_and_cancellation_remove_partial_download(
    stop, tmp_path, monkeypatch, clean_config
):
    """One acquisition clock and cancellation both clean their partial owned transport bytes."""
    from video_research_mcp.media_hls import acquire_hls

    monkeypatch.setenv("MEDIA_ACQUIRE_TIMEOUT_SECONDS", "1")
    stream = _PendingBody()
    _mock_http(monkeypatch, {"https://media.example/list.m3u8": {"stream": stream}})
    native = _native_mock(monkeypatch)
    task = asyncio.create_task(acquire_hls("https://media.example/list.m3u8", tmp_path))
    await asyncio.wait_for(stream.started.wait(), 1)
    if stop == "cancel":
        task.cancel()
    with pytest.raises(TimeoutError if stop == "timeout" else asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    native.assert_not_awaited()
    assert not list(tmp_path.glob("hls-*"))


async def test_missing_runtime_fails_before_any_remote_request(tmp_path, monkeypatch, clean_config):
    """Missing optional binaries are actionable and do not start acquisition."""
    from video_research_mcp.media_hls import acquire_hls

    calls, _ = _mock_http(monkeypatch, {})
    monkeypatch.setattr("video_research_mcp.media_hls.shutil.which", lambda name: None)
    with pytest.raises(FileNotFoundError, match="ffmpeg and ffprobe"):
        await acquire_hls("https://media.example/list.m3u8", tmp_path)
    assert calls == [] and not list(tmp_path.glob("hls-*"))
