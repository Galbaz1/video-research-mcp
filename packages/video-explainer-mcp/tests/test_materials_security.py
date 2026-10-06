"""Stock credential refusal and joined cancellation with mocked network boundaries."""

import asyncio
from contextvars import ContextVar
import json
from threading import Event
from datetime import datetime, timedelta, timezone
import hashlib
import time

import pytest

from video_explainer_mcp import config, materials, materials_remote as remote
from video_explainer_mcp.models.materials import StockDownload, StockSearch
from video_explainer_mcp.tools.materials_stock import explainer_materials_download, explainer_materials_search


def sha(body):
    return hashlib.sha256(body).hexdigest()


def write_json(project, name, value):
    body = json.dumps(value, sort_keys=True).encode()
    (project / name).write_bytes(body)
    return {"path": name, "sha256": sha(body)}


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = tmp_path / "fixture"
    root.mkdir()
    monkeypatch.setattr(config, "_config", config.ServerConfig(projects_path=str(tmp_path)))
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: pytest.fail("Real DNS forbidden"))
    return root


def stock_config(project, provider="pexels", **changes):
    return write_json(project, "stock-config.json", {
        "provider": provider, "api_key_env": provider.upper() + "_API_KEY",
        "download_hosts": ["cdn.example.com"], "principal": "fixture-caller",
        "search_allowed": True, "download_allowed": True,
        "valid_until": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(), **changes})


def rights(project, digest, url):
    now = datetime.now(timezone.utc)
    return write_json(project, "rights.json", {"source_sha256": digest, "source_url": url,
        "license": "Fixture license", "license_url": "project:license.txt", "credit": "Fixture",
        "principal": "fixture-caller", "retrieved_at": (now - timedelta(hours=1)).isoformat(),
        "valid_until": (now + timedelta(hours=1)).isoformat(), "clip_use_allowed": True})


CREDENTIAL_KEYS = [
    "", "%20", "%09", "%0D%0A", "+", "%20%09",
    "key", "token", "signature", "api_key", "auth", "access_token",
    "X-Amz-Signature", "X-Goog-Signature", "X-Amz-Credential", "X-Goog-Credential",
    "X-Amz-Security-Token", "AWSAccessKeyId", "credentials", "client_secret",
    "refresh_token", "password", "Authorization", "access-key", "apiKey", "passwd", "bearer", "authentication",
]


@pytest.mark.parametrize("name", CREDENTIAL_KEYS)
@pytest.mark.parametrize("value", ["", "SYNTHETIC_GRANT"])
def test_credential_urls_refused_before_dns(monkeypatch, name, value):
    """Credential parameter names are refused even with blank values or headers."""
    url = f"https://cdn.example.com/clip.mp4?{name}={value}"
    monkeypatch.setattr(remote.socket, "getaddrinfo", lambda *a, **k: pytest.fail("DNS forbidden"))
    with pytest.raises(ValueError, match="Credential-bearing"):
        remote.public_url(url, ["cdn.example.com"])
    with pytest.raises(ValueError, match="Credential-bearing"):
        remote._fetch(url, {"Accept": "video/mp4"}, ["cdn.example.com"], 20, time.monotonic() + 20)


@pytest.mark.parametrize("name", CREDENTIAL_KEYS)
@pytest.mark.parametrize("value", ["", "SYNTHETIC_GRANT"])
async def test_download_credential_url_refused_before_receipt_or_fetch(project, monkeypatch, name, value):
    url = f"https://cdn.example.com/clip.mp4?{name}={value}"
    req = StockDownload(config=stock_config(project), rights=rights(project, sha(b"body"), url=url),
                        principal="fixture-caller", url=url, expected_sha256=sha(b"body"))
    def forbidden(*args):
        pytest.fail("Credential URL must be refused before lookup or network")
    monkeypatch.setattr(remote, "rights_receipt", forbidden)
    monkeypatch.setattr(remote, "load_manifest", forbidden)
    monkeypatch.setattr(remote, "_fetch", forbidden)
    result = await explainer_materials_download("fixture", req)
    assert "error" in result and "SYNTHETIC_GRANT" not in json.dumps(result)
    assert not (project / materials.MANIFEST).exists() and not list(project.glob("materials-source-*"))


