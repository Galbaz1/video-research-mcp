"""Exact supplied sources and bounded checked-URL bodies for grounded research."""

from __future__ import annotations

import asyncio
import hashlib
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .evidence import validate_evidence_packet
from .media_acquisition import _wait_worker
from .media_local_io import _open_regular
from .media_snapshot import checked_path
from .models.evidence import EvidencePacket, EvidenceSource, SourceSnapshot
from .models.research_execution import ResearchExecutionRequest
from .redaction import redact_text
from .url_policy import checked_response


class SourceError(ValueError):
    """A bounded source refusal with a fixed, content-free reason code."""


@dataclass
class _Budget:
    """Share observed body bytes across rejected and retained source branches."""

    ceiling: int
    received: int = 0
    stopped: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


def _reject(record: dict, error: Exception) -> dict:
    record["status"] = "rejected"
    code = str(error) if isinstance(error, SourceError) else "source_access_failed"
    record["error_type"] = type(error).__name__
    record["error_code"] = redact_text(code)
    return {key: record[key] for key in ("source_id", "status", "error_type", "error_code")}


def _record(source_id: str, index: int, kind: str) -> dict:
    return {"source_id": source_id, "index": index, "kind": kind,
            "status": "pending", "received_bytes": 0, "admitted_bytes": 0}


def _original(root: str, relative: str) -> Path:
    """Apply both source-root and configured fences before opening original bytes."""
    if len(relative) > 4096:
        raise SourceError("source_path_too_long")
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise SourceError("source_root_escape")
    base = checked_path(root)
    result = checked_path(str(base / path))
    if not result.is_relative_to(base):
        raise SourceError("source_root_escape")
    return result


def _copy_file(original: Path, target: Path, record: dict, *, ceiling: int,
               deadline: float, cancelled: threading.Event) -> str:
    """Read only bounded regular original bytes, detecting concurrent substitution."""
    digest = hashlib.sha256()
    with _open_regular(original) as reader:
        before = os.fstat(reader.fileno())
        if before.st_size > ceiling:
            raise SourceError("source_byte_limit")
        with target.open("xb") as writer:
            os.fchmod(writer.fileno(), 0o600)
            while record["received_bytes"] < before.st_size:
                if cancelled.is_set() or time.monotonic() >= deadline:
                    raise TimeoutError("Source copying exceeded its deadline")
                chunk = reader.read(min(65536, before.st_size - record["received_bytes"]))
                if not chunk:
                    raise SourceError("source_changed")
                record["received_bytes"] += len(chunk)
                digest.update(chunk)
                writer.write(chunk)
            after, current = os.fstat(reader.fileno()), original.lstat()
            def identity(value):
                return (value.st_dev, value.st_ino, value.st_size,
                        value.st_mtime_ns, value.st_ctime_ns)
            if identity(before) != identity(after) or identity(before) != identity(current):
                raise SourceError("source_changed")
            writer.flush()
            os.fsync(writer.fileno())
    return digest.hexdigest()


async def _worker(function, *args, deadline: float, **kwargs):
    """Join cooperative local work before a caller may delete owned source assets."""
    cancelled = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(function, *args, cancelled=cancelled,
                                                deadline=deadline, **kwargs))
    async with asyncio.timeout(max(0, deadline - time.monotonic())):
        return await _wait_worker(task, cancelled)


def _validate(source: EvidenceSource, directory: Path, *, cancelled, deadline):
    if cancelled.is_set() or time.monotonic() >= deadline:
        raise TimeoutError("Source validation exceeded its deadline")
    packet = EvidencePacket(packet_id="source-preparation", sources=[source], claims=[])
    if validate_evidence_packet(packet, directory)["source_errors"]:
        raise SourceError("frozen_source_validation_failed")


async def _supplied(source, index, request, directory, assets, budget, deadline):
    record, target = _record(source.id, index, "supplied"), assets / f"source-{index:03}.bin"
    received_before = budget.received
    try:
        if source.asset_kind != "original":
            raise SourceError("derived_or_synthetic_source")
        original = _original(request.source_root, source.path)
        record["origin_path"] = str(original)
        ceiling = min(request.limits.max_source_bytes, budget.ceiling - budget.received)
        digest = await _worker(_copy_file, original, target, record, ceiling=ceiling,
                               deadline=deadline)
        record["sha256"] = digest
        if digest != source.sha256:
            raise SourceError("original_sha256_mismatch")
        copied = source.model_copy(update={"path": str(target.relative_to(directory)),
                                            "origin_path": str(original)})
        await _worker(_validate, copied, directory, deadline=deadline)
        record.update(status="retained", admitted_bytes=record["received_bytes"],
                      path=copied.path, revision=copied.revision)
        return copied, record, None
    except Exception as error:
        target.unlink(missing_ok=True)
        return None, record, _reject(record, error)
    finally:
        budget.received = received_before + record["received_bytes"]


def _response_type(response, remaining, ceiling):
    """Accept raw UTF-8 textual representations without parsing page instructions."""
    header = response.headers.get("content-type", "").lower()
    mime, *parameters = header.split(";")
    mime = mime.strip()
    if mime not in {"text/plain", "text/html", "application/json"} and not (
        mime.startswith("application/") and mime.endswith("+json")
    ):
        raise SourceError("unsupported_source_content_type")
    for value in parameters:
        if value.strip().startswith("charset=") and value.strip()[8:].strip(' "') not in {"utf-8", "utf8"}:
            raise SourceError("source_charset_not_utf8")
    length = response.headers.get("content-length")
    if length is not None and (not length.isdecimal() or int(length) > min(remaining, ceiling)):
        raise SourceError("source_content_length_limit")
    return mime


