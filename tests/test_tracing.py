"""Tests for the optional MLflow tracing integration."""

from __future__ import annotations

import builtins
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(**overrides):
    """Build a mock ServerConfig with tracing-enabled defaults."""
    defaults = {
        "tracing_enabled": True,
        "mlflow_tracking_uri": "http://127.0.0.1:5001",
        "mlflow_experiment_name": "video-research-mcp",
    }
    defaults.update(overrides)
    cfg = MagicMock()
    for k, v in defaults.items():
        setattr(cfg, k, v)
    return cfg


def _fresh_tracing():
    """Load the tracing source into a fresh module without the import cache."""
    path = Path(__file__).parents[1] / "src/video_research_mcp/tracing.py"
    spec = importlib.util.spec_from_file_location("video_research_mcp._fresh_tracing", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("flag,uri", [("false", "http://127.0.0.1:5001"), ("", "")])
def test_fresh_disabled_lifecycle_never_imports_mlflow(flag, uri, monkeypatch, clean_config):
    """GIVEN disabled config WHEN freshly loaded and used THEN MLflow is never imported."""
    monkeypatch.setenv("GEMINI_TRACING_ENABLED", flag)
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    original_import = builtins.__import__

    def reject_mlflow(name, *args, **kwargs):
        if name == "mlflow" or name.startswith("mlflow."):
            raise AssertionError(f"disabled tracing attempted import: {name}")
        return original_import(name, *args, **kwargs)

    async def tool():
        return "unchanged"

    with patch("builtins.__import__", side_effect=reject_mlflow):
        mod = _fresh_tracing()
        assert mod.is_enabled() is False
        assert mod.trace(tool) is tool
        assert mod.trace(name="tool", span_type="TOOL")(tool) is tool
        mod.setup()
        mod.shutdown()


def test_enabled_lazy_import_preserves_lifecycle(monkeypatch):
    """GIVEN enabled config WHEN tracing is used THEN import once and preserve SDK calls."""
    original_import = builtins.__import__
    mlflow = MagicMock()
    imports = []

    def import_mlflow(name, *args, **kwargs):
        if name == "mlflow" or name.startswith("mlflow."):
            imports.append(name)
            return mlflow
        return original_import(name, *args, **kwargs)

    async def tool():
        return "unchanged"

    with (
        patch("builtins.__import__", side_effect=import_mlflow),
        patch("video_research_mcp.config.get_config", return_value=_make_config()),
    ):
        mod = _fresh_tracing()
        assert imports == []
        assert mod.trace(tool) is mlflow.trace.return_value
        mlflow.trace.assert_called_once_with(tool, name=None, span_type=None, attributes=None)
        mlflow.trace.reset_mock()
        attributes = {"operation": "test"}
        assert mod.trace(name="tool", span_type="TOOL", attributes=attributes) is mlflow.trace.return_value
        mlflow.trace.assert_called_once_with(None, name="tool", span_type="TOOL", attributes=attributes)
        monkeypatch.setattr(mod, "_tracking_server_reachable", lambda uri: True)
        mod.setup()
        mod.shutdown()
        assert mod.is_enabled() is True

    assert imports == ["mlflow", "mlflow.gemini"]
    mlflow.set_tracking_uri.assert_called_once_with("http://127.0.0.1:5001")
    mlflow.set_experiment.assert_called_once_with("video-research-mcp")
    mlflow.gemini.autolog.assert_called_once()
    mlflow.flush_trace_async_logging.assert_called_once()


@pytest.mark.parametrize("missing", ["mlflow", "mlflow.gemini"])
def test_enabled_missing_sdk_keeps_identity(missing):
    """GIVEN either optional import missing WHEN enabled THEN the lifecycle stays inert."""
    original_import = builtins.__import__
    mlflow = MagicMock()
    imports = []

    def import_mlflow(name, *args, **kwargs):
        if name == "mlflow" or name.startswith("mlflow."):
            imports.append(name)
            if name == missing:
                raise ImportError("optional SDK unavailable")
            return mlflow
        return original_import(name, *args, **kwargs)

    def tool():
        return "unchanged"

    with (
        patch("builtins.__import__", side_effect=import_mlflow),
        patch("video_research_mcp.config.get_config", return_value=_make_config()),
    ):
        mod = _fresh_tracing()
        assert imports == []
        assert mod.is_enabled() is False
        assert mod.trace(tool) is tool
        assert mod.trace(name="tool")(tool) is tool
        mod.setup()
        mod.shutdown()

    assert imports == (["mlflow"] if missing == "mlflow" else ["mlflow", "mlflow.gemini"])
    assert mlflow.mock_calls == []


# ---------------------------------------------------------------------------
# is_enabled()
# ---------------------------------------------------------------------------


class TestIsEnabled:
    """``tracing.is_enabled()`` respects import availability and config."""

    def test_true_when_installed_and_enabled(self):
        """GIVEN mlflow importable and config.tracing_enabled=True THEN True."""
        import video_research_mcp.tracing as mod

        original = mod._HAS_MLFLOW
        try:
            mod._HAS_MLFLOW = True
            with patch("video_research_mcp.config.get_config", return_value=_make_config()):
                assert mod.is_enabled() is True
        finally:
            mod._HAS_MLFLOW = original

    def test_false_when_not_installed(self):
        """GIVEN mlflow is not importable THEN returns False."""
        import video_research_mcp.tracing as mod

        original = mod._HAS_MLFLOW
        try:
            mod._HAS_MLFLOW = False
            with patch("video_research_mcp.config.get_config", return_value=_make_config()):
                assert mod.is_enabled() is False
        finally:
            mod._HAS_MLFLOW = original

    def test_false_when_config_disabled(self):
        """GIVEN config.tracing_enabled=False THEN returns False."""
        import video_research_mcp.tracing as mod

        original = mod._HAS_MLFLOW
        try:
            mod._HAS_MLFLOW = True
            cfg = _make_config(tracing_enabled=False)
            with patch("video_research_mcp.config.get_config", return_value=cfg):
                assert mod.is_enabled() is False
        finally:
            mod._HAS_MLFLOW = original


# ---------------------------------------------------------------------------
# setup()
# ---------------------------------------------------------------------------


class TestSetup:
    """``tracing.setup()`` configures MLflow when enabled."""

    def test_calls_autolog(self):
        """GIVEN tracing enabled THEN calls set_tracking_uri, set_experiment, autolog."""
        mock_mlflow = MagicMock()
        mock_gemini = MagicMock()

        import video_research_mcp.tracing as mod

        original_has = mod._HAS_MLFLOW
        original_mlflow = getattr(mod, "mlflow", None)
        try:
            mod._HAS_MLFLOW = True
            mod.mlflow = mock_mlflow
            mod.mlflow.gemini = mock_gemini

            cfg = _make_config()
            with (
                patch("video_research_mcp.config.get_config", return_value=cfg),
                patch.object(mod, "_tracking_server_reachable", return_value=True),
            ):
                mod.setup()

            mock_mlflow.set_tracking_uri.assert_called_once_with("http://127.0.0.1:5001")
            mock_mlflow.set_experiment.assert_called_once_with("video-research-mcp")
            mock_gemini.autolog.assert_called_once()
        finally:
            mod._HAS_MLFLOW = original_has
            if original_mlflow is not None:
                mod.mlflow = original_mlflow

    def test_noop_when_disabled(self):
        """GIVEN tracing disabled THEN nothing is called."""
        mock_mlflow = MagicMock()

        import video_research_mcp.tracing as mod

        original_has = mod._HAS_MLFLOW
        original_mlflow = getattr(mod, "mlflow", None)
        try:
            mod._HAS_MLFLOW = False
            mod.mlflow = mock_mlflow

            mod.setup()

            mock_mlflow.set_tracking_uri.assert_not_called()
            mock_mlflow.set_experiment.assert_not_called()
        finally:
            mod._HAS_MLFLOW = original_has
            if original_mlflow is not None:
                mod.mlflow = original_mlflow

    def test_setup_swallows_exceptions(self):
        """GIVEN set_experiment raises THEN setup logs warning and does not propagate."""
        mock_mlflow = MagicMock()
        mock_mlflow.set_experiment.side_effect = Exception("connection refused")
        mock_gemini = MagicMock()

        import video_research_mcp.tracing as mod

        original_has = mod._HAS_MLFLOW
        original_mlflow = getattr(mod, "mlflow", None)
        try:
            mod._HAS_MLFLOW = True
            mod.mlflow = mock_mlflow
            mod.mlflow.gemini = mock_gemini

            cfg = _make_config()
            with (
                patch("video_research_mcp.config.get_config", return_value=cfg),
                patch.object(mod, "_tracking_server_reachable", return_value=True),
            ):
                mod.setup()  # should not raise

            mock_gemini.autolog.assert_not_called()  # never reached
        finally:
            mod._HAS_MLFLOW = original_has
            if original_mlflow is not None:
                mod.mlflow = original_mlflow

    def test_setup_skips_when_server_unreachable(self):
        """GIVEN tracking server unreachable THEN setup returns early, no MLflow calls."""
        mock_mlflow = MagicMock()
        mock_gemini = MagicMock()

        import video_research_mcp.tracing as mod

        original_has = mod._HAS_MLFLOW
        original_mlflow = getattr(mod, "mlflow", None)
        try:
            mod._HAS_MLFLOW = True
            mod.mlflow = mock_mlflow
            mod.mlflow.gemini = mock_gemini

            cfg = _make_config()
            with (
                patch("video_research_mcp.config.get_config", return_value=cfg),
                patch.object(mod, "_tracking_server_reachable", return_value=False),
            ):
                mod.setup()

            mock_mlflow.set_tracking_uri.assert_not_called()
            mock_mlflow.set_experiment.assert_not_called()
            mock_gemini.autolog.assert_not_called()
        finally:
            mod._HAS_MLFLOW = original_has
            if original_mlflow is not None:
                mod.mlflow = original_mlflow

    def test_custom_uri_and_experiment(self):
        """GIVEN custom config values THEN passes them to MLflow."""
        mock_mlflow = MagicMock()
        mock_gemini = MagicMock()

        import video_research_mcp.tracing as mod

        original_has = mod._HAS_MLFLOW
        original_mlflow = getattr(mod, "mlflow", None)
        try:
            mod._HAS_MLFLOW = True
            mod.mlflow = mock_mlflow
            mod.mlflow.gemini = mock_gemini

            cfg = _make_config(
                mlflow_tracking_uri="http://my-server:5000",
                mlflow_experiment_name="custom-experiment",
            )
            with (
                patch("video_research_mcp.config.get_config", return_value=cfg),
                patch.object(mod, "_tracking_server_reachable", return_value=True),
            ):
                mod.setup()

            mock_mlflow.set_tracking_uri.assert_called_once_with("http://my-server:5000")
            mock_mlflow.set_experiment.assert_called_once_with("custom-experiment")
        finally:
            mod._HAS_MLFLOW = original_has
            if original_mlflow is not None:
                mod.mlflow = original_mlflow


# ---------------------------------------------------------------------------
# shutdown()
# ---------------------------------------------------------------------------


class TestShutdown:
    """``tracing.shutdown()`` flushes async traces."""

    def test_flushes(self):
        """GIVEN tracing enabled THEN calls flush_trace_async_logging."""
        mock_mlflow = MagicMock()

        import video_research_mcp.tracing as mod

        original_has = mod._HAS_MLFLOW
        original_mlflow = getattr(mod, "mlflow", None)
        try:
            mod._HAS_MLFLOW = True
            mod.mlflow = mock_mlflow

            cfg = _make_config()
            with patch("video_research_mcp.config.get_config", return_value=cfg):
                mod.shutdown()

            mock_mlflow.flush_trace_async_logging.assert_called_once()
        finally:
            mod._HAS_MLFLOW = original_has
            if original_mlflow is not None:
                mod.mlflow = original_mlflow

    def test_noop_when_disabled(self):
        """GIVEN tracing disabled THEN nothing is called."""
        mock_mlflow = MagicMock()

        import video_research_mcp.tracing as mod

        original_has = mod._HAS_MLFLOW
        original_mlflow = getattr(mod, "mlflow", None)
        try:
            mod._HAS_MLFLOW = False
            mod.mlflow = mock_mlflow

            mod.shutdown()

            mock_mlflow.flush_trace_async_logging.assert_not_called()
        finally:
            mod._HAS_MLFLOW = original_has
            if original_mlflow is not None:
                mod.mlflow = original_mlflow


# ---------------------------------------------------------------------------
# _resolve_tracing_enabled()
# ---------------------------------------------------------------------------


class TestResolveTracingEnabled:
    """``_resolve_tracing_enabled()`` derives tracing state from env vars."""

    def test_enabled_when_uri_set(self):
        """GIVEN tracking URI is set THEN tracing is enabled."""
        from video_research_mcp.config import _resolve_tracing_enabled

        assert _resolve_tracing_enabled("", "http://127.0.0.1:5001") is True

    def test_disabled_when_uri_empty(self):
        """GIVEN tracking URI is empty THEN tracing is disabled."""
        from video_research_mcp.config import _resolve_tracing_enabled

        assert _resolve_tracing_enabled("", "") is False

    def test_disabled_when_flag_false(self):
        """GIVEN explicit false flag THEN disabled regardless of URI."""
        from video_research_mcp.config import _resolve_tracing_enabled

        assert _resolve_tracing_enabled("false", "http://127.0.0.1:5001") is False

    def test_disabled_when_flag_false_case_insensitive(self):
        """GIVEN 'False' (capitalized) THEN disabled."""
        from video_research_mcp.config import _resolve_tracing_enabled

        assert _resolve_tracing_enabled("False", "http://127.0.0.1:5001") is False

    def test_enabled_when_flag_true_and_uri_set(self):
        """GIVEN explicit true flag + URI THEN enabled."""
        from video_research_mcp.config import _resolve_tracing_enabled

        assert _resolve_tracing_enabled("true", "http://127.0.0.1:5001") is True

    def test_disabled_when_flag_true_but_no_uri(self):
        """GIVEN explicit true flag but no URI THEN disabled."""
        from video_research_mcp.config import _resolve_tracing_enabled

        assert _resolve_tracing_enabled("true", "") is False


@pytest.mark.parametrize("reachable", [False, True])
def test_diagnostic_redaction_endpoint(reachable, monkeypatch, caplog):
    """GIVEN credential URL WHEN setup logs THEN clients keep raw bytes and logs redact."""
    import video_research_mcp.tracing as mod

    uri = "https://url-user-canary:url-password-canary@tracking.example/run?token=url-query-canary#url-fragment-canary"
    mlflow = MagicMock()
    monkeypatch.setattr(mod, "mlflow", mlflow, raising=False)
    monkeypatch.setattr(mod, "is_enabled", lambda: True)
    caplog.set_level("INFO", logger=mod.__name__)
    with (
        patch("video_research_mcp.config.get_config", return_value=_make_config(mlflow_tracking_uri=uri)),
        patch.object(mod, "_tracking_server_reachable", return_value=reachable) as probe,
    ):
        mod.setup()
    probe.assert_called_once_with(uri)
    if reachable:
        mlflow.set_tracking_uri.assert_called_once_with(uri)
    else:
        mlflow.set_tracking_uri.assert_not_called()
    assert "tracking.example/run" in caplog.text
    for canary in ("url-user-canary", "url-password-canary", "url-query-canary", "url-fragment-canary"):
        assert canary not in caplog.text


@pytest.mark.parametrize("operation", ["setup", "shutdown"])
def test_diagnostic_redaction_errors(operation, monkeypatch, caplog):
    """GIVEN credential error WHEN setup/flush fails THEN warning retains sanitized cause."""
    import video_research_mcp.tracing as mod

    mlflow = MagicMock()
    error = RuntimeError("backend rejected https://error-user-canary:error-password-canary@tracking.example/?token=error-query-canary#error-fragment-canary password=error-field-canary")
    mlflow.set_experiment.side_effect = error
    mlflow.flush_trace_async_logging.side_effect = error
    monkeypatch.setattr(mod, "mlflow", mlflow, raising=False)
    monkeypatch.setattr(mod, "is_enabled", lambda: True)
    with (
        patch("video_research_mcp.config.get_config", return_value=_make_config()),
        patch.object(mod, "_tracking_server_reachable", return_value=True),
    ):
        getattr(mod, operation)()
    assert "backend rejected" in caplog.text
    assert "tracking.example" in caplog.text
    assert "[redacted]" in caplog.text
    for canary in ("error-user-canary", "error-password-canary", "error-query-canary", "error-fragment-canary", "error-field-canary"):
        assert canary not in caplog.text
