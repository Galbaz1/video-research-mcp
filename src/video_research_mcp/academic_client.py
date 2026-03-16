"""Async HTTP client for Semantic Scholar Graph API v1.

Singleton pattern (class methods) matching GeminiClient. Uses httpx with
1 RPS rate limiting via asyncio.Semaphore. API key is optional but
recommended for higher rate limits.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .config import get_config
from .retry import with_retry

logger = logging.getLogger(__name__)

_DEFAULT_PAPER_FIELDS = (
    "paperId,title,abstract,year,venue,citationCount,referenceCount,"
    "fieldsOfStudy,authors,isOpenAccess,openAccessPdf,externalIds,tldr"
)

_DEFAULT_AUTHOR_FIELDS = (
    "authorId,name,affiliations,paperCount,citationCount,hIndex"
)


class SemanticScholarClient:
    """Process-wide Semantic Scholar API client (singleton)."""

    _client: Any | None = None  # httpx.AsyncClient
    _semaphore: asyncio.Semaphore | None = None

    @classmethod
    def _get_client(cls) -> Any:
        """Return (or create) the shared httpx.AsyncClient."""
        import httpx  # lazy import

        if cls._client is None or cls._client.is_closed:
            cfg = get_config()
            headers: dict[str, str] = {}
            if cfg.s2_api_key:
                headers["x-api-key"] = cfg.s2_api_key
            cls._client = httpx.AsyncClient(
                base_url="https://api.semanticscholar.org",
                headers=headers,
                timeout=30.0,
            )
            cls._semaphore = asyncio.Semaphore(1)
            logger.info("Created Semantic Scholar client (key %s)", "set" if cfg.s2_api_key else "unset")
        return cls._client

    @classmethod
    def _get_semaphore(cls) -> asyncio.Semaphore:
        if cls._semaphore is None:
            cls._semaphore = asyncio.Semaphore(1)
        return cls._semaphore

    @classmethod
    async def _request(cls, method: str, path: str, **kwargs: Any) -> dict:
        """Rate-limited HTTP request with retry on 429/503/timeout."""
        client = cls._get_client()
        sem = cls._get_semaphore()

        async def _do_request() -> dict:
            async with sem:
                resp = await client.request(method, path, **kwargs)
                resp.raise_for_status()
                return resp.json()

        return await with_retry(_do_request)

    @classmethod
    async def search_papers(
        cls,
        query: str,
        limit: int = 10,
        fields_of_study: list[str] | None = None,
        year: str | None = None,
        open_access_only: bool = False,
    ) -> dict:
        """Search papers via /graph/v1/paper/search."""
        params: dict[str, Any] = {
            "query": query,
            "limit": min(limit, 100),
            "fields": _DEFAULT_PAPER_FIELDS,
        }
        if fields_of_study:
            params["fieldsOfStudy"] = ",".join(fields_of_study)
        if year:
            params["year"] = year
        if open_access_only:
            params["openAccessPdf"] = ""
        return await cls._request("GET", "/graph/v1/paper/search", params=params)

    @classmethod
    async def get_paper(cls, paper_id: str) -> dict:
        """Get paper details via /graph/v1/paper/{paper_id}."""
        return await cls._request(
            "GET",
            f"/graph/v1/paper/{paper_id}",
            params={"fields": _DEFAULT_PAPER_FIELDS},
        )

    @classmethod
    async def get_references(cls, paper_id: str, limit: int = 20) -> dict:
        """Get paper references via /graph/v1/paper/{paper_id}/references."""
        return await cls._request(
            "GET",
            f"/graph/v1/paper/{paper_id}/references",
            params={"fields": _DEFAULT_PAPER_FIELDS, "limit": min(limit, 1000)},
        )

    @classmethod
    async def get_citations(cls, paper_id: str, limit: int = 20) -> dict:
        """Get paper citations via /graph/v1/paper/{paper_id}/citations."""
        return await cls._request(
            "GET",
            f"/graph/v1/paper/{paper_id}/citations",
            params={"fields": _DEFAULT_PAPER_FIELDS, "limit": min(limit, 1000)},
        )

    @classmethod
    async def get_recommendations(cls, seed_paper_ids: list[str], limit: int = 10) -> dict:
        """Get recommendations via /recommendations/v1/papers."""
        return await cls._request(
            "POST",
            "/recommendations/v1/papers/",
            json={"positivePaperIds": seed_paper_ids},
            params={"fields": _DEFAULT_PAPER_FIELDS, "limit": min(limit, 500)},
        )

    @classmethod
    async def search_authors(cls, query: str, limit: int = 5) -> dict:
        """Search authors via /graph/v1/author/search."""
        return await cls._request(
            "GET",
            "/graph/v1/author/search",
            params={"query": query, "limit": min(limit, 100), "fields": _DEFAULT_AUTHOR_FIELDS},
        )

    @classmethod
    async def close(cls) -> None:
        """Close the shared httpx client."""
        if cls._client is not None and not cls._client.is_closed:
            await cls._client.aclose()
            logger.info("Closed Semantic Scholar client")
        cls._client = None
        cls._semaphore = None
