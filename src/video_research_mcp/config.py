"""Server configuration via environment variables."""

from __future__ import annotations

import os
from ipaddress import ip_address
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator

VALID_THINKING_LEVELS = {"minimal", "low", "medium", "high"}

MODEL_PRESETS: dict[str, dict[str, str]] = {
    "best": {
        "default_model": "gemini-3.1-pro-preview",
        "flash_model": "gemini-3-flash-preview",
        "label": "Max quality — 3.1 Pro + 3 Flash (preview, lowest rate limits)",
    },
    "stable": {
        "default_model": "gemini-3-pro-preview",
        "flash_model": "gemini-3-flash-preview",
        "label": "Fallback — 3 Pro + 3 Flash (higher rate limits, 3 Pro EOL 2026-03-09)",
    },
    "budget": {
        "default_model": "gemini-3-flash-preview",
        "flash_model": "gemini-3-flash-preview",
        "label": "Cost-optimized — 3 Flash for everything (highest rate limits)",
    },
}


def _is_env_placeholder(value: str) -> bool:
    """Return True when *value* looks like an unresolved shell placeholder."""
    if value.startswith("${") and value.endswith("}"):
        inner = value[2:-1].strip()
        if ":-" in inner:
            inner = inner.split(":-", 1)[0].strip()
        return bool(inner) and all(ch.isalnum() or ch == "_" for ch in inner)
    if value.startswith("$"):
        inner = value[1:].strip()
        return bool(inner) and all(ch.isalnum() or ch == "_" for ch in inner)
    return False


def _normalize_weaviate_url(raw: str) -> str:
    """Normalize WEAVIATE_URL from env.

    Accepts bare hostnames by adding a default scheme:
    - local/private hosts -> ``http://``
    - everything else -> ``https://``

    Unresolved placeholder values (``${WEAVIATE_URL}``) are treated as unset.
    """
    value = raw.strip()
    if not value or _is_env_placeholder(value):
        return ""

    if "://" in value:
        return value

    host = (urlparse(f"//{value}").hostname or "").lower()
    if not host:
        return ""

    is_local_or_private = host == "localhost"
    if not is_local_or_private:
        try:
            ip = ip_address(host)
            is_local_or_private = ip.is_loopback or ip.is_private
        except ValueError:
            is_local_or_private = False

    scheme = "http" if is_local_or_private else "https"
    normalized = f"{scheme}://{value}"

    # Defensive: if parsing still yields no host, disable instead of crashing later.
    return normalized if urlparse(normalized).hostname else ""


def _resolve_tracing_enabled(flag_value: str, tracking_uri: str) -> bool:
    """Derive tracing_enabled from env vars.

    - ``GEMINI_TRACING_ENABLED=false`` → always disabled (explicit opt-out).
    - ``GEMINI_TRACING_ENABLED=true`` → enabled only if ``MLFLOW_TRACKING_URI`` is set.
    - Empty flag → enabled when ``MLFLOW_TRACKING_URI`` is non-empty.
    """
    if flag_value.lower() == "false":
        return False
    return bool(tracking_uri)


