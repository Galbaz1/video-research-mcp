"""Tests for the optional MLflow tracing integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch


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
