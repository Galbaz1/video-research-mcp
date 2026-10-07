"""Optional descriptor and exact pinned external-handler contracts, without APIs.

Set VRM_QWEN_PINNED_SOURCE to an already acquired exact upstream checkout to
exercise source handlers. Missing external bytes are explicitly skipped; this
suite never acquires, installs or activates a provider runtime.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

import pytest
from pydantic import ValidationError


ROOT = Path(__file__).resolve().parents[1]
DESCRIPTOR = ROOT / "integrations/qwen/video-edit.json"
PIN = "07736672525443c7f8a3f6405eed37d2236f023f"
TOOLS = ("qwen_image", "wan_t2v", "wan_s2v", "happyhorse")


@pytest.fixture
def descriptor():
    """Read the separately selected external integration descriptor."""
    return json.loads(DESCRIPTOR.read_text())


def test_external_route_cannot_bootstrap_or_claim_artifact_acceptance(descriptor):
    """GIVEN an optional descriptor, WHEN selected, THEN core stays independent."""
    assert descriptor["source_revision"] == PIN
    assert descriptor["state"] == "external-disabled"
    assert descriptor["enabled_by_default"] is False
    assert descriptor["launch"]["install_on_startup"] is False
    assert descriptor["launch"]["args"] == ["-m", "qwen_mm_plugins_video_edit"]
    assert descriptor["module_entry"] == "qwen_mm_plugins_video_edit.__main__:main"
    assert descriptor["console_entry"] == "qwen-mm-plugins-video-edit"
    assert descriptor["runtime_requirements"]["mcp"] == ">=1.0.0,<2"
    assert not any(descriptor[key] for key in ("copied_paths", "imports", "bundled_assets"))
    for key in ("durable_operation_id", "artifact_sha256", "decoded_metadata"):
        assert descriptor["output_contract"][key] is False
    assert descriptor["verification"]["whole_bead_accepted"] is False
    assert descriptor["guards"]["discovery_generation_allowed"] is False


def test_descriptor_closure_has_launch_helpers_and_all_registered_tools(descriptor):
    """GIVEN discovery imports, THEN a four-tool-only closure is insufficient."""
    paths = {item["path"] for item in descriptor["source_closure"]}
    assert "src/mcp_framework.py" in paths
    for helper in ("env", "content", "api_dashscope", "retry", "native_mode"):
        assert f"src/shared/{helper}.py" in paths
    for tool in (*TOOLS, "qwen_tts", "minimax_tts"):
        assert any(path.endswith(f"/tools/{tool}.py") for path in paths)
    assert descriptor["license"]["spdx"] == "Apache-2.0"
    assert f"/{PIN}/LICENSE" in descriptor["license"]["grant_url"]
    assert descriptor["license"]["bundled_source"] is False


def test_skills_resolve_owned_contract_and_preserve_generation_guards():
    """GIVEN shipped skills, THEN their source and contract links are usable."""
    for name in ("qwen-image-integration", "qwen-video-integration"):
        skill = ROOT / "skills" / name / "SKILL.md"
        text = skill.read_text()
        assert f"name: {name}" in text
        assert PIN in text
        assert (skill.parent / "../../integrations/qwen/video-edit.json").resolve() == DESCRIPTOR
        assert "UNRUN" in text
        assert "before" in text and "spend" in text
        assert "hash" in text and "decode" in text


@pytest.fixture
def upstream(monkeypatch, tmp_path, descriptor):
    """Load hash-checked handlers with explicitly mocked external SDK/HTTP seams."""
    selected = os.environ.get("VRM_QWEN_PINNED_SOURCE")
    if not selected:
        pytest.skip("UNRUN: exact optional source fixture was not selected")
    root = Path(selected)
    for item in descriptor["source_closure"]:
        path = root / item["path"]
        assert path.is_file(), f"Missing exact closure body: {path}"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
    monkeypatch.syspath_prepend(str(root / "src"))
    monkeypatch.setenv("QWEN_MM_CONFIG", str(tmp_path / "absent-config"))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "mock-key-never-real")
    monkeypatch.setenv("DASHSCOPE_BASE_URL", "https://provider.invalid/api/v1")
    monkeypatch.setenv("QWEN_MM_NATIVE_MODE", "true")

    def deny_network(*args, **kwargs):
        raise AssertionError("Contract tests must never reach real network")

    monkeypatch.setattr(socket.socket, "connect", deny_network)
    monkeypatch.setattr(socket, "getaddrinfo", deny_network)
    response = SimpleNamespace(
        status_code=200,
        code=None,
        message="mock",
        output=SimpleNamespace(
            task_status="SUCCEEDED",
            video_url="https://artifact.invalid/video.mp4",
            choices=[SimpleNamespace(message=SimpleNamespace(
                content=[{"image": "https://artifact.invalid/image.png"}]
            ))],
        ),
    )
    sdk = ModuleType("dashscope")
    sdk.MultiModalConversation = SimpleNamespace(call=Mock(return_value=response))
    sdk.VideoSynthesis = SimpleNamespace(call=Mock(return_value=response))
    http = ModuleType("requests")
    post_response = SimpleNamespace(
        status_code=200,
        raise_for_status=Mock(),
        json=Mock(return_value={"output": {"task_id": "mock-job-1"}}),
    )
    get_response = SimpleNamespace(
        raise_for_status=Mock(),
        content=b"mock bytes, not a decoded artifact",
        json=Mock(return_value={"output": {
            "task_id": "mock-job-1", "task_status": "SUCCEEDED",
            "video_url": "https://artifact.invalid/video.mp4",
            "image_url": "https://artifact.invalid/image.png",
        }}),
    )
    http.post = Mock(return_value=post_response)
    http.get = Mock(return_value=get_response)
    monkeypatch.setitem(sys.modules, "dashscope", sdk)
    monkeypatch.setitem(sys.modules, "requests", http)
    # Preserve module identity without retaining external imports in later tests.
    for name in ("shared", "shared.env", "shared.content", "shared.api_dashscope", "shared.retry"):
        monkeypatch.delitem(sys.modules, name, raising=False)
    import shared.api_dashscope as api
    import shared.retry as retry

    monkeypatch.setattr(retry.time, "sleep", lambda seconds: None)
    modules = {}
    for name in TOOLS:
        path = root / descriptor["tools"][name]["source_path"]
        spec = importlib.util.spec_from_file_location(f"_qwen_contract_{name}", path)
        module = importlib.util.module_from_spec(spec)
        monkeypatch.setitem(sys.modules, spec.name, module)
        spec.loader.exec_module(module)
        modules[name] = module
    yield SimpleNamespace(
        modules=modules, sdk=sdk, http=http, response=response,
        post_response=post_response, get_response=get_response, api=api,
    )
    for name in list(sys.modules):
        if name == "shared" or name.startswith("shared."):
            sys.modules.pop(name, None)


@pytest.mark.parametrize("tool", TOOLS)
def test_advertised_schema_matches_actual_argument_model(upstream, descriptor, tool):
    """GIVEN source schemas, THEN mode/default/required declarations match discovery."""
    entry = descriptor["tools"][tool]
    model = getattr(upstream.modules[tool], entry["argument_model"])
    actual = model.model_json_schema()
    advertised = entry["input_schema"]
    assert advertised["required"] == actual.get("required", [])
    assert set(advertised["properties"]) == set(actual["properties"])
    for name, field in actual["properties"].items():
        advertised_field = advertised["properties"][name]
        if field.get("default", ...) is None:
            assert "default" not in advertised_field
        elif "default" in field:
            assert advertised_field["default"] == field["default"]
        if "enum" in field:
            assert advertised_field["enum"] == field["enum"]
        actual_types = field.get("type")
        if "anyOf" in field:
            # The pinned launcher intentionally strips Optional's null branch.
            actual_types = [part["type"] for part in field["anyOf"] if part["type"] != "null"]
            if len(actual_types) == 1:
                actual_types = actual_types[0]
        assert actual_types == advertised_field.get("type")
    selector = "action" if tool == "wan_s2v" else "mode"
    with pytest.raises(ValidationError):
        model.model_validate({selector: "invented-mode", "prompt": "p", "image_url": "i"})


CASES = [
    ("qwen_image", {"mode": "text_to_image", "prompt": "p"}, "qwen-image-2.0-pro"),
    ("qwen_image", {"mode": "image_edit", "prompt": "p", "image_urls": ["image"]}, "qwen-image-2.0-pro"),
    ("qwen_image", {"mode": "image_translate", "image_urls": ["image"]}, "qwen-mt-image"),
    ("wan_t2v", {"mode": "text_to_video", "prompt": "p"}, "wan2.7-t2v"),
    ("wan_t2v", {"mode": "first_frame", "prompt": "p", "first_frame_url": "first"}, "wan2.7-i2v"),
    ("wan_t2v", {"mode": "first_last_frame", "prompt": "p", "first_frame_url": "first", "last_frame_url": "last"}, "wan2.7-i2v"),
    ("wan_s2v", {"action": "detect", "image_url": "portrait"}, "wan2.2-s2v-detect"),
    ("wan_s2v", {"action": "generate", "image_url": "portrait", "audio_url": "audio"}, "wan2.2-s2v"),
    ("happyhorse", {"mode": "text_to_video", "prompt": "p"}, "happyhorse-1.0-t2v"),
    ("happyhorse", {"mode": "image_to_video", "image_url": "image"}, "happyhorse-1.0-i2v"),
    ("happyhorse", {"mode": "reference_to_video", "prompt": "p", "reference_image_urls": ["r"]}, "happyhorse-1.0-r2v"),
    ("happyhorse", {"mode": "video_edit", "prompt": "p", "video_url": "v"}, "happyhorse-1.0-video-edit"),
]


@pytest.mark.parametrize("tool,arguments,model", CASES)
def test_each_requested_mode_uses_its_exact_provider_payload(upstream, tool, arguments, model):
    """GIVEN one mode, WHEN the actual handler runs, THEN one correct mock submit occurs."""
    if model == "wan2.2-s2v-detect":
        upstream.post_response.json.return_value = {"output": {"check_pass": True, "humanoid": True}}
    result = upstream.modules[tool].handle(arguments)
    text = result[0]["text"]
    assert not text.startswith("Error:"), text
    calls = (upstream.sdk.MultiModalConversation.call.call_args_list
             + upstream.sdk.VideoSynthesis.call.call_args_list
             + upstream.http.post.call_args_list)
    assert len(calls) == 1
    payload = calls[0].kwargs
    assert payload.get("model", payload.get("json", {}).get("model")) == model
    if tool == "wan_t2v" and arguments["mode"] == "first_last_frame":
        assert payload["media"] == [
            {"type": "first_frame", "url": "first"}, {"type": "last_frame", "url": "last"}
        ]
        assert "ratio" not in payload
    assert "artifact_sha256" not in text


@pytest.mark.parametrize("tool,arguments,model", CASES)
def test_each_mode_retains_mock_provider_failure(upstream, tool, arguments, model):
    """GIVEN a provider failure, THEN every declared mode reports an error."""
    upstream.response.status_code = 400
    upstream.response.code = "Rejected"
    upstream.response.message = "mock rejection"
    upstream.post_response.status_code = 400
    upstream.post_response.json.return_value = {"code": "Rejected", "message": "mock rejection"}
    result = upstream.modules[tool].handle(arguments)
    assert result[0]["text"].startswith("Error:"), result


@pytest.mark.parametrize("tool,arguments", [
    ("wan_s2v", {"action": "generate", "image_url": "p", "audio_url": "a"}),
    ("happyhorse", {"mode": "text_to_video", "prompt": "p"}),
])
@pytest.mark.parametrize("outcome", ["FAILED", "TIMEOUT"])
def test_async_failure_timeout_retains_id_without_resubmitting(upstream, tool, arguments, outcome):
    """GIVEN an existing job, THEN terminal failure or timeout never submits again."""
    if outcome == "TIMEOUT":
        arguments = {**arguments, "poll_timeout": 0}
    else:
        upstream.get_response.json.return_value = {"output": {
            "task_status": "FAILED", "task_id": "mock-job-1", "message": "failed fixture"
        }}
    result = upstream.modules[tool].handle(arguments)[0]["text"]
    assert result.startswith("Error:") and "mock-job-1" in result
    assert upstream.http.post.call_count == 1
    assert upstream.http.get.call_count == (0 if outcome == "TIMEOUT" else 1)
    if outcome == "TIMEOUT":
        assert "may still be running" in result


def test_alpha_intent_would_be_dropped_by_source_model(upstream, descriptor):
    """GIVEN alpha intent, THEN omission must be surfaced before submission."""
    model = upstream.modules["qwen_image"].QwenImageArgs
    parsed = model.model_validate({"mode": "text_to_image", "transparent_background": True})
    assert "transparent_background" not in parsed.model_dump()
    assert descriptor["guards"]["transparent_background"]["supported"] is False
    assert upstream.http.post.call_count == 0


def test_reference_overflow_and_ignored_edit_fields_are_real_source_limits(upstream, descriptor):
    """GIVEN excess references and edit settings, THEN declared losses match payload."""
    upstream.modules["happyhorse"].handle({
        "mode": "video_edit", "prompt": "p", "video_url": "v", "duration": 60,
        "ratio": "9:16", "reference_image_urls": [str(i) for i in range(7)],
    })
    payload = upstream.http.post.call_args.kwargs["json"]
    assert len(payload["input"]["media"]) == 6
    assert "duration" not in payload["parameters"] and "ratio" not in payload["parameters"]
    assert descriptor["guards"]["reference_overflow"]["upstream_drops"]["happyhorse.video_edit"] == 5
    assert "15s" in descriptor["guards"]["provider_truncation"]["happyhorse.video_edit"]


def test_ambiguous_submit_failure_can_duplicate_upstream_effect(upstream, descriptor):
    """GIVEN an ambiguous first POST, THEN upstream retries and lacks idempotency."""
    upstream.http.post.side_effect = [RuntimeError("unknown effect"), upstream.post_response]
    task_id, _ = upstream.api.submit_dashscope_async("fixture", {}, "mock")
    assert task_id == "mock-job-1" and upstream.http.post.call_count == 2
    assert descriptor["guards"]["upstream_retry"]["idempotency_guaranteed"] is False
    assert "Idempotency-Key" not in upstream.http.post.call_args.kwargs["headers"]


def test_expired_download_and_existing_unverified_path_are_distinct(upstream, tmp_path):
    """GIVEN expiry or a stale file, THEN neither is a verified final artifact."""
    target = tmp_path / "result.png"
    error = RuntimeError("expired fixture URL")
    error.response = SimpleNamespace(status_code=404)
    upstream.get_response.raise_for_status.side_effect = error
    with pytest.raises(RuntimeError, match="expired fixture"):
        upstream.api.save_url_to_dir("https://artifact.invalid/expired", str(target))
    assert not target.exists() and upstream.http.get.call_count == 1
    upstream.http.get.reset_mock()
    target.write_bytes(b"stale unverified data")
    assert upstream.api.save_url_to_dir("https://artifact.invalid/new", str(target)) == str(target)
    assert target.read_bytes() == b"stale unverified data"
    assert upstream.http.get.call_count == 0
