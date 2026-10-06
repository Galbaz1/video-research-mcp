"""Provider failures remain safe through the public context diagnostics boundary."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import video_research_mcp.context_cache as cc_mod
from video_research_mcp.tools.infra import infra_cache


@pytest.mark.parametrize(
    "error,expected_reason",
    [
        (RuntimeError("provider dummy-secret https://example.org/private?sig=dummy-secret"), "api_error"),
        (ValueError("private request fragment dummy-secret"), "api_error"),
        (RuntimeError("too few tokens; dummy-secret"), "suppressed:too_few_tokens"),
        (RuntimeError("minimum token count; dummy-secret"), "suppressed:too_few_tokens"),
    ],
)
async def test_provider_failure_is_safe_in_public_context_diagnostics(
    monkeypatch, caplog, error, expected_reason
):
    """GIVEN foreign error text WHEN context diagnostics are read THEN only safe reasons escape."""
    monkeypatch.setattr(cc_mod, "_registry", {})
    monkeypatch.setattr(cc_mod, "_pending", {})
    monkeypatch.setattr(cc_mod, "_suppressed", set())
    monkeypatch.setattr(cc_mod, "_last_failure", {})
    monkeypatch.setattr(cc_mod, "_loaded", True)
    monkeypatch.setattr(
        cc_mod, "get_config", lambda: SimpleNamespace(context_cache_ttl_seconds=60)
    )
    client = MagicMock()
    client.aio.caches.create = AsyncMock(side_effect=error)
    monkeypatch.setattr(cc_mod.GeminiClient, "get", lambda: client)

    assert await cc_mod.get_or_create("dummy-content", [], "dummy-model") is None
    result = await infra_cache(action="context")

    assert result["recent_failures"] == {"dummy-content/dummy-model": expected_reason}
    assert cc_mod.failure_reason("dummy-content", "dummy-model") == expected_reason
    assert "dummy-secret" not in str(result)
    assert "dummy-secret" not in caplog.text
    client.aio.caches.create.assert_awaited_once()
    if expected_reason == "suppressed:too_few_tokens":
        assert await cc_mod.get_or_create("dummy-content", [], "dummy-model") is None
        client.aio.caches.create.assert_awaited_once()
    else:
        assert not cc_mod._suppressed