@pytest.mark.parametrize("provider", ["pexels", "pixabay"])
@pytest.mark.parametrize("name", ["access_token", "X-Amz-Signature", "X-Goog-Signature", "credentials"])
@pytest.mark.parametrize("value", ["", "SYNTHETIC_GRANT"])
async def test_search_credential_rendition_never_enters_results(project, monkeypatch, provider, name, value):
    monkeypatch.setenv(provider.upper() + "_API_KEY", "SYNTHETIC_PROVIDER_KEY")
    cfg = stock_config(project, provider)
    url = f"https://cdn.example.com/clip.mp4?{name}={value}"
    variant = {"link": url, "url": url, "width": 1280, "height": 720}
    item = {"id": 1, "duration": 1, "video_files": [variant], "videos": {"large": variant}}
    calls = []
    def fetch(*args):
        calls.append(args)
        return json.dumps({"videos": [item], "hits": [item]}).encode(), args[0]
    monkeypatch.setattr(remote, "_fetch", fetch)
    result = await explainer_materials_search("fixture", StockSearch(
        config=cfg, principal="fixture-caller", query="rain", pages=3))
    assert not result["success"] and result["results"] == [] and len(calls) == 1
    assert "SYNTHETIC_GRANT" not in json.dumps(result) and name not in json.dumps(result)
    assert not (project / materials.MANIFEST).exists()


@pytest.mark.parametrize("provider", ["pexels", "pixabay"])
async def test_arbitrary_environment_slot_refused_before_lookup(project, monkeypatch, provider):
    cfg = stock_config(project, provider, api_key_env="UNRELATED_SYNTHETIC_SECRET")
    class NoLookup(dict):
        def get(self, name, default=None):
            pytest.fail("Invalid provider slot must be refused before environment lookup")
    monkeypatch.setattr(remote.os, "environ", NoLookup())
    monkeypatch.setattr(remote, "_fetch", lambda *a: pytest.fail("Fetch forbidden"))
    result = await explainer_materials_search("fixture", StockSearch(
        config=cfg, principal="fixture-caller", query="rain"))
    assert "error" in result


async def test_redirect_final_url_refused_before_publication(project, monkeypatch):
    url = "https://cdn.example.com/clip.mp4"
    req = StockDownload(config=stock_config(project), rights=rights(project, sha(b"body"), url=url),
                        principal="fixture-caller", url=url, expected_sha256=sha(b"body"))
    monkeypatch.setattr(remote, "_fetch", lambda *a: (b"body", url + "?access_token=SYNTHETIC_GRANT"))
    result = await explainer_materials_download("fixture", req)
    assert "error" in result and "SYNTHETIC_GRANT" not in json.dumps(result)
    assert not (project / materials.MANIFEST).exists() and not list(project.glob("materials-source-*"))


@pytest.mark.parametrize("operation", ["search", "download"])
@pytest.mark.parametrize("fetch_error", [False, True])
async def test_cancelled_worker_is_joined_before_terminal_result(project, monkeypatch, operation, fetch_error):
    """A cancelled await waits for the blocked worker and prevents pages/publication."""
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release, terminal = Event(), Event()
    calls = []
    url = "https://cdn.example.com/clip.mp4"
    monkeypatch.setenv("PEXELS_API_KEY", "SYNTHETIC_PROVIDER_KEY")
    cfg = stock_config(project)
    if operation == "download":
        req = StockDownload(config=cfg, rights=rights(project, sha(b"body"), url=url),
                            principal="fixture-caller", url=url, expected_sha256=sha(b"body"))
        invoke, worker_name = explainer_materials_download, "_download"
    else:
        req = StockSearch(config=cfg, principal="fixture-caller", query="rain", pages=3)
        invoke, worker_name = explainer_materials_search, "_search"
    original = getattr(remote, worker_name)
    def worker(*args):
        try:
            return original(*args)
        finally:
            terminal.set()
    monkeypatch.setattr(remote, worker_name, worker)
    def fetch(*args):
        calls.append(args)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(3):
            raise TimeoutError("Test release barrier expired")
        if fetch_error:
            raise OSError("controlled fetch failure")
        return (b"body" if operation == "download" else b'{"videos": []}'), url
    monkeypatch.setattr(remote, "_fetch", fetch)
    task = asyncio.create_task(invoke("fixture", req))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done() and not terminal.is_set()
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await asyncio.wait_for(task, 2)
        assert terminal.is_set() and len(calls) == 1
        assert any("joined" in note for note in cancelled.value.__notes__)
        assert not (project / materials.MANIFEST).exists() and not list(project.glob("materials-source-*"))
        await asyncio.sleep(0)
        assert not (project / materials.MANIFEST).exists() and len(calls) == 1
    finally:
        release.set()
        if not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.parametrize("stage", ["publish", "save_manifest"])
