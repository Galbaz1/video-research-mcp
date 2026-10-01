"""Exercise configured text protocol, refusal, accounting and credential boundaries."""

import asyncio
import hashlib
import json
from urllib.parse import quote, quote_plus

import pytest

from video_research_mcp.config import get_config, update_config
from video_research_mcp.models.text_provider import TextBackend
from video_research_mcp.tools.text_provider import provider_capabilities, text_generate

SCHEMA = {"type": "object", "properties": {"answer": {"type": "string"}},
          "required": ["answer"], "additionalProperties": False}
KEY = "owned text/key+ sentinel"
BASE = "https://owned.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1"


@pytest.fixture
def route(clean_config, monkeypatch):
    """Provide one nonreal regional account; Gemini/vision credentials stay separate."""
    monkeypatch.setenv("OWNED_TEXT_API_KEY", KEY)
    update_config(text_backends={"regional": {"base_url": BASE, "model": "owned-text-model",
                                              "api_key_env": "OWNED_TEXT_API_KEY"}})
    return {"backend": "regional", "instruction": "Summarize the supplied text", "context": "Owned source text.",
            "output_schema": SCHEMA, "dry_run": False, "authorize_submission": True}


def response(content=None, **kwargs):
    """Build a concrete provider wire object for exactly one structured answer."""
    body = {"id": "owned-response", "model": "owned-text-model", "choices": [{"finish_reason": "stop",
            "message": {"content": json.dumps({"answer": "unverified inference"}) if content is None else content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
                      "completion_tokens_details": {"reasoning_tokens": 2}}}
    body.update(kwargs)
    return json.dumps(body).encode()


def transport(monkeypatch, raw=None, status=200):
    """Replace only the external exchange; public parsing/selection stays active."""
    seen = []
    async def exchange(url, **kwargs):
        seen.append({"url": url, **kwargs})
        return status, response() if raw is None else raw
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", exchange)
    return seen


async def test_exact_structured_request_usage_and_lineage(route, monkeypatch):
    """GIVEN a selected account WHEN submitted THEN full JSON contract and usage survive."""
    seen = transport(monkeypatch)
    value = await text_generate(route)
    assert value["status"] == "complete" and value["factual_success"] is False
    assert value["output"] == {"answer": "unverified inference"}
    assert value["backend"]["provider"] == "dashscope"
    assert len(seen) == 1 and seen[0]["url"] == BASE + "/chat/completions"
    assert seen[0]["headers"]["Authorization"] == "Bearer " + KEY
    assert seen[0]["method"] == "POST" and seen[0]["local"] is False
    payload = json.loads(seen[0]["content"])
    assert payload["model"] == "owned-text-model" and payload["stream"] is False
    assert payload["max_completion_tokens"] == 2048 and "max_tokens" not in payload
    assert payload["response_format"] == {"type": "json_object"}
    assert all(isinstance(m["content"], str) for m in payload["messages"])
    assert json.loads(payload["messages"][1]["content"])["context_data"] == route["context"]
    assert json.dumps(SCHEMA, sort_keys=True) in payload["messages"][0]["content"]
    assert "tools" not in payload and "thinking_level" not in payload
    report = value["execution"]
    assert report["http_exchange_attempts"] == 1 and report["usage_complete"] is True
    assert report["usage"] == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15, "reasoning_tokens": 2}
    assert report["request_body_sha256"] == hashlib.sha256(seen[0]["content"]).hexdigest()
    assert report["cost_usd"] is None and report["physical_wire_attempts"] is None
    assert report["provider_response_model"] == "owned-text-model" and report["provider_response_id"] == "owned-response"
    assert not report["input_token_bound_verified"] and not report["charge_bound_verified"]
    assert KEY not in json.dumps(value)


async def test_plans_and_missing_authority_never_exchange(route, monkeypatch):
    """GIVEN planning or no workflow grant THEN no configured service is invoked."""
    seen = transport(monkeypatch)
    planned = await text_generate({**route, "dry_run": True, "authorize_submission": False})
    denied = await text_generate({**route, "authorize_submission": False})
    assert planned["status"] == "planned" and planned["output"] is None
    assert denied["category"] == "PERMISSION_DENIED"
    assert planned["execution"]["http_exchange_attempts"] == denied["execution"]["http_exchange_attempts"] == 0
    assert seen == []


async def test_selected_key_absence_has_no_account_fallback(route, monkeypatch):
    """GIVEN Gemini is configured but the selected key is missing THEN submission fails."""
    seen = transport(monkeypatch)
    monkeypatch.delenv("OWNED_TEXT_API_KEY")
    value = await text_generate(route)
    assert "credential is missing" in value["error"] and value["execution"]["http_exchange_attempts"] == 0
    assert seen == [] and get_config().gemini_api_key


@pytest.mark.parametrize("key", ["   ", "${OWNED_TEXT_API_KEY}", "$OWNED_TEXT_API_KEY"])
async def test_placeholder_keys_fail_before_transport(route, monkeypatch, key):
    """GIVEN a setup placeholder THEN readiness and execution agree on missing credentials."""
    seen = transport(monkeypatch)
    monkeypatch.setenv("OWNED_TEXT_API_KEY", key)
    value = await text_generate(route)
    inspected = await provider_capabilities("text:regional")
    assert "credential is missing" in value["error"]
    assert value["execution"]["http_exchange_attempts"] == 0 and seen == []
    assert inspected["backends"][0]["configured"] is False


async def test_key_in_selected_profile_name_is_withheld(route, monkeypatch):
    """GIVEN selected secret in route metadata THEN failure returns no secret-bearing backend."""
    key = "owned_key_sentinel"
    monkeypatch.setenv("OWNED_TEXT_API_KEY", key)
    update_config(text_backends={key: get_config().text_backends["regional"]})
    seen = transport(monkeypatch)
    value = await text_generate({**route, "backend": key})
    assert value["category"] == "PERMISSION_DENIED" and value["backend"] == {}
    assert key not in json.dumps(value) and seen == []
    for backend in (None, "text:" + key):
        inspected = await provider_capabilities(backend)
        assert inspected["category"] == "PERMISSION_DENIED"
        assert inspected["provider_calls"] == 0 and key not in json.dumps(inspected)


@pytest.mark.parametrize("cap", ["images", "video", "audio", "files", "grounding", "embeddings", "rerank"])
async def test_incompatible_operations_fail_before_exchange(route, monkeypatch, cap):
    """GIVEN unsupported operations THEN text adapter and inspection refuse them."""
    seen = transport(monkeypatch)
    value = await text_generate({**route, "required_capabilities": [cap]})
    assert cap in value["error"] and value["execution"]["http_exchange_attempts"] == 0
    inspected = await provider_capabilities("text:regional", [cap])
    assert cap in inspected["error"] and inspected["provider_calls"] == 0
    assert seen == []


@pytest.mark.parametrize("cap", [{"max_input_tokens": 100}, {"max_total_tokens": 3000}, {"max_cost_usd": 1.0}])
async def test_unprovable_hard_caps_fail_closed(route, monkeypatch, cap):
    """GIVEN a literal unknown token/currency ceiling THEN no inference is admitted."""
    seen = transport(monkeypatch)
    value = await text_generate({**route, **cap})
    assert "cannot verify" in value["error"] and value["execution"]["http_exchange_attempts"] == 0
    assert seen == []


@pytest.mark.parametrize("status", [301, 400, 401, 403, 429, 500])
async def test_http_errors_retain_one_attempt_without_retry_or_body(route, monkeypatch, status):
    """GIVEN an error/redirect body THEN attempt metadata survives without resubmission."""
    seen = transport(monkeypatch, ("prefix" + quote(KEY, safe="") + "suffix").encode(), status)
    value = await text_generate(route)
    assert "error" in value and value["retryable"] is False
    assert value["execution"]["http_exchange_attempts"] == 1 and value["execution"]["http_status"] == status
    assert len(seen) == 1 and value["execution"]["usage"] is None
    assert KEY not in json.dumps(value) and quote(KEY, safe="") not in json.dumps(value)
    if status in (401, 403):
        assert value["category"] == "API_PERMISSION_DENIED"
    if status == 429:
        assert value["category"] == "API_QUOTA_EXCEEDED"


@pytest.mark.parametrize("body", [b'not JSON', b'{"choices": NaN}', response('[]'), response('{"answer": NaN}'),
    response('{"invented": true}'), response('not JSON'), response('"' + 'a' * (128 * 1024) + '"'),
    response(choices=[]), response(choices=[{}, {}]), response(choices=[{"finish_reason": "length", "message": {"content": "{}"}}]),
    response(choices=[{"finish_reason": "stop", "message": {"refusal": "no", "content": "{}"}}]),
    response(choices=[{"finish_reason": "stop", "message": {"tool_calls": [{}], "content": "{}"}}])])
async def test_invalid_refused_or_truncated_outputs_remain_failures(route, monkeypatch, body):
    """GIVEN incomplete/invalid inference THEN no JSON repair or success promotion occurs."""
    seen = transport(monkeypatch, body)
    value = await text_generate(route)
    assert "error" in value and value["execution"]["http_exchange_attempts"] == 1
    assert value["execution"]["response_sha256"] == hashlib.sha256(body).hexdigest()
    assert value["retryable"] is False and len(seen) == 1


async def test_usage_unknown_and_failed_answer_usage_are_distinct(route, monkeypatch):
    """GIVEN absent telemetry or rejected text THEN observed counts remain separate."""
    transport(monkeypatch, response(usage=None))
    value = await text_generate(route)
    assert value["status"] == "complete" and value["execution"]["usage"] is None
    assert value["execution"]["usage_complete"] is False
    transport(monkeypatch, response('{"invented": true}'))
    bad = await text_generate(route)
    assert "error" in bad and bad["execution"]["usage"]["total_tokens"] == 15


@pytest.mark.parametrize("material", [KEY, quote(KEY, safe=""), quote_plus(KEY)])
async def test_selected_credentials_are_blocked_in_data_and_responses(route, monkeypatch, material):
    """GIVEN raw/encoded selected key text THEN neither submission nor public echo is allowed."""
    seen = transport(monkeypatch)
    blocked = await text_generate({**route, "context": "prefix" + material + "suffix"})
    assert blocked["execution"]["http_exchange_attempts"] == 0 and seen == []
    transport(monkeypatch, response(json.dumps({"answer": "prefix" + material + "suffix"})))
    echoed = await text_generate(route)
    assert "error" in echoed and echoed["execution"]["http_exchange_attempts"] == 1
    assert material not in json.dumps(blocked) + json.dumps(echoed)


async def test_foreign_exception_diagnostics_are_withheld(route, monkeypatch):
    """GIVEN a transport exception with embedded credentials THEN retain accounting only."""
    async def exchange(*args, **kwargs):
        raise ValueError("FOREIGN_DIAGNOSTICprefix" + KEY + quote(KEY, safe="") + "suffix")
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", exchange)
    value = await text_generate(route)
    assert "FOREIGN_DIAGNOSTIC" not in json.dumps(value) and KEY not in json.dumps(value)
    assert value["execution"]["http_exchange_attempts"] == 1 and value["execution"]["usage"] is None


async def test_real_config_drift_retains_usage_without_promoting_answer(route, monkeypatch):
    """GIVEN the selected account changes during exchange THEN answer promotion stops."""
    async def exchange(*args, **kwargs):
        monkeypatch.setenv("OWNED_TEXT_API_KEY", "other-owned-account")
        return 200, response()
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", exchange)
    value = await text_generate(route)
    assert "account changed" in value["error"] and value["execution"]["http_exchange_attempts"] == 1
    assert value["execution"]["usage"]["total_tokens"] == 15


@pytest.mark.parametrize("deadline", [False, True])
async def test_cancellation_and_deadline_join_the_external_task(route, monkeypatch, deadline):
    """GIVEN a pending transport THEN deadline/cancellation retains one attempt and joins."""
    started, joined = asyncio.Event(), asyncio.Event()
    async def exchange(*args, **kwargs):
        try:
            started.set()
            await asyncio.sleep(60)
        finally:
            joined.set()
    monkeypatch.setattr("video_research_mcp.vision_http.exchange", exchange)
    task = asyncio.create_task(text_generate({**route, "timeout_seconds": .01 if deadline else 60}))
    await started.wait()
    if not deadline:
        task.cancel()
    value = await task
    assert "error" in value and joined.is_set() and task.done()
    assert value["execution"]["http_exchange_attempts"] == 1 and value["execution"]["usage"] is None


async def test_local_json_schema_route_is_explicit(route, monkeypatch):
    """GIVEN a configured local endpoint THEN the exact local JSON schema route is used."""
    update_config(text_backends={"local": {"provider": "local_compatible", "base_url": "http://127.0.0.1:1234/v1",
                   "model": "owned-local", "structured_format": "json_schema"}})
    seen = transport(monkeypatch)
    value = await text_generate({**route, "backend": "local"})
    assert value["status"] == "complete" and seen[0]["local"] is True
    assert "Authorization" not in seen[0]["headers"]
    assert json.loads(seen[0]["content"])["response_format"]["json_schema"]["schema"] == SCHEMA


@pytest.mark.parametrize("profile", [
    {"base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "owned", "api_key_env": "OWNED_TEXT_API_KEY"},
    {"base_url": "https://owned.us-east-1.maas.aliyuncs.com/compatible-mode/v1", "model": "owned"},
    {"base_url": BASE + "?credential=secret", "model": "owned", "api_key_env": "OWNED_TEXT_API_KEY"},
    {"provider": "local_compatible", "base_url": "http://localhost:1234/v1", "model": "owned"},
    {"provider": "local_compatible", "base_url": "http://10.1.2.3/v1", "model": "owned"},
])
def test_region_credentials_and_loopback_profiles_are_fenced(profile):
    """GIVEN a mismatched origin THEN profile validation rejects it without networking."""
    with pytest.raises(ValueError):
        TextBackend.model_validate(profile)


@pytest.mark.parametrize("schema", [{"type": "array"}, {"type": "object", "$ref": "https://evil.invalid/schema"},
    {"type": "object", "properties": {"x": {"$dynamicRef": "#somewhere"}}},
    {"type": "object", "description": "a" * 32769}])
async def test_nonlocal_unbounded_schemas_fail_before_exchange(route, monkeypatch, schema):
    """GIVEN invalid/reference schemas THEN schema validation has no remote side effects."""
    seen = transport(monkeypatch)
    value = await text_generate({**route, "output_schema": schema})
    assert "error" in value and value["execution"]["http_exchange_attempts"] == 0 and seen == []


def test_config_allowlists_and_reranker_selection_match_actual_implementations(clean_config, monkeypatch):
    """GIVEN explicit optional configuration THEN unsupported/repeated providers fail early."""
    monkeypatch.setenv("SEARCH_BACKENDS_JSON", '["tavily","serper"]')
    monkeypatch.setenv("TEXT_BACKENDS_JSON", '{"local":{"provider":"local_compatible","base_url":"http://127.0.0.1:1234/v1","model":"owned"}}')
    cfg = get_config()
    assert cfg.search_backends == ["tavily", "serper"] and cfg.text_backends["local"].provider == "local_compatible"
    with pytest.raises(ValueError, match="unique"):
        update_config(search_backends=["serper", "serper"])
    with pytest.raises(ValueError):
        update_config(search_backends=["unsupported"])
    with pytest.raises(ValueError, match="cohere"):
        update_config(reranker_provider="imaginary")


def test_optional_readiness_is_redacted_and_does_not_probe(route):
    """GIVEN explicit profiles THEN read-only selection reports no model/endpoint/key value."""
    from scripts.inspect_provider_readiness import optional_adapter_profiles

    env = {"TEXT_BACKENDS_JSON": json.dumps({"regional": get_config().text_backends["regional"].model_dump(mode="json")}),
           "OWNED_TEXT_API_KEY": KEY, "SEARCH_BACKENDS_JSON": '["tavily","serper"]', "TAVILY_API_KEY": "owned-search-key"}
    value = optional_adapter_profiles(env)
    assert value["text"][0]["state"] == "configured-but-unverified"
    assert value["search"][0]["state"] == "missing" and value["search"][1]["state"] == "configured-but-unverified"
    assert value["run_authority"] == "not-granted" and value["live_verified"] is False
    assert all(s not in json.dumps(value) for s in (KEY, "owned-search-key", BASE, "owned-text-model"))
    assert optional_adapter_profiles({"TEXT_BACKENDS_JSON": 'notjson'})["text_config_invalid"]
    assert optional_adapter_profiles({"SEARCH_BACKENDS_JSON": '[["tavily"]]'})["search_config_invalid"]


async def test_four_role_profiles_select_independent_models_and_output_limits(route, monkeypatch):
    """GIVEN separate role profiles THEN each actual request selects its own model/cap."""
    roles = ("summary", "research", "compression", "report")
    profiles = {role: {"base_url": BASE, "model": "owned-" + role,
                      "api_key_env": "OWNED_TEXT_API_KEY"} for role in roles}
    update_config(text_backends=profiles)
    seen = transport(monkeypatch)
    for i, role in enumerate(roles):
        value = await text_generate({**route, "backend": role, "max_output_tokens": 100 + i,
                                     "instruction": "Create the " + role + " from supplied context"})
        assert value["status"] == "complete" and value["backend"]["model"] == "owned-" + role
        payload = json.loads(seen[-1]["content"])
        assert payload["model"] == "owned-" + role and payload["max_completion_tokens"] == 100 + i
        assert value["execution"]["usage"]["total_tokens"] == 15
        assert value["execution"]["provider_response_model"] == "owned-text-model"
        assert value["execution"]["response_identity_authority"] == "provider_response_observation; unverified"
    assert len(seen) == 4


async def test_json_escaped_credentials_cannot_cross_decoded_output_boundary(route, monkeypatch):
    """GIVEN escaped wire text/identity THEN decoding cannot promote a selected credential."""
    escaped = ''.join('\\u%04x' % ord(c) for c in KEY)
    bodies = [response('{"answer":"' + escaped + '"}'),
              response().decode().replace('"owned-response"', '"' + escaped + '"').encode()]
    for body in bodies:
        seen = transport(monkeypatch, body)
        value = await text_generate(route)
        assert "error" in value and value["execution"]["http_exchange_attempts"] == 1
        assert KEY not in json.dumps(value) and len(seen) == 1


@pytest.mark.parametrize("schema", [
    {"type": "object", "properties": {"x": {"type": "string", "pattern": "^(a+)+$"}}},
    {"type": "object", "patternProperties": {"^(a+)+$": {"type": "string"}}},
    {"type": "object", "$defs": {"nested": {"if": {"properties": {"x": {"pattern": "^(a+)+$"}}}}}},
])
async def test_regex_schema_admission_cannot_block_loop_or_submit(route, monkeypatch, schema):
    """GIVEN unbounded regex validation THEN admission refuses promptly without HTTP work."""
    seen = transport(monkeypatch)
    heartbeat = asyncio.create_task(asyncio.sleep(0))
    try:
        value = await asyncio.wait_for(text_generate({**route, "output_schema": schema}), 0.5)
        await asyncio.wait_for(heartbeat, 0.5)
    finally:
        if not heartbeat.done():
            heartbeat.cancel()
            await asyncio.gather(heartbeat, return_exceptions=True)
    assert "error" in value and value["execution"]["http_exchange_attempts"] == 0
    assert seen == []


async def test_regex_named_data_properties_remain_valid(route, monkeypatch):
    """GIVEN ordinary properties or const data named pattern THEN keyword checks preserve them."""
    schema = {"type": "object", "properties": {"pattern": {"type": "string"},
              "metadata": {"const": {"pattern": "^(a+)+$", "$ref": "ordinary data"}}},
              "required": ["pattern", "metadata"], "additionalProperties": False}
    answer = {"pattern": "ordinary text", "metadata": {"pattern": "^(a+)+$", "$ref": "ordinary data"}}
    seen = transport(monkeypatch, response(json.dumps(answer)))
    value = await text_generate({**route, "output_schema": schema})
    assert value["status"] == "complete" and value["output"] == answer and len(seen) == 1
