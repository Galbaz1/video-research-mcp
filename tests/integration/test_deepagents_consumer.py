"""Maintain the selected optional task/tool shape with all foreign inference mocked."""

import asyncio
import json
import subprocess
import sys
from types import SimpleNamespace

import pytest

from examples import deepagents_report as consumer
from tests.integration.test_external_harness_contract import selected  # noqa: F401
from video_research_mcp.integrations.external_harness import source_record


@pytest.fixture
def engine(monkeypatch):
    """Mock only the optional engine/middleware/tool providers, retaining own guard logic."""
    seen = {}

    def tool(**kwargs):
        seen["tool_options"] = kwargs
        return lambda function: function

    def register(key, profile):
        seen["profile"] = (key, profile)

    def create(**kwargs):
        seen["create"] = kwargs

        async def invoke(state, *, config):
            seen["invoke"] = (state, config)
            specialist = kwargs["subagents"][0]
            request = SimpleNamespace(tool_call={"name": "task", "args": {"subagent_type": "video_source"}})

            async def task_handler(request):
                child_request = SimpleNamespace(tool_call={"name": "video_source", "args": {}})

                async def source_handler(request):
                    body, artifact = specialist["tools"][0]()
                    seen["source"] = (body, artifact)
                    return body

                return await specialist["middleware"][0].awrap_tool_call(child_request, source_handler)

            body = await kwargs["middleware"][0].awrap_tool_call(request, task_handler)
            refs = json.loads(body)["source_references"]
            return {"structured_response": kwargs["response_format"](report=f"Measured point [{refs[0]}]", source_references=refs)}

        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(consumer, "version", lambda name: "0.7.18")
    monkeypatch.setitem(sys.modules, "deepagents", SimpleNamespace(
        HarnessProfile=lambda **kwargs: kwargs, GeneralPurposeSubagentProfile=lambda **kwargs: kwargs,
        register_harness_profile=register, create_deep_agent=create,
    ))
    monkeypatch.setitem(sys.modules, "langchain.agents.middleware.types", SimpleNamespace(AgentMiddleware=object))
    monkeypatch.setitem(sys.modules, "langchain_core.tools", SimpleNamespace(tool=tool))
    return seen


async def test_specialist_task_consumes_exact_video_tool_record(selected, engine):  # noqa: F811
    request, result = selected
    record = source_record(result, request)
    report = await consumer.report_source(record, "Report point metadata", "selected:operator-model")
    assert report["status"] == "complete" and report["factual_success"] is False
    assert report["source_references"] == [record["href"]]
    assert engine["source"] == (record["body"], record)
    key, profile = engine["profile"]
    assert key == "selected:operator-model"
    assert profile["general_purpose_subagent"] == {"enabled": False}
    assert profile["excluded_tools"] == {"ls", "read_file", "write_file", "edit_file", "delete", "glob", "grep", "execute", "write_todos"}
    assert engine["create"]["tools"] == []
    assert engine["create"]["memory"] is None and engine["create"]["skills"] is None
    assert engine["invoke"][1] == {"recursion_limit": 8}
    assert engine["tool_options"] == {"response_format": "content_and_artifact"}
    assert [event["stage"] for event in report["trace"]] == ["task", "source_tool", "source_returned"]


@pytest.mark.parametrize("level", ["parent", "child"])
async def test_guard_denies_other_tools_and_repeats_without_handler(level, engine):
    trace = []
    parent, child = consumer.source_guards(trace)
    guard = parent if level == "parent" else child
    count = 0

    async def handler(request):
        nonlocal count
        count += 1

    allowed = {"name": "task", "args": {"subagent_type": "video_source"}} if level == "parent" else {"name": "video_source", "args": {}}
    for denied in ["execute", "write_file", "delete", "task" if level == "child" else "video_source"]:
        with pytest.raises(PermissionError):
            await guard.awrap_tool_call(SimpleNamespace(tool_call={"name": denied, "args": {}}), handler)
    await guard.awrap_tool_call(SimpleNamespace(tool_call=allowed), handler)
    with pytest.raises(PermissionError):
        await guard.awrap_tool_call(SimpleNamespace(tool_call=allowed), handler)
    assert count == 1 and trace[-1]["status"] == "refused"


