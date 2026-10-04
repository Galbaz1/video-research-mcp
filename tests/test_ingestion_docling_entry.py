"""Optional Docling submission retains exact original bytes and terminal ambiguity."""

import hashlib
import json
import asyncio
from pathlib import Path

import pytest

from video_research_mcp import ingestion, ingestion_docling
from video_research_mcp.config import update_config
from video_research_mcp.models.ingestion import SourceIngestRequest
from video_research_mcp.models.ingestion_service import DoclingService
from video_research_mcp.models.ingestion_location import IngestionLocation
from video_research_mcp.job_store import JobStore
from video_research_mcp.tools.ingestion import source_ingest_cancel


@pytest.fixture(autouse=True)
def isolated(clean_config, monkeypatch, tmp_path):
    monkeypatch.setenv("GEMINI_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("LOCAL_FILE_ACCESS_ROOT", str(tmp_path))


def request(tmp_path, **overrides):
    path = tmp_path / "input.md"
    path.write_bytes(b"# exact original\n")
    fields = dict(
        source_id="docling-original",
        revision="r1",
        source_format="markdown",
        file_path=str(path),
        parser="docling",
        authorize_submission=True,
    )
    return SourceIngestRequest(**(fields | overrides))


def capabilities():
    return {
        "versions": {"docling-serve": "1.36.0", "docling": "2.129.0", "docling-core": "2.96.0"},
        "targets": {"allowed": ["inbody"], "default": "inbody"},
        "output_formats": ["json"],
        "image_export_modes": ["embedded"],
        "sources": ["file"],
        "stages": {},
        "limits": {
            "max_document_timeout": 120,
            "max_images_scale": 2,
            "max_sources_per_request": 1,
            "max_num_pages": None,
            "max_file_size": None,
        },
        "features": {"api_key_required": False, "artifact_storage": False},
    }


def configure(contract, **overrides):
    fields = {
        "base_url": "http://127.0.0.1:7777",
        "expected_contract_sha256": hashlib.sha256(contract).hexdigest(),
        "deployment_revision": "operator-pinned",
        "runtime_qualified": True,
    }
    update_config(docling_service=fields | overrides)


@pytest.mark.parametrize("core_version", ["2.79.0", "2.95.0", "2.96.0", "2.97.0"])
async def test_exact_core_version_admission_before_upload(tmp_path, monkeypatch, core_version):
    """Only the selected compatible core version admits the retained original."""
    data = capabilities()
    data["versions"]["docling-core"] = core_version
    contract, body = json.dumps(data).encode(), json.dumps(response()).encode()
    configure(contract)
    calls = []

    async def exchange(url, **kwargs):
        calls.append(kwargs["method"])
        return 200, contract if kwargs["method"] == "GET" else body

    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == ("completed" if core_version == "2.96.0" else "failed")
    assert calls == (["GET", "POST"] if core_version == "2.96.0" else ["GET"])
    derived = Path(result["original"]["path"]).parent / "derived"
    assert (derived / "docling-contract.json").read_bytes() == contract
    if core_version != "2.96.0":
        assert not result["docling_lifecycle"]["upload_attempted"]
        assert not (derived / "docling-submission.json").exists()
    else:
        profile = json.loads((derived / "docling-profile.json").read_bytes())
        assert profile["versions"]["docling-core"] == "2.96.0"
        assert (derived / "docling-response.json").read_bytes() == body


async def test_timeout_retains_remote_ambiguity_in_durable_failure(tmp_path, monkeypatch):
    contract = json.dumps(capabilities()).encode()
    configure(contract)
    calls = []

    async def exchange(url, **kwargs):
        calls.append(kwargs["method"])
        if kwargs["method"] == "GET":
            return 200, contract
        raise TimeoutError("owned transport joined")

    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == "failed"
    assert result["docling_lifecycle"]["remote_conversion"] == "may_continue"
    assert Path(result["original"]["path"]).read_bytes() == b"# exact original\n"
    assert calls == ["GET", "POST"]
    again = await ingestion.ingest_source(request(tmp_path))
    assert again["deduplicated"] and again["status"] == "failed"
    assert calls == ["GET", "POST"]


def response():
    return {
        "status": "success",
        "errors": [],
        "document": {
            "filename": "original.md",
            "json_content": {
                "schema_name": "DoclingDocument",
                "version": "1.10.0",
                "pages": {},
                "tables": [],
                "pictures": [],
                "texts": [
                    {"self_ref": "#/texts/0", "text": "exact original", "label": "text", "prov": []}
                ],
            },
        },
    }


@pytest.mark.parametrize("refusal", ["disabled", "unqualified", "unauthorized"])
async def test_refusals_precede_retention_and_connection(tmp_path, monkeypatch, refusal):
    contract = json.dumps(capabilities()).encode()
    if refusal != "disabled":
        configure(contract, runtime_qualified=refusal != "unqualified")

    async def forbidden(*args, **kwargs):
        pytest.fail("retention/connection before admission")

    monkeypatch.setattr(ingestion, "retain_source", forbidden)
    monkeypatch.setattr(ingestion_docling, "exchange", forbidden)
    with pytest.raises(ValueError):
        await ingestion.ingest_source(
            request(tmp_path, authorize_submission=refusal != "unauthorized")
        )


@pytest.mark.parametrize("mismatch", ["hash", "version", "shape", "output", "api_key"])
async def test_contract_mismatch_retained_without_upload(tmp_path, monkeypatch, mismatch):
    data = capabilities()
    if mismatch == "version":
        data["versions"]["docling"] = "2.0.0"
    if mismatch == "shape":
        data["limits"] = []
    if mismatch == "output":
        data["output_formats"] = ["md"]
    if mismatch == "api_key":
        data["features"]["api_key_required"] = True
    contract = json.dumps(data).encode()
    configure(contract, **({"expected_contract_sha256": "0" * 64} if mismatch == "hash" else {}))
    calls = []

    async def exchange(url, **kwargs):
        calls.append(kwargs["method"])
        assert kwargs["method"] == "GET" and kwargs["content"] == b""
        return 200, contract

    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == "failed" and calls == ["GET"]
    assert not result["docling_lifecycle"]["upload_attempted"]
    retained = Path(result["original"]["path"]).parent / "derived" / "docling-contract.json"
    assert retained.read_bytes() == contract
    assert result["docling_evidence"][str(retained)] == hashlib.sha256(contract).hexdigest()


async def test_exact_multipart_success_dedup_and_restart(tmp_path, monkeypatch):
    contract, body = json.dumps(capabilities()).encode(), json.dumps(response()).encode()
    configure(contract)
    calls = []

    async def exchange(url, **kwargs):
        calls.append(kwargs["method"])
        assert kwargs["local"] and kwargs["response_limit"] <= 240 * 1024
        if kwargs["method"] == "GET":
            assert url.endswith("/v1/capabilities")
            return 200, contract
        assert url.endswith("/v1/convert/file")
        boundary = kwargs["headers"]["Content-Type"].split("boundary=")[1].encode()
        file_part = kwargs["content"].split(b'name="files"; filename="original.md"')[1]
        assert (
            file_part.split(b"\r\n\r\n", 1)[1] == b"# exact original\n\r\n--" + boundary + b"--\r\n"
        )
        assert b'name="do_ocr"\r\n\r\nfalse\r\n' in kwargs["content"]
        return 200, body

    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == "completed", result
    assert result["extraction"]["segments"][0]["location"]["element"] == "#/texts/0"
    assert result["original"]["sha256"] == hashlib.sha256(b"# exact original\n").hexdigest()
    derived = Path(result["original"]["path"]).parent / "derived"
    assert (derived / "docling-response.json").read_bytes() == body
    restarted = await ingestion.read_ingestion(result["job_id"])
    assert restarted["original"] == result["original"]
    assert restarted["extraction"] == result["extraction"]
    assert (await ingestion.ingest_source(request(tmp_path)))["deduplicated"]
    assert calls == ["GET", "POST"]


@pytest.mark.parametrize(
    "status,body",
    [
        (504, b'{"detail":"conversion timed out"}'),
        (200, b'{"status":"success","status":"failure"}'),
        (200, b'{"value":NaN}'),
        (200, b"not JSON"),
        (200, b'{"document":null}'),
    ],
)
async def test_wire_failure_retains_exact_raw_body_without_retry(
    tmp_path, monkeypatch, status, body
):
    contract = json.dumps(capabilities()).encode()
    configure(contract)
    calls = []

    async def exchange(url, **kwargs):
        calls.append(kwargs["method"])
        return (200, contract) if kwargs["method"] == "GET" else (status, body)

    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert (
        result["status"] == "failed"
        and result["docling_lifecycle"]["remote_conversion"] == "may_continue"
    )
    retained = Path(result["original"]["path"]).parent / "derived" / "docling-response.json"
    assert retained.read_bytes() == body
    assert (await ingestion.read_ingestion(result["job_id"]))["docling_evidence"] == result[
        "docling_evidence"
    ]
    assert (await ingestion.ingest_source(request(tmp_path)))["deduplicated"]
    assert calls == ["GET", "POST"]


async def test_cancellation_joins_local_exchange_and_keeps_remote_unknown(tmp_path, monkeypatch):
    contract = json.dumps(capabilities()).encode()
    configure(contract)
    submitted, joined = asyncio.Event(), asyncio.Event()
    original = []

    async def exchange(url, **kwargs):
        if kwargs["method"] == "GET":
            return 200, contract
        original.extend((tmp_path / "cache" / "media" / "views").glob("*/original.md"))
        submitted.set()
        try:
            await asyncio.Event().wait()
        finally:
            joined.set()

    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    task = asyncio.create_task(ingestion.ingest_source(request(tmp_path)))
    await asyncio.wait_for(submitted.wait(), 3)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert joined.is_set() and len(original) == 1
    lifecycle = json.loads((original[0].parent / "derived" / "docling-lifecycle.json").read_bytes())
    assert lifecycle["remote_conversion"] == "may_continue"
    again = await ingestion.ingest_source(request(tmp_path))
    assert again["status"] == "cancelled" and again["deduplicated"]
    assert JobStore().get(again["job_id"])["result"]["docling_lifecycle"] == lifecycle


async def test_changed_profile_refuses_before_body_upload(tmp_path, monkeypatch):
    contract = json.dumps(capabilities()).encode()
    configure(contract)

    async def exchange(url, **kwargs):
        assert kwargs["method"] == "GET"
        configure(contract, deployment_revision="changed")
        return 200, contract

    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == "failed" and not result["docling_lifecycle"]["upload_attempted"]


async def test_source_hash_readback_refuses_before_upload(tmp_path, monkeypatch):
    contract = json.dumps(capabilities()).encode()
    configure(contract)

    async def exchange(url, **kwargs):
        assert kwargs["method"] == "GET"
        path = next((tmp_path / "cache" / "media" / "views").glob("*/original.md"))
        path.write_bytes(b"changed")
        return 200, contract

    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == "unknown"  # Original custody failure remains visible.


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:7777",
        "https://example.com",
        "http://127.0.0.1/x",
        "http://user@127.0.0.1",
        "http://127.0.0.1?x=1",
        "http://127.0.0.1:0",
    ],
)
def test_config_refuses_nonliteral_or_ambiguous_origins(url):
    with pytest.raises(ValueError):
        DoclingService(
            base_url=url, expected_contract_sha256="0" * 64, deployment_revision="pinned"
        )


