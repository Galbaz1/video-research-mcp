"""Explicit stock-source access with bounded responses and pinned media rights."""

import asyncio
from contextvars import copy_context
from datetime import datetime, timezone
import hashlib
import http.client
import ipaddress
import json
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import time
from threading import Event
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

from .materials import MAX_ASSET_BYTES, discard_published, load_manifest, pinned_object, publish, rights_receipt, save_manifest
from .models.materials import STOCK_CREDENTIAL_ENV, StockCandidate, StockConfig, StockDownload, StockSearch
from .planning import plan_transaction
from .planning_sources import digest, project_directory
from .render_storyboard_sources import confined_path, file_pin

SEARCH_HOSTS = {"pexels": "api.pexels.com", "pixabay": "pixabay.com"}


def public_url(url: str, hosts: list[str], *, credential_query: bool = False):
    """Require an exact configured public HTTPS host without userinfo or nonstandard ports."""
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname not in hosts or parts.username or parts.password
            or parts.port not in {None, 443} or parts.fragment or "\\" in url):
        raise ValueError("Stock URL must use an explicitly allowed public HTTPS host")
    for key in parse_qs(parts.query, keep_blank_values=True):
        if not key.strip():
            raise ValueError("Credential-bearing stock URLs cannot enter receipts")
        name = key.lower().replace("-", "").replace("_", "")
        if (name in {"key", "apikey", "auth", "sig", "accesskey", "accesskeyid", "awsaccesskeyid", "passwd", "bearer", "authentication"}
                or any(marker in name for marker in ("token", "signature", "credential", "secret", "password", "authorization"))):
            if (credential_query and name == "key" and hosts == ["pixabay.com"]
                    and parts.hostname == "pixabay.com" and parts.path == "/api/videos/"):
                continue
            raise ValueError("Credential-bearing stock URLs cannot enter receipts")
    return parts


