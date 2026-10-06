"""Actual project receipts and recipes with mocked codec/network boundaries only."""

from datetime import datetime, timedelta, timezone
import hashlib
import asyncio
import json
from pathlib import Path
import time
from urllib.parse import parse_qs, urlsplit

import pytest

from video_explainer_mcp import config, materials, materials_remote as remote, materials_render as render
from video_explainer_mcp.models.materials import MaterialsRequest, StockDownload, StockSearch
from video_explainer_mcp.tools.materials import (
    explainer_materials_assemble, explainer_materials_download, explainer_materials_search,
)


def sha(body):
    return hashlib.sha256(body).hexdigest()


def write_json(project, name, value):
    body = json.dumps(value, sort_keys=True).encode()
    (project / name).write_bytes(body)
    return {"path": name, "sha256": sha(body)}


@pytest.fixture
def project(tmp_path, monkeypatch):
    project = tmp_path / "fixture"
    project.mkdir()
    monkeypatch.setattr(config, "_config", config.ServerConfig(projects_path=str(tmp_path)))
    monkeypatch.setattr(remote.socket, "create_connection", lambda *a, **k: pytest.fail("Real network forbidden"))
    return project


def rights(project, source_sha, name="rights.json", url="project:clip.mp4", **changes):
    now = datetime.now(timezone.utc)
    value = {"source_sha256": source_sha, "source_url": url, "license": "First-party fixture license",
             "license_url": "project:license.txt", "credit": "Fixture author", "principal": "fixture-caller",
             "retrieved_at": (now - timedelta(hours=1)).isoformat(),
             "valid_until": (now + timedelta(hours=1)).isoformat(), "clip_use_allowed": True, **changes}
    return write_json(project, name, value)


def request(project):
    clips = []
    for i, data in enumerate((b"first-source", b"second-source")):
        path = f"clip-{i}.mp4"
        (project / path).write_bytes(data)
        clips.append({"scene_id": f"scene-{i}", "script_id": f"script-{i}",
                      "source": {"path": path, "sha256": sha(data)},
                      "rights": rights(project, sha(data), f"rights-{i}.json"),
                      "duration_seconds": 1.0, "fit": "cover" if i == 0 else "contain"})
    return MaterialsRequest(principal="fixture-caller", clips=clips)


@pytest.fixture
def codec(monkeypatch):
    commands = []
    pins = {"ffmpeg": {"path": "/mock/ffmpeg", "sha256": "a" * 64},
            "ffprobe": {"path": "/mock/ffprobe", "sha256": "b" * 64}}
    monkeypatch.setattr(render, "codec_executables", lambda: pins)

    async def process(command, timeout):
        commands.append(command)
        inputs = [Path(command[i + 1]).read_bytes() for i, part in enumerate(command) if part == "-i"]
        Path(command[-1]).write_bytes(b"mock-codec:" + b"|".join(inputs))
        assert timeout <= 15
        return b"", b""

    async def qualify(artifact, resolution):
        assert sha(Path(artifact["path"]).read_bytes()) == artifact["sha256"]
        assert resolution == "720p"
        return {"policy": "mp4-full-decode-v1", "full_decode": True,
                "artifact_sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"],
                "media": {"duration_seconds": 2.0}, "executables": pins}

    monkeypatch.setattr(render, "run_media_process", process)
    monkeypatch.setattr(render, "qualify_render", qualify)
    return commands, process


