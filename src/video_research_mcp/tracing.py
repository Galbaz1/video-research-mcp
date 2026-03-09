"""Optional MLflow tracing integration.

Provides two instrumentation layers:

1. **Autolog** — ``mlflow.gemini.autolog()`` patches the google-genai SDK to
   capture every ``generate_content`` call as a ``CHAT_MODEL`` span.
2. **Tool spans** — the ``trace()`` decorator wraps MCP tool entrypoints,
   producing ``TOOL`` root spans that parent the autolog child spans.

Guarded import — the server runs fine without ``mlflow-tracing`` installed.
Configuration is read from :class:`~video_research_mcp.config.ServerConfig`.

Env vars (all optional):
    MLFLOW_TRACKING_URI: Where to store traces. Empty = tracing disabled.
    MLFLOW_EXPERIMENT_NAME: Experiment name (default ``video-research-mcp``).
    GEMINI_TRACING_ENABLED: Set to ``"false"`` to force-disable even with a URI.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

try:
    import mlflow
    import mlflow.gemini

    _HAS_MLFLOW = True
except ImportError:
    _HAS_MLFLOW = False


def is_enabled() -> bool:
    """Return True when mlflow-tracing is installed and not explicitly disabled."""
    if not _HAS_MLFLOW:
        return False
    from .config import get_config

    return get_config().tracing_enabled


def trace(
    func: Callable | None = None,
    *,
    name: str | None = None,
    span_type: str | None = None,
    attributes: dict[str, Any] | None = None,
) -> Callable:
    """Drop-in replacement for ``@mlflow.trace`` — identity when tracing is off.

    Usage::

        @trace(name="video_analyze", span_type="TOOL")
        async def video_analyze(...): ...
    """
    if not is_enabled():
        return func if func is not None else (lambda f: f)
    return mlflow.trace(func, name=name, span_type=span_type, attributes=attributes)


def _tracking_server_reachable(uri: str, timeout: float = 2.0) -> bool:
    """Fast check whether the MLflow tracking server accepts connections."""
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(uri)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def setup() -> None:
    """Configure MLflow tracking and enable Gemini autologging.

    No-op when ``is_enabled()`` returns False. Skips setup when the
    tracking server is unreachable (2 s probe) to prevent blocking the
    MCP server startup. Failures are logged and swallowed — tracing must
    never prevent the server from starting.
    """
    if not is_enabled():
        return

    from .config import get_config

    cfg = get_config()
    tracking_uri = cfg.mlflow_tracking_uri
    experiment = cfg.mlflow_experiment_name

    if not _tracking_server_reachable(tracking_uri):
        logger.warning(
            "MLflow tracking server unreachable (%s) — tracing disabled",
            tracking_uri,
        )
        return

    try:
        mlflow.set_tracking_uri(tracking_uri)
        mlflow.set_experiment(experiment)
        mlflow.gemini.autolog()
        logger.info("MLflow tracing enabled (uri=%s, experiment=%s)", tracking_uri, experiment)
    except Exception:
        logger.warning("MLflow tracing setup failed — continuing without tracing", exc_info=True)


def shutdown() -> None:
    """Flush pending async traces.

    No-op when ``is_enabled()`` returns False.
    """
    if not is_enabled():
        return

    try:
        mlflow.flush_trace_async_logging()
        logger.info("MLflow traces flushed")
    except Exception:
        logger.warning("MLflow trace flush failed", exc_info=True)