class ServerConfig(BaseModel):
    """Runtime configuration resolved from environment."""

    gemini_api_key: str = Field(default="")
    default_model: str = Field(default="gemini-3.1-pro-preview")
    flash_model: str = Field(default="gemini-3-flash-preview")
    default_thinking_level: str = Field(default="high")
    default_temperature: float = Field(default=1.0)
    cache_dir: str = Field(default="")
    cache_ttl_days: int = Field(default=30)
    max_sessions: int = Field(default=50)
    session_timeout_hours: int = Field(default=2)
    session_max_turns: int = Field(default=24)
    retry_max_attempts: int = Field(default=3)
    retry_base_delay: float = Field(default=1.0)
    retry_max_delay: float = Field(default=60.0)
    youtube_api_key: str = Field(default="")
    session_db_path: str = Field(default="")
    weaviate_url: str = Field(default="")
    weaviate_api_key: str = Field(default="")
    weaviate_enabled: bool = Field(default=False)
    reranker_enabled: bool = Field(default=False)
    reranker_provider: str = Field(default="cohere")
    flash_summarize: bool = Field(default=True)
    context_cache_ttl_seconds: int = Field(default=3600)
    clear_cache_on_shutdown: bool = Field(default=False)
    tracing_enabled: bool = Field(default=False)
    mlflow_tracking_uri: str = Field(default="")
    mlflow_experiment_name: str = Field(default="video-research-mcp")
    doc_max_download_bytes: int = Field(default=50 * 1024 * 1024)
    research_document_max_sources: int = Field(default=12)
    research_document_phase_concurrency: int = Field(default=4)
    local_file_access_root: str = Field(default="")
    infra_mutations_enabled: bool = Field(default=False)
    infra_admin_token: str = Field(default="")

    @field_validator("default_thinking_level")
    @classmethod
    def validate_thinking_level(cls, value: str) -> str:
        level = value.strip().lower()
        if level not in VALID_THINKING_LEVELS:
            allowed = ", ".join(sorted(VALID_THINKING_LEVELS))
            raise ValueError(f"Invalid thinking level '{value}'. Allowed: {allowed}")
        return level

    @field_validator(
        "cache_ttl_days",
        "max_sessions",
        "session_timeout_hours",
        "session_max_turns",
        "context_cache_ttl_seconds",
        "research_document_max_sources",
        "research_document_phase_concurrency",
    )
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Configuration values must be >= 1")
        return value

    @field_validator("retry_max_attempts")
    @classmethod
    def validate_retry_max_attempts(cls, value: int) -> int:
        if value < 1:
            raise ValueError("retry_max_attempts must be >= 1")
        return value

    @field_validator("retry_base_delay", "retry_max_delay")
    @classmethod
    def validate_retry_delays(cls, value: float) -> float:
        if value <= 0:
            raise ValueError("Retry delay must be > 0")
        return value

    @classmethod
    def from_env(cls) -> ServerConfig:
        """Build config from environment variables."""
        from pathlib import Path

        cache_default = str(Path.home() / ".cache" / "video-research-mcp")
        local_file_access_root = os.getenv("LOCAL_FILE_ACCESS_ROOT", "").strip()
        if local_file_access_root:
            local_file_access_root = str(Path(local_file_access_root).expanduser().resolve())
        weaviate_url = _normalize_weaviate_url(os.getenv("WEAVIATE_URL", ""))
        _cohere_key = os.environ.get("COHERE_API_KEY", "")
        _reranker_flag = os.getenv("RERANKER_ENABLED", "").lower()
        return cls(
            gemini_api_key=os.getenv("GEMINI_API_KEY", ""),
            default_model=os.getenv("GEMINI_MODEL", "gemini-3.1-pro-preview"),
            flash_model=os.getenv("GEMINI_FLASH_MODEL", "gemini-3-flash-preview"),
            default_thinking_level=os.getenv("GEMINI_THINKING_LEVEL", "high"),
            default_temperature=float(os.getenv("GEMINI_TEMPERATURE", "1.0")),
            cache_dir=os.getenv("GEMINI_CACHE_DIR", cache_default),
            cache_ttl_days=int(os.getenv("GEMINI_CACHE_TTL_DAYS", "30")),
            max_sessions=int(os.getenv("GEMINI_MAX_SESSIONS", "50")),
            session_timeout_hours=int(os.getenv("GEMINI_SESSION_TIMEOUT_HOURS", "2")),
            session_max_turns=int(os.getenv("GEMINI_SESSION_MAX_TURNS", "24")),
            retry_max_attempts=int(os.getenv("GEMINI_RETRY_MAX_ATTEMPTS", "3")),
            retry_base_delay=float(os.getenv("GEMINI_RETRY_BASE_DELAY", "1.0")),
            retry_max_delay=float(os.getenv("GEMINI_RETRY_MAX_DELAY", "60.0")),
            youtube_api_key=os.getenv("YOUTUBE_API_KEY", ""),
            session_db_path=os.getenv("GEMINI_SESSION_DB", ""),
            weaviate_url=weaviate_url,
            weaviate_api_key=os.getenv("WEAVIATE_API_KEY", ""),
            weaviate_enabled=bool(weaviate_url),
            reranker_enabled=(
                _reranker_flag == "true"
                or (bool(_cohere_key) and _reranker_flag != "false")
            ),
            reranker_provider=os.getenv("RERANKER_PROVIDER", "cohere"),
            flash_summarize=os.getenv("FLASH_SUMMARIZE", "true").lower() != "false",
            context_cache_ttl_seconds=int(os.getenv("GEMINI_CONTEXT_CACHE_TTL", "3600")),
            clear_cache_on_shutdown=os.getenv("CLEAR_CACHE_ON_SHUTDOWN", "").lower() in ("1", "true", "yes"),
            tracing_enabled=_resolve_tracing_enabled(
                os.getenv("GEMINI_TRACING_ENABLED", ""),
                os.getenv("MLFLOW_TRACKING_URI", ""),
            ),
            mlflow_tracking_uri=os.getenv("MLFLOW_TRACKING_URI", ""),
            mlflow_experiment_name=os.getenv("MLFLOW_EXPERIMENT_NAME", "video-research-mcp"),
            doc_max_download_bytes=int(os.getenv("DOC_MAX_DOWNLOAD_BYTES", str(50 * 1024 * 1024))),
            research_document_max_sources=int(os.getenv("RESEARCH_DOCUMENT_MAX_SOURCES", "12")),
            research_document_phase_concurrency=int(
                os.getenv("RESEARCH_DOCUMENT_PHASE_CONCURRENCY", "4")
            ),
            local_file_access_root=local_file_access_root,
            infra_mutations_enabled=os.getenv("INFRA_MUTATIONS_ENABLED", "").lower() in ("1", "true", "yes"),
            infra_admin_token=os.getenv("INFRA_ADMIN_TOKEN", ""),
        )


# Singleton — initialised once at import time.
_config: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Return the global config singleton, creating it on first access.

    Loads ``~/.config/video-research-mcp/.env`` before reading env vars.
    Process environment always takes precedence over the config file.
    """
    global _config
    if _config is None:
        import logging

        from .dotenv import load_dotenv

        injected = load_dotenv()
        if injected:
            logger = logging.getLogger(__name__)
            logger.info(
                "Loaded %d var(s) from config: %s",
                len(injected),
                ", ".join(injected.keys()),
            )
        _config = ServerConfig.from_env()
    return _config


def update_config(**overrides: object) -> ServerConfig:
    """Patch the live config (used by ``infra_configure`` tool)."""
    global _config
    cfg = get_config()
    data = cfg.model_dump()
    data.update({k: v for k, v in overrides.items() if v is not None})
    _config = ServerConfig(**data)
    return _config