def test_default_location_serialization_has_no_new_none_field():
    location = IngestionLocation(start_char=0, end_char=5)
    assert "element" not in location.model_dump(mode="json")
    assert "bbox" in location.model_dump(mode="json")  # Original None fields are retained.


def test_json_rejects_exponent_overflow_even_in_unused_fields():
    with pytest.raises(ValueError):
        ingestion_docling.finite_json(b'{"unused":1e400}')


@pytest.mark.parametrize("change", ["sources", "file_size", "missing_file", "missing_pages", "bool_file", "string_file", "bool_pages"])
async def test_repair_contract_refuses_before_multipart(tmp_path, monkeypatch, change):
    data = capabilities()
    if change == "sources":
        data["sources"] = ["http"]
    elif change == "file_size":
        data["limits"]["max_file_size"] = 1
    elif change.startswith("missing"):
        del data["limits"]["max_file_size" if change == "missing_file" else "max_num_pages"]
    else:
        key = "max_num_pages" if change == "bool_pages" else "max_file_size"
        data["limits"][key] = "50" if change == "string_file" else True
    contract = json.dumps(data).encode()
    configure(contract)
    calls = []
    async def exchange(url, **kwargs):
        calls.append(kwargs["method"])
        assert kwargs["method"] == "GET"
        return 200, contract
    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    monkeypatch.setattr(ingestion_docling, "multipart", lambda *a, **k: pytest.fail("multipart before file admission"))
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == "failed" and calls == ["GET"]
    assert not result["docling_lifecycle"]["upload_attempted"]