async def test_local_recipe_order_fit_and_restart_cache(project, codec):
    req = request(project)
    result = await explainer_materials_assemble("fixture", req)
    assert result["success"] and not result["cached"]
    assert [c["scene_id"] for c in result["recipe"]["request"]["clips"]] == ["scene-0", "scene-1"]
    assert [c["script_id"] for c in result["recipe"]["request"]["clips"]] == ["script-0", "script-1"]
    graph = codec[0][0][codec[0][0].index("-filter_complex") + 1]
    assert "crop=1280:720" in graph and "pad=1280:720" in graph
    assert "[v0][v1]concat=n=2:v=1:a=0[out]" in graph
    assert (project / result["path"]).read_bytes() == b"mock-codec:first-source|second-source"
    durable = json.loads((project / materials.MANIFEST).read_text())
    again = await explainer_materials_assemble("fixture", MaterialsRequest.model_validate(req.model_dump()))
    assert again["success"] and again["cached"] and len(codec[0]) == 1
    assert json.loads((project / materials.MANIFEST).read_text()) == durable
    assert again["factual_success"] is False


async def test_order_is_part_of_cache_identity(project, codec):
    req = request(project)
    first = await render.assemble_materials("fixture", req)
    reverse = req.model_copy(update={"clips": list(reversed(req.clips))})
    second = await render.assemble_materials("fixture", reverse)
    assert first["cache_key"] != second["cache_key"] and len(codec[0]) == 2
    assert (project / second["path"]).read_bytes().endswith(b"second-source|first-source")


@pytest.mark.parametrize("change", [{"clip_use_allowed": False}, {"valid_until": "2000-01-01T00:00:00Z"}])
async def test_rights_refusal_precedes_codec_work(project, codec, change):
    req = request(project)
    req.clips[0].rights = rights(project, req.clips[0].source.sha256, "rights-0.json", **change)
    result = await explainer_materials_assemble("fixture", req)
    assert "error" in result and codec[0] == []
    assert not (project / materials.MANIFEST).exists()


async def test_stale_rights_and_changed_cached_output_never_succeed(project, codec):
    req = request(project)
    first = await render.assemble_materials("fixture", req)
    path = project / first["path"]
    path.write_bytes(b"changed output")
    with pytest.raises(ValueError, match="Cached"):
        await render.assemble_materials("fixture", req)
    path.write_bytes(b"mock-codec:first-source|second-source")
    (project / req.clips[0].rights.path).write_text("{}")
    with pytest.raises(ValueError, match="Pinned"):
        await render.assemble_materials("fixture", req)
    assert len(codec[0]) == 1


@pytest.mark.parametrize("bad_path", ["../outside.mp4", "/absolute.mp4", "folder/link.mp4"])
async def test_path_escape_and_parent_symlink_refused(project, codec, tmp_path, bad_path):
    req = request(project)
    (project / "folder").symlink_to(tmp_path, target_is_directory=True)
    req.clips[0].source.path = bad_path
    result = await explainer_materials_assemble("fixture", req)
    assert "error" in result and codec[0] == []


async def test_source_mutation_during_codec_refuses_publication(project, codec, monkeypatch):
    req = request(project)

    async def mutate(command, timeout):
        result = await codec[1](command, timeout)
        (project / req.clips[0].source.path).write_bytes(b"changed original")
        return result

    monkeypatch.setattr(render, "run_media_process", mutate)
    with pytest.raises(ValueError, match="source"):
        await render.assemble_materials("fixture", req)
    assert not list(project.glob("materials-output-*")) and not (project / materials.MANIFEST).exists()


async def test_atomic_manifest_failure_preserves_previous_revision(project, codec, monkeypatch):
    req = request(project)
    first = await render.assemble_materials("fixture", req)
    before = (project / materials.MANIFEST).read_bytes()

    def fail(*args):
        raise OSError("injected atomic publication failure")

    monkeypatch.setattr(materials, "atomic_write", fail)
    req.clips.reverse()
    with pytest.raises(OSError, match="injected atomic"):
        await render.assemble_materials("fixture", req)
    assert (project / materials.MANIFEST).read_bytes() == before
    assert [p.name for p in project.glob("materials-output-*")] == [first["path"]]


