"""Non-idempotent interaction creation must never repeat in SDK transport."""

import httpx
import pytest
from google import genai

from video_research_mcp.client import GeminiClient


async def test_shared_client_disables_interactions_transport_retry(monkeypatch):
    """GIVEN a 503 THEN one real SDK transmission is retained as ambiguous failure."""
    requests = []

    def transport(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"message": "fixture unavailable"}})

    client = genai.Client(
        api_key="fixture",
        http_options={
            "base_url": "https://fixture.invalid",
            "async_client_args": {"transport": httpx.MockTransport(transport)},
        },
    )
    monkeypatch.setattr(genai, "Client", lambda **kwargs: client)
    monkeypatch.setattr(GeminiClient, "_clients", {})
    shared = GeminiClient.get("fixture")
    try:
        with pytest.raises(Exception) as failed:
            await shared.aio.interactions.create(model="fixture", input="owned fixture")
        assert type(failed.value).__name__ == "InternalServerError"
        assert len(requests) == 1
        assert requests[0].url.host == "fixture.invalid"
        assert shared.aio.interactions.sdk_configuration.retry_config is None
    finally:
        await shared.aio.aclose()
        shared.close()


async def test_durable_generation_does_not_retry_ambiguous_failure(monkeypatch):
    """GIVEN durable submission scope THEN SDK and outer generation transmit once."""
    from video_research_mcp.job_execution import job_submission

    requests = []
    actual_client = genai.Client

    def transport(request):
        requests.append(request)
        return httpx.Response(503, json={"error": {"message": "fixture unavailable"}})

    def factory(**kwargs):
        options = kwargs.pop("http_options").model_dump(exclude_none=True)
        return actual_client(
            **kwargs,
            http_options={
                **options,
                "base_url": "https://fixture.invalid",
                "async_client_args": {"transport": httpx.MockTransport(transport)},
            },
        )

    monkeypatch.setattr(genai, "Client", factory)
    monkeypatch.setattr(GeminiClient, "_clients", {})
    try:
        with job_submission(), pytest.raises(Exception):
            await GeminiClient.generate("owned fixture", model="fixture")
        assert len(requests) == 1
        assert requests[0].url.host == "fixture.invalid"
    finally:
        await GeminiClient.close_all()
