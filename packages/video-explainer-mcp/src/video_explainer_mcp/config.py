"""Server configuration via environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class ServerConfig(BaseModel):
    """Runtime configuration resolved from environment.

    Fields with empty-string defaults are optional services.
    ``explainer_enabled`` is derived — True when ``explainer_path`` points
    to a valid directory (checked at tool-call time, not at startup).
    """

    explainer_path: str = Field(default="")
    projects_path: str = Field(default="")
    tts_provider: str = Field(default="mock")
    timeout: int = Field(default=600)
    render_timeout: int = Field(default=1800)
    explainer_python: str = Field(default="python3")
    elevenlabs_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")

    @field_validator("timeout", "render_timeout")
    @classmethod
    def validate_positive_ints(cls, value: int) -> int:
        if value < 1:
            raise ValueError("Timeout values must be >= 1")
        return value

    @field_validator("tts_provider")
    @classmethod
    def validate_tts_provider(cls, value: str) -> str:
        allowed = {"mock", "elevenlabs", "edge"}
        v = value.strip().lower()
        if v not in allowed:
            raise ValueError(f"Invalid TTS provider '{value}'. Allowed: {', '.join(sorted(allowed))}")
        return v

    @property
    def explainer_enabled(self) -> bool:
        """True when explainer_path is set (directory check deferred to tool call)."""
        return bool(self.explainer_path)

    @property
    def resolved_projects_path(self) -> Path:
        """Return the projects directory, defaulting to explainer_path/projects."""
        if self.projects_path:
            return Path(self.projects_path).expanduser().resolve()
        if self.explainer_path:
            return Path(self.explainer_path).expanduser().resolve() / "projects"
        return Path.cwd() / "projects"

    @classmethod
    def from_env(cls) -> ServerConfig:
        """Build config from environment variables."""

        def _int(key: str, default: int) -> int:
            try:
                return int(os.getenv(key, str(default)))
            except (ValueError, TypeError):
                return default

        # Auto-detect explainer path: env var → sibling submodule → empty
        explainer_path = os.getenv("EXPLAINER_PATH", "")
        if not explainer_path:
            submodule = Path(__file__).resolve().parents[3] / "video-explainer"
            if (submodule / "pyproject.toml").is_file():
                explainer_path = str(submodule)

        return cls(
            explainer_path=explainer_path,
            projects_path=os.getenv("EXPLAINER_PROJECTS_PATH", ""),
            tts_provider=os.getenv("EXPLAINER_TTS_PROVIDER", "mock"),
            timeout=_int("EXPLAINER_TIMEOUT", 600),
            render_timeout=_int("EXPLAINER_RENDER_TIMEOUT", 1800),
            explainer_python=os.getenv("EXPLAINER_PYTHON", "python3"),
            elevenlabs_api_key=os.getenv("ELEVENLABS_API_KEY", ""),
            openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        )


# Singleton — initialised once on first access.
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
    """Patch the live config."""
    global _config
    cfg = get_config()
    data = cfg.model_dump()
    data.update({k: v for k, v in overrides.items() if v is not None})
    _config = ServerConfig(**data)
    return _config
