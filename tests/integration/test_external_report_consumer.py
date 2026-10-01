"""Optional maintained report hook under an explicit mocked inference boundary."""

from copy import deepcopy
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from examples import gpt_researcher_report as consumer
from tests.integration.test_external_harness_contract import selected  # noqa: F401
from video_research_mcp.integrations.external_harness import digest, encoded, source_record


@pytest.fixture
def receipt_file(tmp_path, selected):  # noqa: F811
    """Write a complete collector receipt bound to a declared mocked source response."""
    request, result = selected
    record = source_record(result, request)
    receipt = {"status": "complete", "factual_success": False, "record": record,
               "trace": [{"stage": "source", "record_sha256": digest(encoded(record))}]}
    path = tmp_path / "source-receipt.json"
    path.write_text(json.dumps(receipt))
    return path, consumer.digest(path.read_bytes()), receipt


async def test_public_report_hook_consumes_tool_record_without_assuming_research_execution(receipt_file, monkeypatch):
    """GIVEN exact retained source WHEN report hook runs THEN source references derive from tool output."""
    path, expected, _ = receipt_file
    record = consumer.read_source(path, expected)
    seen = {}

    class MockResearcher:
        """The optional GPT runtime/model is mocked, keeping the source adapter actual."""

        def __init__(self, **kwargs):
            seen["constructor"] = kwargs

        async def conduct_research(self):
            raise AssertionError("The consumer must not replace context or run planner/search")

        async def write_report(self, *, ext_context):
            assert self.available_images == []
            seen["ext_context"] = ext_context
            return f"Measured point: [{json.loads(ext_context[0])['source_references'][0]}]"

    monkeypatch.setattr(consumer, "version", lambda name: "0.16.0")
    monkeypatch.setitem(sys.modules, "gpt_researcher", SimpleNamespace(GPTResearcher=MockResearcher))
    result = await consumer.report_source(record, "Report metadata", "/owned/consumer.json")
    assert result["status"] == "complete" and result["reference_present"] is True
    assert seen["ext_context"] == seen["constructor"]["context"] == [record["body"]]
    assert seen["constructor"]["mcp_strategy"] == "disabled"
    assert seen["constructor"]["visited_urls"] == {record["href"]}
    assert seen["constructor"]["config_path"] == "/owned/consumer.json"
    assert result["record_sha256"] == consumer.digest(consumer.encoded(record))
    assert result["report_sha256"] == consumer.digest(result["report"].encode())
    assert result["provider_calls"] is None and result["currency"] is None
    assert result["factual_success"] is False and result["semantic_review"] == "pending"


@pytest.mark.parametrize("mutation", ["artifact_sha", "failed", "record", "result", "reference"])
def test_source_commitment_failures_reject_before_optional_import_or_model(mutation, receipt_file):
    path, expected, original = receipt_file
    receipt = deepcopy(original)
    if mutation == "artifact_sha":
        expected = "0" * 64
    elif mutation == "failed":
        receipt["status"] = "failed"
    elif mutation == "record":
        receipt["trace"][0]["record_sha256"] = "0" * 64
    else:
        payload = json.loads(receipt["record"]["body"])
        if mutation == "result":
            payload["tool_result_sha256"] = "0" * 64
        else:
            payload["source_references"] = ["https://fabricated.example/"]
        receipt["record"]["body"] = encoded(payload)
        receipt["trace"][0]["record_sha256"] = digest(encoded(receipt["record"]))
    path.write_text(json.dumps(receipt))
    if mutation != "artifact_sha":
        expected = consumer.digest(path.read_bytes())
    with pytest.raises(ValueError):
        consumer.read_source(path, expected)


async def test_unqualified_optional_version_never_imports_consumer(receipt_file, monkeypatch):
    path, expected, _ = receipt_file
    monkeypatch.setattr(consumer, "version", lambda name: "new-unqualified")
    monkeypatch.delitem(sys.modules, "gpt_researcher", raising=False)
    with pytest.raises(ValueError, match="Qualify"):
        await consumer.report_source(consumer.read_source(path, expected), "query", "config")
    assert "gpt_researcher" not in sys.modules


async def test_missing_report_reference_retains_the_failed_denominator(receipt_file, monkeypatch):
    path, expected, _ = receipt_file

    class MockResearcher:
        def __init__(self, **kwargs):
            pass

        async def write_report(self, **kwargs):
            return "A report that omitted its required source reference"

    monkeypatch.setattr(consumer, "version", lambda name: "0.16.0")
    monkeypatch.setitem(sys.modules, "gpt_researcher", SimpleNamespace(GPTResearcher=MockResearcher))
    result = await consumer.report_source(consumer.read_source(path, expected), "query", "config")
    assert result["status"] == "missing_reference" and result["reference_present"] is False
    assert result["report"] == "A report that omitted its required source reference"
    assert result["factual_success"] is False


def test_optional_gpt_cli_sigint_retains_started_report(tmp_path):
    """GIVEN interruption of mocked foreign inference WHEN the owner joins THEN a receipt remains."""
    script = '''
import asyncio, signal, sys
from types import SimpleNamespace
from examples import gpt_researcher_report as cli
class Engine:
    def __init__(self, **kwargs): pass
    async def write_report(self, **kwargs):
        asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)
        await asyncio.Event().wait()
cli.version = lambda name: "0.16.0"
sys.modules["gpt_researcher"] = SimpleNamespace(GPTResearcher=Engine)
cli.read_source = lambda *args: {"href": "urn:sha256:selected#t=0.3", "body": "{}"}
sys.argv = ["consumer", "--source-receipt", "unused", "--receipt-sha256", "0"*64,
            "--query", "selected", "--consumer-config", "unused", "--authorize-inference",
            "--output", sys.argv[1]]
cli.main()
'''
    output = tmp_path / "cancelled-report.json"
    result = subprocess.run([sys.executable, "-c", script, str(output)], capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 1, result.stderr
    receipt = json.loads(output.read_text())
    assert receipt["status"] == "cancelled" and "report" not in receipt
    assert receipt["trace"][0]["stage"] == "report" and receipt["trace"][0]["status"] == "started"
    assert receipt["provider_calls"] is None and receipt["currency"] is None