async def _body(response, target, record, budget, ceiling):
    """Serialize chunk admission; a rejected boundary chunk remains in observed counts."""
    iterator = response.aiter_bytes(chunk_size=min(65536, ceiling + 1)).__aiter__()
    digest = hashlib.sha256()
    with target.open("xb") as writer:
        os.fchmod(writer.fileno(), 0o600)
        while True:
            async with budget.lock:
                if budget.stopped or (budget.received >= budget.ceiling and not record["received_bytes"]):
                    raise SourceError("aggregate_source_byte_limit")
                try:
                    chunk = await anext(iterator)
                except StopAsyncIteration:
                    break
                budget.received += len(chunk)
                record["received_bytes"] += len(chunk)
                if budget.received > budget.ceiling:
                    budget.stopped = True
                    raise SourceError("aggregate_source_byte_limit")
                if record["received_bytes"] > ceiling:
                    raise SourceError("source_byte_limit")
                digest.update(chunk)
                writer.write(chunk)
    with _open_regular(target) as reader:
        text = reader.read(ceiling + 1).decode("utf-8", errors="strict")
    return digest.hexdigest(), text


async def _url_source(url, record, request, directory, assets, budget, deadline, semaphore, hosts):
    target = assets / f"url-{record['index']:03}.bin"
    try:
        async with asyncio.timeout(max(0, deadline - time.monotonic())), semaphore:
            if urlsplit(url).hostname not in hosts:
                raise SourceError("source_domain_not_allowed")
            if budget.stopped or budget.received >= budget.ceiling:
                raise SourceError("aggregate_source_byte_limit")
            async with checked_response(url, allowed_hosts=hosts) as response:
                record.update(final_url=redact_text(str(response.url)), status_code=response.status_code)
                mime = _response_type(response, budget.ceiling - budget.received,
                                      request.limits.max_source_bytes)
                record["content_type"] = mime
                digest, text = await _body(response, target, record, budget, request.limits.max_source_bytes)
            copied = EvidenceSource(id=record["source_id"], revision=f"sha256:{digest}",
                                    sha256=digest, path=str(target.relative_to(directory)),
                                    modality="text", asset_kind="original",
                                    snapshot=SourceSnapshot(text=text, sha256=digest),
                                    origin_url=redact_text(url), final_url=record["final_url"])
            await _worker(_validate, copied, directory, deadline=deadline)
            record.update(status="retained", sha256=digest, revision=copied.revision,
                          admitted_bytes=record["received_bytes"], path=copied.path)
            return copied, record, None
    except Exception as error:
        target.unlink(missing_ok=True)
        return None, record, _reject(record, error)


async def _join(tasks):
    """Cancel and join all HTTP branches even when caller cancellation repeats."""
    group = asyncio.gather(*tasks, return_exceptions=True)
    try:
        return await asyncio.shield(group)
    except asyncio.CancelledError:
        for task in tasks:
            task.cancel()
        while not group.done():
            try:
                await asyncio.shield(group)
            except asyncio.CancelledError:
                continue
        group.result()
        raise


def _url_plan(request):
    records, reservations = [], 0
    for index, url in enumerate(request.urls):
        identity = hashlib.sha256(f"{index}\0{url}".encode()).hexdigest()
        row = _record(f"retrieved-{identity}", index, "url")
        row.update(url=redact_text(url), reserved_requests=0, physical_requests=None,
                   physical_request_upper_bound=6)
        if request.dry_run:
            row["status"] = "planned"
        elif not request.authorize_source_access:
            _reject(row, SourceError("source_access_not_authorized"))
        elif reservations + 6 > request.limits.max_source_requests:
            _reject(row, SourceError("source_request_reservation_limit"))
        else:
            reservations += 6
            row["reserved_requests"] = 6
        records.append(row)
    return records


async def prepare_sources(request: ResearchExecutionRequest, directory: Path) -> dict:
    """Retain exact original evidence and every checked retrieval outcome separately."""
    deadline = time.monotonic() + request.limits.timeout_seconds
    directory = checked_path(str(directory))
    packet = request.supplied_packet.model_copy(deep=True) if request.supplied_packet else None
    result = {"sources": [], "source_records": [], "rejections": [], "requests": _url_plan(request),
              "retained_claims": packet.claims if packet else [],
              "retained_lineage": packet.lineage if packet else []}
    budget = _Budget(request.limits.max_total_source_bytes)
    assets = directory / f"source-assets-{uuid.uuid4().hex}"
    assets.mkdir(mode=0o700)
    try:
        outcomes = []
        for index, source in enumerate(packet.sources if packet else []):
            outcomes.append(await _supplied(source, index, request, directory, assets, budget, deadline))
        hosts = set(request.allowed_domains) or {urlsplit(url).hostname for url in request.urls}
        semaphore = asyncio.Semaphore(request.limits.concurrency)
        tasks = [asyncio.create_task(_url_source(url, row, request, directory, assets, budget,
                                               deadline, semaphore, hosts))
                 for url, row in zip(request.urls, result["requests"]) if row["status"] == "pending"]
        outcomes.extend(await _join(tasks))
        for row in result["requests"]:
            if not row["reserved_requests"]:
                outcomes.append((None, row, {key: row[key] for key in (
                    "source_id", "status", "error_type", "error_code")} if row["status"] == "rejected" else None))
        for source, record, rejection in sorted(outcomes, key=lambda item: (item[1]["kind"] == "url", item[1]["index"])):
            result["source_records"].append(record.copy())
            if source is not None:
                result["sources"].append(source)
            if rejection is not None:
                result["rejections"].append(rejection)
        if not any(assets.iterdir()):
            assets.rmdir()
        return result
    except BaseException:
        shutil.rmtree(assets)
        raise