async def test_foreign_version_is_a_retained_failure_before_import(selected, monkeypatch):  # noqa: F811
    request, result = selected
    monkeypatch.setattr(consumer, "version", lambda name: "unqualified")
    monkeypatch.delitem(sys.modules, "deepagents", raising=False)
    report = await consumer.report_source(source_record(result, request), "query", "selected:model")
    assert report["status"] == "failed" and report["trace"] == []
    assert report["provider_calls"] is None and "deepagents" not in sys.modules


async def test_cancelled_task_owner_keeps_started_task_trace(selected, engine, monkeypatch):  # noqa: F811
    """GIVEN a cancelled foreign task WHEN its owner joins THEN its attempt remains visible."""
    entered, joined = asyncio.Event(), asyncio.Event()

    def create(**kwargs):
        async def invoke(*args, **options):
            async def blocked(request):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    joined.set()

            request = SimpleNamespace(tool_call={"name": "task", "args": {"subagent_type": "video_source"}})
            return await kwargs["middleware"][0].awrap_tool_call(request, blocked)

        return SimpleNamespace(ainvoke=invoke)

    monkeypatch.setattr(sys.modules["deepagents"], "create_deep_agent", create)
    request, result = selected
    task = asyncio.create_task(consumer.report_source(source_record(result, request), "query", "selected:model"))
    await entered.wait()
    task.cancel()
    receipt = await task
    assert joined.is_set() and receipt["status"] == "cancelled" and "report" not in receipt
    assert receipt["trace"] == [{"stage": "task", "subagent": "video_source", "status": "started"}]
    assert receipt["provider_calls"] is None and receipt["error_type"] == "CancelledError"


def test_optional_deep_cli_sigint_retains_started_task(tmp_path):
    """GIVEN SIGINT during a mocked specialist WHEN the CLI joins THEN it writes the task trace."""
    script = '''
import asyncio, signal, sys
from types import SimpleNamespace
from examples import deepagents_report as cli
def create(**kwargs):
    async def invoke(*args, **options):
        async def blocked(request):
            asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)
            await asyncio.Event().wait()
        request = SimpleNamespace(tool_call={"name": "task", "args": {"subagent_type": "video_source"}})
        return await kwargs["middleware"][0].awrap_tool_call(request, blocked)
    return SimpleNamespace(ainvoke=invoke)
cli.version = lambda name: "0.7.18"
sys.modules["deepagents"] = SimpleNamespace(create_deep_agent=create,
    HarnessProfile=lambda **kwargs: kwargs, GeneralPurposeSubagentProfile=lambda **kwargs: kwargs,
    register_harness_profile=lambda *args: None)
sys.modules["langchain.agents.middleware.types"] = SimpleNamespace(AgentMiddleware=object)
sys.modules["langchain_core.tools"] = SimpleNamespace(tool=lambda **kwargs: lambda function: function)
cli.read_source = lambda *args: {"href": "urn:sha256:selected#t=0.3", "body": "{}"}
sys.argv = ["consumer", "--source-receipt", "unused", "--receipt-sha256", "0"*64,
            "--query", "selected", "--model", "selected:model", "--authorize-inference",
            "--output", sys.argv[1]]
cli.main()
'''
    output = tmp_path / "cancelled-task.json"
    result = subprocess.run([sys.executable, "-c", script, str(output)], capture_output=True,
                            text=True, timeout=10)
    assert result.returncode == 1, result.stderr
    receipt = json.loads(output.read_text())
    assert receipt["status"] == "cancelled" and "report" not in receipt
    assert receipt["trace"] == [{"stage": "task", "subagent": "video_source", "status": "started"}]
    assert receipt["source_receipt_sha256"] == "0" * 64
