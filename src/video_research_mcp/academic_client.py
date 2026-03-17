"""Async HTTP client for Semantic Scholar Graph API v1.

Singleton pattern (class methods) matching GeminiClient. Uses httpx with
time-based 1 RPS rate limiting. API key is optional but recommended for
higher rate limits.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
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

# Valid paper ID formats accepted by Semantic Scholar API
_PAPER_ID_RE = re.compile(
    r"^("
    r"[0-9a-f]{40}|"                        # S2 corpus ID (SHA1 hex)
    r"DOI:10\.\d{4,}/[^\s]{1,200}|"         # DOI format
    r"ArXiv:\d{4}\.\d{4,}(v\d+)?|"          # ArXiv ID
    r"CorpusID:\d+|"                         # Corpus ID
    r"PMID:\d+|"                             # PubMed ID
    r"ACL:[A-Z]\d{2}-\d{4}"                  # ACL ID
    r")$"
)


def validate_paper_id(paper_id: str) -> str:
    """Validate paper ID format to prevent path traversal."""
    if not _PAPER_ID_RE.match(paper_id):
        raise ValueError(
            f"Invalid paper ID format: {paper_id!r}. "
            "Use S2 ID (hex), DOI:10.xxx/yyy, ArXiv:YYMM.NNNNN, "
            "CorpusID:N, PMID:N, or ACL:X00-0000"
        )
    return paper_id


class _RateLimiter:
    """Time-based rate limiter enforcing minimum interval between requests."""

    def __init__(self, min_interval: float = 1.0):
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last_request = 0.0

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            wait = self._min_interval - (now - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = time.monotonic()


class SemanticScholarClient:
    """Process-wide Semantic Scholar API client (singleton)."""

    _client: Any | None = None  # httpx.AsyncClient
    _limiter: _RateLimiter | None = None

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
            cls._limiter = _RateLimiter(min_interval=1.0)
            logger.info("Created Semantic Scholar client (key %s)", "set" if cfg.s2_api_key else "unset")
        return cls._client

    @classmethod
    async def _request(cls, method: str, path: str, **kwargs: Any) -> dict:
        """Rate-limited HTTP request with retry on 429/503/timeout."""
        client = cls._get_client()
        limiter = cls._limiter  # always set by _get_client()

        async def _do_request() -> dict:
            await limiter.acquire()
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
        validate_paper_id(paper_id)
        return await cls._request(
            "GET",
            f"/graph/v1/paper/{paper_id}",
            params={"fields": _DEFAULT_PAPER_FIELDS},
        )

    @classmethod
    async def get_references(cls, paper_id: str, limit: int = 20) -> dict:
        """Get paper references via /graph/v1/paper/{paper_id}/references."""
        validate_paper_id(paper_id)
        return await cls._request(
            "GET",
            f"/graph/v1/paper/{paper_id}/references",
            params={"fields": _DEFAULT_PAPER_FIELDS, "limit": min(limit, 1000)},
        )

    @classmethod
    async def get_citations(cls, paper_id: str, limit: int = 20) -> dict:
        """Get paper citations via /graph/v1/paper/{paper_id}/citations."""
        validate_paper_id(paper_id)
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