@pytest.mark.parametrize("cancelled", [False, True])
@pytest.mark.parametrize("evidence_failure", ["exception", "corrupt"])
async def test_repair_evidence_exception_still_checkpoints(tmp_path, monkeypatch, cancelled, evidence_failure):
    contract = json.dumps(capabilities()).encode()
    configure(contract)
    async def exchange(url, **kwargs):
        if kwargs["method"] == "GET":
            return 200, contract
        if cancelled:
            raise asyncio.CancelledError()
        raise TimeoutError("joined")
    collect = ingestion_docling.failure_evidence
    def unavailable(source):
        if evidence_failure == "corrupt":
            (Path(source["path"]).parent / "derived" / "docling-lifecycle.json").write_bytes(b"[]")
            return collect(source)
        raise PermissionError("PRIVATE_EVIDENCE_EXCEPTION_INPUT")
    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    monkeypatch.setattr(ingestion_docling, "failure_evidence", unavailable)
    selected = request(tmp_path)
    if cancelled:
        with pytest.raises(asyncio.CancelledError):
            await ingestion.ingest_source(selected)
        result = await ingestion.ingest_source(selected)
    else:
        result = await ingestion.ingest_source(selected)
    assert result["status"] == ("cancelled" if cancelled else "failed")
    assert result["docling_evidence_error"] == "Docling failure evidence unavailable"
    assert "PRIVATE_EVIDENCE_EXCEPTION_INPUT" not in json.dumps(result)
    assert Path(result["original"]["path"]).read_bytes() == b"# exact original\n"
    assert JobStore().get(result["job_id"])["status"] == result["status"]