async def test_duration_qualification_failure_is_not_final_success(project, codec, monkeypatch):
    req = request(project)

    async def short(*args):
        return {"media": {"duration_seconds": 1.9}}

    monkeypatch.setattr(render, "qualify_render", short)
    result = await explainer_materials_assemble("fixture", req)
    assert "error" in result and not (project / materials.MANIFEST).exists()


async def test_missing_codec_and_missing_evidence_refuse_before_work(project, codec, monkeypatch):
    req = request(project)
    req.clips[0].use = "evidentiary"
    result = await explainer_materials_assemble("fixture", req)
    assert "error" in result and codec[0] == []
    req.clips[0].use = "illustrative"

    def missing():
        raise FileNotFoundError("ffmpeg unavailable")

    monkeypatch.setattr(render, "codec_executables", missing)
    result = await explainer_materials_assemble("fixture", req)
    assert "error" in result and codec[0] == []


def stock_config(project, provider="pexels", **changes):
    return write_json(project, "stock-config.json", {
        "provider": provider, "api_key_env": "MATERIALS_FIXTURE_KEY", "download_hosts": ["cdn.example.com"],
        "principal": "fixture-caller", "search_allowed": True, "download_allowed": True,
        "valid_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), **changes})


@pytest.mark.parametrize("provider", ["pexels", "pixabay"])
async def test_search_pagination_and_protocol_errors_are_retained(project, monkeypatch, provider):
    cfg = stock_config(project, provider)
    monkeypatch.setenv("MATERIALS_FIXTURE_KEY", "PRIVATE-FIXTURE-KEY")
    calls = []
    variant = {"link": "https://cdn.example.com/clip.mp4", "url": "https://cdn.example.com/clip.mp4",
               "width": 1280, "height": 720}
    item = {"id": 42, "duration": 3, "video_files": [variant], "videos": {"large": variant}, "user": "Author"}

    def fetch(url, headers, hosts, limit, deadline):
        calls.append((url, headers))
        if parse_qs(urlsplit(url).query)["page"] == ["2"]:
            raise ValueError("HTTP429")
        return json.dumps({"videos": [item], "hits": [item]}).encode(), url

    monkeypatch.setattr(remote, "_fetch", fetch)
    result = await explainer_materials_search("fixture", StockSearch(config=cfg, principal="fixture-caller", query="rain", pages=3))
    assert result["success"] is False and result["failed_page"] == 2 and len(result["results"]) == 1
    assert len(calls) == 2 and result["results"][0]["use"] == "illustrative"
    assert "PRIVATE-FIXTURE-KEY" not in json.dumps(result)
    if provider == "pexels":
        assert calls[0][1]["Authorization"] == "PRIVATE-FIXTURE-KEY"
    else:
        assert "key=PRIVATE-FIXTURE-KEY" in calls[0][0]


async def test_download_rights_hash_restart_and_source_config_cache(project, monkeypatch):
    body = b"download-fixture-only"
    cfg = stock_config(project)
    url = "https://cdn.example.com/clip.mp4"
    ref = rights(project, sha(body), url=url)
    calls = []

    def fetch(*args):
        calls.append(args)
        return body, url

    monkeypatch.setattr(remote, "_fetch", fetch)
    req = StockDownload(config=cfg, rights=ref, principal="fixture-caller", url=url, expected_sha256=sha(body))
    first = await explainer_materials_download("fixture", req)
    assert first["success"] and first["use"] == "illustrative" and not first["media_qualified"]
    assert (project / first["path"]).read_bytes() == body and first["rights"]["credit"] == "Fixture author"
    again = await explainer_materials_download("fixture", StockDownload.model_validate(req.model_dump()))
    assert again["cached"] and len(calls) == 1
    req.config = stock_config(project, api_key_env="OTHER_FIXTURE_KEY")
    changed = await explainer_materials_download("fixture", req)
    assert changed["success"] and len(calls) == 2 and changed["path"] != first["path"]
    (project / req.rights.path).write_text("{}")
    refused = await explainer_materials_download("fixture", req)
    assert "error" in refused and len(calls) == 2


async def test_download_wrong_hash_and_missing_authority_leave_no_artifact(project, monkeypatch):
    cfg = stock_config(project, download_allowed=False)
    url = "https://cdn.example.com/clip.mp4"
    ref = rights(project, sha(b"expected"), url=url)
    calls = []
    monkeypatch.setattr(remote, "_fetch", lambda *a: (calls.append(a) or b"wrong", url))
    req = StockDownload(config=cfg, rights=ref, principal="fixture-caller", url=url, expected_sha256=sha(b"expected"))
    assert "error" in await explainer_materials_download("fixture", req) and calls == []
    req.config = stock_config(project)
    assert "error" in await explainer_materials_download("fixture", req) and len(calls) == 1
    assert not list(project.glob("materials-source-*")) and not (project / materials.MANIFEST).exists()


@pytest.fixture
def http_boundary(monkeypatch):
    responses, requests, sockets = [], [], []

    class Stream:
        def connect(self, address):
            self.address = address

        def settimeout(self, timeout):
            assert timeout > 0

        def close(self):
            self.closed = True

    class Connection:
        def __init__(self, *args, **kwargs):
            self.sock = None

        def request(self, method, path, headers):
            requests.append((path, headers))

        def getresponse(self):
            return responses.pop(0)

        def close(self):
            if self.sock:
                self.sock.close()

    class Response:
        def __init__(self, status=200, body=b"ok", location=None):
            self.status, self.body, self.location = status, body, location

        def getheader(self, name):
            return self.location

        def read1(self, size):
            chunk, self.body = self.body[:size], self.body[size:]
            return chunk

        def close(self):
            self.closed = True

    def connect(*args, **kwargs):
        stream = Stream()
        stream.closed = False
        sockets.append(stream)
        return stream

    class Context:
        def wrap_socket(self, stream, **kwargs):
            return stream

    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(remote.socket, "create_connection", connect)
    monkeypatch.setattr(remote.socket, "socket", lambda *a: connect())
    monkeypatch.setattr(remote.ssl, "create_default_context", Context)
    monkeypatch.setattr(remote.http.client, "HTTPSConnection", Connection)
    return responses, requests, sockets, Response


def test_real_fetch_control_flow_redirect_body_bound_and_close(http_boundary):
    responses, calls, sockets, response = http_boundary
    responses.extend([response(302, location="/next.mp4"), response(body=b"fixture")])
    body, url = remote._fetch("https://cdn.example.com/first.mp4", {}, ["cdn.example.com"], 10, time.monotonic() + 20)
    assert body == b"fixture" and url.endswith("/next.mp4") and len(calls) == 2
    assert all(s.closed for s in sockets)
    responses.append(response(body=b"too-many-bytes"))
    with pytest.raises(ValueError, match="bound"):
        remote._fetch(url, {}, ["cdn.example.com"], 3, time.monotonic() + 20)
    assert all(s.closed for s in sockets)


def test_public_ipv6_first_dns_uses_selected_sockaddr(http_boundary, monkeypatch):
    responses, calls, sockets, response = http_boundary
    address = ("2606:4700:4700::1111", 443, 0, 0)
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: [(remote.socket.AF_INET6, 1, 6, "", address)])
    selected = []
    original = remote.socket.create_connection

    def connect(address, **kwargs):
        host, port = address
        return original((host, port), **kwargs)

    monkeypatch.setattr(remote.socket, "create_connection", connect)

    def socket_(family, kind):
        selected.append((family, kind))
        stream = original((address[0], address[1]))
        stream.connect = lambda actual: selected.append(actual)
        return stream

    monkeypatch.setattr(remote.socket, "socket", socket_)
    responses.append(response(body=b"ipv6 fixture"))
    body, url = remote._fetch("https://cdn.example.com/clip.mp4", {}, ["cdn.example.com"], 32, time.monotonic() + 20)
    assert body == b"ipv6 fixture" and selected == [(remote.socket.AF_INET6, remote.socket.SOCK_STREAM), address]
    assert all(stream.closed for stream in sockets)


def test_foreign_redirect_private_dns_and_auth_redirect_refused(http_boundary, monkeypatch):
    responses, calls, sockets, response = http_boundary
    url = "https://cdn.example.com/clip.mp4"
    responses.append(response(302, location="https://evil.example/clip.mp4"))
    with pytest.raises(ValueError, match="allowed"):
        remote._fetch(url, {}, ["cdn.example.com"], 10, time.monotonic() + 20)
    assert len(calls) == 1 and all(s.closed for s in sockets)
    responses.append(response(302, location="/next"))
    with pytest.raises(ValueError, match="Authenticated"):
        remote._fetch(url, {"Authorization": "SECRET"}, ["cdn.example.com"], 10, time.monotonic() + 20)
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(ValueError, match="nonpublic"):
        remote._fetch(url, {}, ["cdn.example.com"], 10, time.monotonic() + 20)
    assert len(calls) == 2


def test_exclusive_output_symlink_is_not_followed(project, tmp_path):
    source = tmp_path / "private-render.mp4"
    source.write_bytes(b"new")
    unrelated = tmp_path / "unrelated.mp4"
    unrelated.write_bytes(b"original")
    (project / "output.mp4").symlink_to(unrelated)
    with pytest.raises(ValueError, match="symlink"):
        materials.publish(project, source, "output.mp4", sha(b"new"))
    assert unrelated.read_bytes() == b"original"


async def test_cancelled_codec_releases_admission_without_final_artifacts(project, codec, monkeypatch):
    req = request(project)

    async def hang(*args):
        await asyncio.sleep(100)

    monkeypatch.setattr(render, "run_media_process", hang)
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(render._assemble(project, req), timeout=0.01)
    assert not (project / materials.MANIFEST).exists() and not list(project.glob("materials-output-*"))
    monkeypatch.setattr(render, "run_media_process", codec[1])
    assert (await render.assemble_materials("fixture", req))["success"]


async def test_downloaded_material_requires_current_source_permission(project, codec, monkeypatch):
    body = b"downloaded fixture"
    cfg = stock_config(project)
    url = "https://cdn.example.com/clip.mp4"
    ref = rights(project, sha(body), url=url)
    monkeypatch.setattr(remote, "_fetch", lambda *a: (body, url))
    acquired = await remote.download_material("fixture", StockDownload(
        config=cfg, rights=ref, principal="fixture-caller", url=url, expected_sha256=sha(body)))
    req = request(project)
    req.clips[0].source = {"path": acquired["path"], "sha256": sha(body)}
    req.clips[0].rights = ref
    assert (await render.assemble_materials("fixture", req))["success"]
    stock_config(project, download_allowed=False)
    refused = await explainer_materials_assemble("fixture", req)
    assert "error" in refused and len(codec[0]) == 1


async def test_atomic_failure_keeps_primary_and_changed_output_cleanup_liability(project, codec, monkeypatch):
    req = request(project)

    def fail_publication(*args):
        output = next(project.glob("materials-output-*"))
        output.write_bytes(b"changed by other writer")
        raise OSError("primary publication failure")

    monkeypatch.setattr(materials, "atomic_write", fail_publication)
    result = await explainer_materials_assemble("fixture", req)
    assert "primary publication failure" in result["error"] and result["cleanup_liability"]
    assert next(project.glob("materials-output-*")).read_bytes() == b"changed by other writer"
    assert not (project / materials.MANIFEST).exists()


def test_expired_network_deadline_refuses_before_dns(http_boundary, monkeypatch):
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: pytest.fail("Expired work must not resolveDNS"))
    with pytest.raises(TimeoutError):
        remote._fetch("https://cdn.example.com/clip.mp4", {}, ["cdn.example.com"], 10, time.monotonic() - 1)