async def test_cancellation_publication_race_has_terminal_disposition(project, monkeypatch, stage):
    """Cancellation rolls back an uncommitted asset or retains an already committed receipt."""
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    release, terminal = Event(), Event()
    url = "https://cdn.example.com/clip.mp4"
    req = StockDownload(config=stock_config(project), rights=rights(project, sha(b"body"), url=url),
                        principal="fixture-caller", url=url, expected_sha256=sha(b"body"))
    monkeypatch.setattr(remote, "_fetch", lambda *a: (b"body", url))
    original = getattr(remote, stage)
    def barrier(*args):
        result = original(*args)
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(3):
            raise TimeoutError("Test commit barrier expired")
        return result
    monkeypatch.setattr(remote, stage, barrier)
    download = remote._download
    def worker(*args):
        try:
            return download(*args)
        finally:
            terminal.set()
    monkeypatch.setattr(remote, "_download", worker)
    task = asyncio.create_task(explainer_materials_download("fixture", req))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await asyncio.wait_for(task, 2)
        assert terminal.is_set()
        if stage == "publish":
            assert not (project / materials.MANIFEST).exists()
            assert not list(project.glob("materials-source-*"))
        else:
            assert (project / materials.MANIFEST).exists()
            assert len(list(project.glob("materials-source-*"))) == 1
            assert any("completion won cancellation race" in note for note in cancelled.value.__notes__)
        before = {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
        await asyncio.sleep(0)
        assert before == {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
    finally:
        release.set()
        if not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass


@pytest.mark.parametrize("operation,stage", [
    ("search", "fetch"), ("download", "fetch"),
    ("download", "publish"), ("download", "save_manifest"),
])
async def test_shutdown_cancellation_joins_executor_future(project, monkeypatch, operation, stage):
    """Cancel every operation-owned Task at shutdown while its executor callback is blocked."""
    loop = asyncio.get_running_loop()
    baseline = asyncio.all_tasks()
    entered = asyncio.Event()
    release, terminal = Event(), Event()
    context = ContextVar("stock-worker-context", default="missing")
    token = context.set("R485-context")
    url = "https://cdn.example.com/clip.mp4"
    monkeypatch.setenv("PEXELS_API_KEY", "SYNTHETIC_PROVIDER_KEY")
    cfg = stock_config(project)
    if operation == "search":
        req = StockSearch(config=cfg, principal="fixture-caller", query="rain", pages=3)
        invoke, name = explainer_materials_search, "_search"
    else:
        req = StockDownload(config=cfg, rights=rights(project, sha(b"body"), url=url),
                            principal="fixture-caller", url=url, expected_sha256=sha(b"body"))
        invoke, name = explainer_materials_download, "_download"
    original = getattr(remote, name)
    def worker(*args):
        try:
            assert context.get() == "R485-context"
            return original(*args)
        finally:
            terminal.set()
    monkeypatch.setattr(remote, name, worker)
    def block():
        loop.call_soon_threadsafe(entered.set)
        if not release.wait(3):
            raise TimeoutError("Owned shutdown barrier expired")
    calls = []
    def fetch(*args):
        calls.append(args)
        if stage == "fetch":
            block()
        return (b'{"videos": []}' if operation == "search" else b"body"), url
    monkeypatch.setattr(remote, "_fetch", fetch)
    if stage != "fetch":
        callback = getattr(remote, stage)
        def precommit(*args):
            if stage == "save_manifest":
                block()
                return callback(*args)
            result = callback(*args)
            block()
            return result
        monkeypatch.setattr(remote, stage, precommit)
    task = asyncio.create_task(invoke("fixture", req))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        owned = {task} | {t for t in asyncio.all_tasks() - baseline
                          if t.get_coro().__qualname__ == asyncio.to_thread.__qualname__}
        for owned_task in owned:
            owned_task.cancel()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not task.done() and not terminal.is_set()
        assert owned == {task}
        release.set()
        with pytest.raises(asyncio.CancelledError) as cancelled:
            await asyncio.wait_for(task, 2)
        assert terminal.is_set() and len(calls) == 1
        if stage == "save_manifest":
            assert (project / materials.MANIFEST).exists()
            assert any("completion won cancellation race" in n for n in cancelled.value.__notes__)
        else:
            assert not (project / materials.MANIFEST).exists()
            assert not list(project.glob("materials-source-*"))
        before = {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
        await asyncio.sleep(0)
        assert before == {p.name: p.read_bytes() for p in project.iterdir() if p.is_file()}
    finally:
        release.set()
        context.reset(token)
        if not task.done():
            try:
                await task
            except asyncio.CancelledError:
                pass