async def test_repair_local_io_not_started_before_profile_drift(tmp_path, monkeypatch):
    contract = json.dumps(capabilities()).encode()
    configure(contract)
    selected = request(tmp_path)
    original_retain = ingestion.retain_source
    async def retain_then_change(*args, **kwargs):
        source = await original_retain(*args, **kwargs)
        configure(contract, deployment_revision="changed-before-contract")
        return source
    async def forbidden(*args, **kwargs):
        pytest.fail("exchange after profile drift")
    monkeypatch.setattr(ingestion, "retain_source", retain_then_change)
    monkeypatch.setattr(ingestion_docling, "exchange", forbidden)
    result = await ingestion.ingest_source(selected)
    assert result["status"] == "failed"
    assert result["docling_lifecycle"]["local_io"] == "no_exchange_started"


async def test_repair_orphan_png_is_bound_after_later_picture_failure(tmp_path, monkeypatch):
    import base64
    import io
    from PIL import Image
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(stream, format="PNG")
    png = stream.getvalue()
    data = response()
    image = {"mimetype": "image/png", "uri": "data:image/png;base64," + base64.b64encode(png).decode(),
             "size": {"width": 2, "height": 2}}
    data["document"]["json_content"]["pictures"] = [
        {"self_ref": "#/pictures/0", "prov": [], "image": image},
        {"self_ref": "#/pictures/1", "prov": [], "image": {**image, "uri": "https://external.invalid/picture.png"}},
    ]
    contract, body = json.dumps(capabilities()).encode(), json.dumps(data).encode()
    configure(contract)
    async def exchange(url, **kwargs):
        return (200, contract) if kwargs["method"] == "GET" else (200, body)
    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == "failed"
    path = Path(result["original"]["path"]).parent / "derived" / "docling-image-0.png"
    assert path.read_bytes() == png
    assert result["docling_evidence"][str(path)] == hashlib.sha256(png).hexdigest()
    assert JobStore().get(result["job_id"])["artifact_hashes"][str(path)] == hashlib.sha256(png).hexdigest()