async def test_unconfigured_search_and_unknown_clip_license_refuse_before_work(project, codec, monkeypatch):
    cfg = stock_config(project, search_allowed=False)
    monkeypatch.setattr(remote, "_fetch", lambda *a: pytest.fail("Unauthorized source must not access network"))
    result = await explainer_materials_search("fixture", StockSearch(config=cfg, principal="fixture-caller", query="rain"))
    assert "error" in result
    req = request(project)
    req.clips[0].rights = rights(project, req.clips[0].source.sha256, "rights-0.json", license="unknown")
    assert "error" in await explainer_materials_assemble("fixture", req) and codec[0] == []


async def test_image_motion_is_in_the_actual_fitted_recipe(project, codec):
    req = request(project)
    clip = req.clips[0]
    (project / "clip.png").write_bytes(b"first-source")
    clip.source.path = "clip.png"
    clip.kind, clip.motion = "image", "zoom"
    result = await render.assemble_materials("fixture", req)
    command = codec[0][0]
    assert result["success"] and "-loop" in command and "-pattern_type" in command
    assert "zoompan=" in command[command.index("-filter_complex") + 1]
    assert result["recipe"]["request"]["clips"][0]["motion"] == "zoom"


async def test_evidence_preserves_original_identity_clock_and_refuses_unobserved_span(project, codec):
    req = request(project)
    clip = req.clips[0]
    spans = [{"start_ms": 0, "end_ms": 1000}]
    observation = json.dumps({"asset_sha256": clip.source.sha256, "revision": "original-r1",
                              "observed_intervals": spans, "passages": []})
    source = {"id": "original-video", "revision": "original-r1", "sha256": clip.source.sha256,
              "path": clip.source.path, "modality": "video", "asset_kind": "original",
              "snapshot": {"text": observation, "sha256": sha(observation.encode())},
              "observed_intervals": spans, "duration_ms": 1000}
    clip.evidence_packet = write_json(project, "evidence.json", {
        "packet_id": "materials-fixture-evidence", "sources": [source], "claims": [], "lineage": []})
    clip.evidence_source_id, clip.use = "original-video", "evidentiary"
    result = await render.assemble_materials("fixture", req)
    evidence = result["recipe"]["sources"][0]["evidence"]
    assert evidence["source_revision"] == "original-r1" and evidence["source_sha256"] == clip.source.sha256
    assert (evidence["original_start_ms"], evidence["original_end_ms"]) == (0, 1000)
    assert result["factual_success"] is False
    clip.start_seconds = 0.5
    refused = await explainer_materials_assemble("fixture", req)
    assert "error" in refused and len(codec[0]) == 1


async def test_busy_project_refuses_a_second_material_writer(project, codec):
    req = request(project)
    with render.plan_transaction(project, create=True):
        result = await explainer_materials_assemble("fixture", req)
        assert "busy" in result["error"] and codec[0] == []
    assert not (project / materials.MANIFEST).exists()


def test_http_cleanup_error_does_not_replace_primary_provider_failure(http_boundary):
    responses, calls, sockets, response = http_boundary

    class FailedClose(response):
        def close(self):
            raise OSError("secondary cleanup failure")

    responses.append(FailedClose(429))
    with pytest.raises(ValueError, match="status429") as failure:
        remote._fetch("https://cdn.example.com/clip.mp4", {}, ["cdn.example.com"], 10, time.monotonic() + 20)
    assert failure.value.__notes__ and len(calls) == 1 and all(s.closed for s in sockets)


def test_qualified_bytes_changed_before_publication_are_not_promoted(project, tmp_path):
    source = tmp_path / "qualified.mp4"
    expected = sha(b"qualified original")
    source.write_bytes(b"changed after qualification")
    with pytest.raises(ValueError, match="changed before publication"):
        materials.publish(project, source, "output.mp4", expected)
    assert not (project / "output.mp4").exists()