def _fetch(url: str, headers: dict, hosts: list[str], limit: int, deadline: float) -> tuple[bytes, str]:
    """Pin public DNS addresses, retain TLS hostname validation and bound redirect/body work."""
    for attempt in range(4):
        if time.monotonic() >= deadline:
            raise TimeoutError("Stock acquisition deadline exceeded")
        parts = public_url(url, hosts, credential_query=bool(headers))
        addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError("Stock DNS resolved to a nonpublic address")
        remaining = min(10.0, deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError("Stock acquisition deadline exceeded")
        connection = http.client.HTTPSConnection(parts.hostname, timeout=remaining)
        response = None
        try:
            stream = socket.socket(addresses[0][0], socket.SOCK_STREAM)
            try:
                stream.settimeout(remaining)
                stream.connect(addresses[0][4])
                secured = ssl.create_default_context().wrap_socket(stream, server_hostname=parts.hostname)
            except BaseException as error:
                try:
                    stream.close()
                except OSError as cleanup:
                    error.add_note(f"Stock TLS cleanup liability:{type(cleanup).__name__}")
                raise
            connection.sock = secured
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                if headers or attempt == 3:
                    raise ValueError("Authenticated search redirects and excessive redirects are refused")
                location = response.getheader("Location")
                if not location:
                    raise ValueError("Stock redirect has no location")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError(f"Stock HTTP status{response.status}; no automatic retry")
            return _read_response(response, secured, limit, deadline), url
        finally:
            _close_http(response, connection)
    raise ValueError("Stock redirect bound exhausted")


def _close_http(response, connection) -> None:
    """Close both resources while retaining the primary acquisition error and cleanup liability."""
    primary = sys.exception()
    failure = None
    for resource in (response, connection):
        if resource is None:
            continue
        try:
            resource.close()
        except OSError as cleanup:
            if primary is not None:
                primary.add_note(f"Stock HTTP cleanup liability:{type(cleanup).__name__}")
            elif failure is None:
                failure = cleanup
    if failure is not None:
        raise failure


def _read_response(response, secured, limit: int, deadline: float) -> bytes:
    """Bound streamed bytes and each socket wait against the same acquisition deadline."""
    body = bytearray()
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Stock acquisition deadline exceeded")
        secured.settimeout(min(10.0, remaining))
        chunk = response.read1(min(65536, limit + 1 - len(body)))
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > limit or time.monotonic() > deadline:
            raise ValueError("Stock response exceeded byte/deadline bound")


def _config(project: Path, request, action: str) -> StockConfig:
    """Require pinned configuration and explicit, unexpired caller/source permission."""
    config = StockConfig.model_validate(pinned_object(project, request.config))
    if (config.valid_until.tzinfo is None or config.valid_until <= datetime.now(timezone.utc)
            or config.principal != request.principal or not getattr(config, f"{action}_allowed")):
        raise ValueError("Stock source/caller permission is absent or expired")
    for host in config.download_hosts:
        public_url(f"https://{host}/", config.download_hosts)
        if host in {"localhost", SEARCH_HOSTS[config.provider]}:
            raise ValueError("Download hosts must identify explicitly allowed public media origins")
    return config


def _search_page(config: StockConfig, request: StockSearch, page: int, deadline: float) -> list[dict]:
    """Apply the two retained primary source response shapes without treating results as rights."""
    key = os.environ.get(STOCK_CREDENTIAL_ENV[config.provider], "")
    if not key:
        raise ValueError("Configured stock credential is unavailable")
    headers = {"Authorization": key} if config.provider == "pexels" else {"Accept": "application/json"}
    size = 20 if config.provider == "pexels" else 50
    params = {"page": page, "per_page": size}
    if config.provider == "pexels":
        params.update(query=request.query, orientation="landscape")
        base = "https://api.pexels.com/v1/videos/search"
    else:
        params.update(q=request.query, video_type="all", key=key)
        base = "https://pixabay.com/api/videos/"
    body, _ = _fetch(base + "?" + urlencode(params), headers, [SEARCH_HOSTS[config.provider]], 1024 * 1024, deadline)
    value = json.loads(body)
    items = value["videos" if config.provider == "pexels" else "hits"]
    if not isinstance(items, list) or len(items) > size:
        raise ValueError("Stock response has an invalid or excessive result list")
    results = []
    for item in items:
        files = item["video_files"] if config.provider == "pexels" else list(item["videos"].values())
        if not isinstance(files, list) or len(files) > 32:
            raise ValueError("Stock response has an invalid rendition list")
        for variant in files:
            url = variant["link" if config.provider == "pexels" else "url"]
            public_url(url, config.download_hosts)
            if len(results) >= 128:
                raise ValueError("Stock page exceeds128renditions")
            creator = item.get("user")
            if isinstance(creator, dict):
                creator = creator.get("name")
            results.append(StockCandidate(provider=config.provider, asset_id=str(item["id"]), url=url,
                            source_page=item.get("url" if config.provider == "pexels" else "pageURL"),
                            creator=creator, duration_seconds=item["duration"],
                            width=variant["width"], height=variant["height"]).model_dump(mode="json"))
    return results


def _search(project: Path, request: StockSearch, cancelled: Event) -> dict:
    """Retain partial pagination failures honestly without retrying provider errors."""
    _check_cancelled(cancelled)
    config = _config(project, request, "search")
    results = []
    deadline = time.monotonic() + 20
    for page in range(request.page, request.page + request.pages):
        _check_cancelled(cancelled)
        try:
            candidates = _search_page(config, request, page, deadline)
            _check_cancelled(cancelled)
            if len(json.dumps(results + candidates, allow_nan=False).encode()) > 1024 * 1024:
                raise ValueError("Stock result metadata exceeds1MiB")
            results.extend(candidates)
        except (OSError, ValueError, KeyError, TypeError, http.client.HTTPException):
            return {"success": False, "results": results, "failed_page": page,
                    "error": "Stock page failed; no retry; partial results confer no rights"}
    _check_cancelled(cancelled)
    _config(project, request, "search")
    return {"success": True, "results": results, "config_sha256": request.config.sha256,
            "retrieved_at": datetime.now(timezone.utc).isoformat(), "provider_rights_verified": False}


def _download(project: Path, request: StockDownload, cancelled: Event) -> dict:
    """Publish only exact caller-pinned downloaded bytes, after source and clip permission checks."""
    _check_cancelled(cancelled)
    with plan_transaction(project, create=True):
        config = _config(project, request, "download")
        public_url(request.url, config.download_hosts)
        rights = rights_receipt(project, request.rights, request.expected_sha256, request.principal)
        if rights["source_url"] != request.url:
            raise ValueError("Download URL differs from its rights receipt")
        key = digest(request.model_dump(mode="json"))
        manifest = load_manifest(project)
        if key in manifest["downloads"]:
            row = manifest["downloads"][key]
            public_url(row["url"], config.download_hosts)
            public_url(row["final_url"], config.download_hosts)
            pin = file_pin(confined_path(project, row["path"]), MAX_ASSET_BYTES)
            if (row["path"] != f"materials-source-{key}.mp4"
                    or pin["sha256"] != request.expected_sha256 or row["sha256"] != pin["sha256"]
                    or row["size_bytes"] != pin["size_bytes"]
                    or row["rights"] != rights or row["config_sha256"] != request.config.sha256
                    or row["use"] != "illustrative"):
                raise ValueError("Cached stock source changed")
            _config(project, request, "download")
            rights_receipt(project, request.rights, request.expected_sha256, request.principal)
            _check_cancelled(cancelled)
            return {"success": True, "cached": True, **row}
        body, final_url = _fetch(request.url, {}, config.download_hosts, MAX_ASSET_BYTES, time.monotonic() + 20)
        _check_cancelled(cancelled)
        public_url(final_url, config.download_hosts)
        if not body or hashlib.sha256(body).hexdigest() != request.expected_sha256:
            raise ValueError("Stock download bytes differ from the expected source digest")
        _config(project, request, "download")
        if rights_receipt(project, request.rights, request.expected_sha256, request.principal) != rights:
            raise ValueError("Stock rights changed during download")
        name = f"materials-source-{key}.mp4"
        with tempfile.TemporaryDirectory(prefix="vrm-stock-") as directory:
            temporary = Path(directory) / "source.mp4"
            temporary.write_bytes(body)
            _check_cancelled(cancelled)
            publish(project, temporary, name, request.expected_sha256)
        row = {"path": name, "sha256": request.expected_sha256, "size_bytes": len(body), "url": request.url,
               "final_url": final_url, "rights": rights, "config": request.config.model_dump(),
               "config_sha256": request.config.sha256,
               "retrieved_at": datetime.now(timezone.utc).isoformat(), "use": "illustrative",
               "media_qualified": False, "factual_success": False}
        manifest["downloads"][key] = row
        try:
            _check_cancelled(cancelled)
            save_manifest(project, manifest)
        except BaseException as error:
            discard_published(project, name, request.expected_sha256, error)
            raise
        return {"success": True, "cached": False, **row}


async def search_materials(project_id: str, request: StockSearch) -> dict:
    """Search only the explicitly authorized configured source, with at most three pages."""
    return await _joined_worker(_search, project_directory(project_id), request)


async def download_material(project_id: str, request: StockDownload) -> dict:
    """Acquire a stock rendition only after explicit source permission and separate asset rights."""
    return await _joined_worker(_download, project_directory(project_id), request)


def _check_cancelled(cancelled: Event) -> None:
    """Stop at a worker boundary before further pagination or publication."""
    if cancelled.is_set():
        raise asyncio.CancelledError("Stock worker cooperatively stopped")


async def _joined_worker(operation, project: Path, request) -> dict:
    """Defer terminal cancellation until the owned worker has finished and been observed."""
    cancelled = Event()
    worker = asyncio.get_running_loop().run_in_executor(
        None, copy_context().run, operation, project, request, cancelled
    )
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError as cancellation:
        cancelled.set()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except BaseException:
                break
        try:
            result = worker.result()
        except BaseException as error:
            cancellation.add_note(f"Stock worker joined with {type(error).__name__}")
            for note in getattr(error, "__notes__", []):
                cancellation.add_note(note)
            cancellation.__cause__ = error
        else:
            cancellation.add_note(f"Stock worker joined; completion won cancellation race; success={result.get('success')}")
        raise