async def test_repair_docling_cancel_tool_does_not_claim_remote_termination(tmp_path, monkeypatch):
    contract = json.dumps(capabilities()).encode()
    configure(contract)
    async def exchange(url, **kwargs):
        if kwargs["method"] == "GET":
            return 200, contract
        raise asyncio.CancelledError()
    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    with pytest.raises(asyncio.CancelledError):
        await ingestion.ingest_source(request(tmp_path))
    row = await ingestion.ingest_source(request(tmp_path))
    result = await source_ingest_cancel(row["job_id"])
    assert result["status"] == "cancelled" and result["local_owner_acknowledged"]
    assert not result["termination_verified"] and result["remote_conversion"] == "may_continue"


async def test_repair_validation_error_does_not_expose_input_values(tmp_path, monkeypatch):
    data = response()
    data["document"]["json_content"]["texts"][0]["text"] = "PRIVATE_VALIDATION_INPUT_" + "x" * 32768
    contract, body = json.dumps(capabilities()).encode(), json.dumps(data).encode()
    configure(contract)
    async def exchange(url, **kwargs):
        return (200, contract) if kwargs["method"] == "GET" else (200, body)
    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == "failed" and "PRIVATE_VALIDATION_INPUT_" not in result["error"]
    assert "input_value" not in result["error"]


@pytest.mark.parametrize("page_count", [0, 2])
async def test_repair_page_limit_uses_only_known_returned_population(tmp_path, monkeypatch, page_count):
    caps, data = capabilities(), response()
    caps["limits"].update(max_file_size=len(b"# exact original\n"), max_num_pages=1)
    data["document"]["json_content"]["pages"] = {
        str(i): {"page_no": i, "size": {"width": 100, "height": 100}} for i in range(1, page_count + 1)}
    contract, body = json.dumps(caps).encode(), json.dumps(data).encode()
    configure(contract)
    async def exchange(url, **kwargs):
        if kwargs["method"] == "GET":
            return 200, contract
        original = next((tmp_path / "cache" / "media" / "views").glob("*/original.md"))
        receipt = json.loads((original.parent / "derived" / "docling-submission.json").read_bytes())
        assert receipt["source_num_pages_before_upload"] == "unknown" and receipt["max_num_pages"] == 1
        return 200, body
    monkeypatch.setattr(ingestion_docling, "exchange", exchange)
    result = await ingestion.ingest_source(request(tmp_path))
    assert result["status"] == ("completed" if page_count == 0 else "failed")
    if page_count == 0:
        assert any("Source page count was unknown" in line for line in result["extraction"]["limitations"])
    else:
        assert result["docling_lifecycle"]["upload_attempted"]


@pytest.mark.parametrize("invalid", ["symlink", "bytes", "population"])
def test_repair_failure_artifacts_are_bounded_regular_files(tmp_path, invalid):
    original = tmp_path / "original.md"
    original.write_bytes(b"original")
    derived = tmp_path / "derived"
    derived.mkdir()
    path = derived / "docling-image-0.png"
    if invalid == "symlink":
        path.symlink_to(original)
    elif invalid == "bytes":
        path.write_bytes(b"x" * (256 * 1024 + 1))
    else:
        for index in range(65):
            (derived / f"docling-{index}.json").write_bytes(b"{}")
    with pytest.raises((ValueError, PermissionError)):
        ingestion_docling.failure_evidence({"path": str(original)})
    assert original.read_bytes() == b"original"
