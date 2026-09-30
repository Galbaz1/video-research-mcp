"""Server configuration via environment variables."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from pydantic import BaseModel, Field, field_validator


class ServerConfig(BaseModel):
    """Runtime configuration resolved from environment."""

    explainer_path: str = Field(
        default="",
        description="Root directory of the upstream video_explainer checkout",
    )
    projects_path: str = Field(default="", description="Override the explainer projects directory")
    agent_model: str = Field(
        default="claude-sonnet-5-5",
        description="Claude model for agent queries",
    )
    agent_concurrency: int = Field(
        default=5,
        description="Max parallel agent queries",
    )
    agent_timeout: int = Field(
        default=300,
        description="Per-query timeout in seconds",
    )
    agent_max_turns: int = Field(
        default=1,
        ge=1,
        description="Max turns per agent query (tools are disabled)",
    )

    @field_validator("agent_concurrency")
    @classmethod
    def validate_concurrency(cls, value: int) -> int:
        if value < 1:
            raise ValueError("agent_concurrency must be >= 1")
        return min(value, 10)  # cap at 10 to avoid rate limits

    @field_validator("agent_timeout")
    @classmethod
    def validate_timeout(cls, value: int) -> int:
        if value < 30:
            raise ValueError("agent_timeout must be >= 30")
        return value

    @classmethod
    def from_env(cls) -> ServerConfig:
        """Build config from environment variables."""
        return cls(
            explainer_path=os.getenv("EXPLAINER_PATH", ""),
            projects_path=os.getenv("EXPLAINER_PROJECTS_PATH", ""),
            agent_model=os.getenv("AGENT_MODEL", "claude-sonnet-5-5"),
            agent_concurrency=int(os.getenv("AGENT_CONCURRENCY", "5")),
            agent_timeout=int(os.getenv("AGENT_TIMEOUT", "300")),
            agent_max_turns=int(os.getenv("AGENT_MAX_TURNS", "1")),
        )

    def get_project_dir(self, project_id: str) -> Path:
        """Resolve a project_id to its directory path.

        Args:
            project_id: Project directory name.

        Returns:
            Absolute path to the project directory.

        Raises:
            FileNotFoundError: If EXPLAINER_PATH is unset or project doesn't exist.
        """
        if not self.explainer_path and not self.projects_path:
            raise FileNotFoundError(
                "Set EXPLAINER_PATH to the upstream checkout or EXPLAINER_PROJECTS_PATH to its projects"
            )
        if not project_id.strip():
            raise FileNotFoundError("Project not found: project_id cannot be empty")

        explainer_root = (
            Path(self.projects_path) if self.projects_path else Path(self.explainer_path) / "projects"
        ).expanduser().resolve()
        project_dir = (explainer_root / project_id).resolve()
        try:
            project_dir.relative_to(explainer_root)
        except ValueError as exc:
            raise FileNotFoundError(
                f"Project not found: {project_id} (must be under {explainer_root})"
            ) from exc

        if not project_dir.is_dir():
            raise FileNotFoundError(f"Project not found: {project_dir}")
        return project_dir


# Singleton
_config: ServerConfig | None = None


def get_config() -> ServerConfig:
    """Return the global config singleton, creating it on first access."""
    global _config
    if _config is None:
        from .dotenv import load_dotenv

        injected = load_dotenv()
        if injected:
            logger = logging.getLogger(__name__)
            logger.info("Loaded %d var(s) from config: %s", len(injected), ", ".join(injected))
        _config = ServerConfig.from_env()
    return _config


def reset_config() -> None:
    """Reset the config singleton (for testing)."""
    global _config
    _config = None
