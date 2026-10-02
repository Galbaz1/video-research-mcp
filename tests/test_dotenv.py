"""Tests for the dotenv auto-loader."""

from __future__ import annotations

from video_research_mcp.dotenv import load_dotenv, parse_dotenv


# ---------------------------------------------------------------------------
# parse_dotenv
# ---------------------------------------------------------------------------


class TestParseDotenv:
    """Unit tests for the .env file parser."""

    def test_basic_key_value(self, tmp_path):
        """GIVEN a simple KEY=VALUE line THEN it is parsed correctly."""
        env = tmp_path / ".env"
        env.write_text("FOO=bar\n")
        assert parse_dotenv(env) == {"FOO": "bar"}

    def test_double_quoted_value(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text('DB_URL="postgres://localhost/db"\n')
        assert parse_dotenv(env) == {"DB_URL": "postgres://localhost/db"}

    def test_single_quoted_value(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("SECRET='s3cr3t'\n")
        assert parse_dotenv(env) == {"SECRET": "s3cr3t"}

    def test_comments_and_blanks(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("# comment\n\nKEY=val\n  # indented comment\n")
        assert parse_dotenv(env) == {"KEY": "val"}

    def test_missing_file(self, tmp_path):
        assert parse_dotenv(tmp_path / "nonexistent") == {}

    def test_malformed_lines_skipped(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("NO_EQUALS\nGOOD=yes\n")
        assert parse_dotenv(env) == {"GOOD": "yes"}

    def test_empty_value(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("EMPTY=\n")
        assert parse_dotenv(env) == {"EMPTY": ""}

    def test_value_with_equals(self, tmp_path):
        """GIVEN a value containing '=' THEN only the first '=' splits."""
        env = tmp_path / ".env"
        env.write_text("URL=https://host?a=1&b=2\n")
        assert parse_dotenv(env) == {"URL": "https://host?a=1&b=2"}

    def test_export_prefix(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("export API_KEY=abc123\n")
        assert parse_dotenv(env) == {"API_KEY": "abc123"}

    def test_spaces_around_key_value(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("  KEY  =  value  \n")
        assert parse_dotenv(env) == {"KEY": "value"}

    def test_multiple_entries(self, tmp_path):
        env = tmp_path / ".env"
        env.write_text("A=1\nB=2\nC=3\n")
        result = parse_dotenv(env)
        assert result == {"A": "1", "B": "2", "C": "3"}


# ---------------------------------------------------------------------------
# load_dotenv
# ---------------------------------------------------------------------------


class TestLoadDotenv:
    """Unit tests for env injection."""

    def test_selected_project_file_does_not_read_home_credentials(self, tmp_path, monkeypatch):
        """A local registration selects its own file without user-file fallback."""
        home = tmp_path / "home.env"
        home.write_text("_TEST_SCOPE=home\n")
        project = tmp_path / "project.env"
        project.write_text("_TEST_SCOPE=project\n")
        monkeypatch.setattr("video_research_mcp.dotenv.DEFAULT_ENV_PATH", home)
        monkeypatch.setenv("VIDEO_RESEARCH_ENV_FILE", str(project))
        monkeypatch.delenv("_TEST_SCOPE", raising=False)
        assert load_dotenv() == {"_TEST_SCOPE": "project"}
        monkeypatch.delenv("_TEST_SCOPE")
        project.unlink()
        assert load_dotenv() == {}

    def test_explicit_file_precedes_installer_selection(self, tmp_path, monkeypatch):
        """The existing explicit-path API remains authoritative."""
        selected = tmp_path / "selected.env"
        selected.write_text("_TEST_SCOPE=selected\n")
        explicit = tmp_path / "explicit.env"
        explicit.write_text("_TEST_SCOPE=explicit\n")
        monkeypatch.setenv("VIDEO_RESEARCH_ENV_FILE", str(selected))
        monkeypatch.delenv("_TEST_SCOPE", raising=False)
        assert load_dotenv(explicit) == {"_TEST_SCOPE": "explicit"}

    def test_injects_into_environ(self, tmp_path, monkeypatch):
        """GIVEN a .env file WHEN load_dotenv THEN vars appear in os.environ."""
        monkeypatch.delenv("_TEST_DOTENV_VAR", raising=False)
        env = tmp_path / ".env"
        env.write_text("_TEST_DOTENV_VAR=hello\n")

        injected = load_dotenv(env)

        import os

        assert os.environ["_TEST_DOTENV_VAR"] == "hello"
        assert injected == {"_TEST_DOTENV_VAR": "hello"}

    def test_does_not_override_existing(self, tmp_path, monkeypatch):
        """GIVEN a non-empty env var WHEN load_dotenv THEN the existing value wins."""
        monkeypatch.setenv("_TEST_EXISTING", "original")
        env = tmp_path / ".env"
        env.write_text("_TEST_EXISTING=overridden\n")

        injected = load_dotenv(env)

        import os

        assert os.environ["_TEST_EXISTING"] == "original"
        assert injected == {}

    def test_overrides_empty_string(self, tmp_path, monkeypatch):
        """GIVEN an empty-string env var WHEN load_dotenv THEN the config file value wins.

        MCP hosts like Claude Code resolve ${VAR} to "" when VAR is unset
        in the user's shell, which would shadow the config file value.
        """
        monkeypatch.setenv("_TEST_EMPTY", "")
        env = tmp_path / ".env"
        env.write_text("_TEST_EMPTY=from-config\n")

        injected = load_dotenv(env)

        import os

        assert os.environ["_TEST_EMPTY"] == "from-config"
        assert injected == {"_TEST_EMPTY": "from-config"}

    def test_overrides_self_placeholder(self, tmp_path, monkeypatch):
        """GIVEN an unresolved ${VAR} placeholder THEN load_dotenv overrides it."""
        monkeypatch.setenv("_TEST_PLACEHOLDER", "${_TEST_PLACEHOLDER}")
        env = tmp_path / ".env"
        env.write_text("_TEST_PLACEHOLDER=from-config\n")

        injected = load_dotenv(env)

        import os

        assert os.environ["_TEST_PLACEHOLDER"] == "from-config"
        assert injected == {"_TEST_PLACEHOLDER": "from-config"}

    def test_missing_file_returns_empty(self, tmp_path):
        injected = load_dotenv(tmp_path / "missing")
        assert injected == {}


# ---------------------------------------------------------------------------
# Config integration
# ---------------------------------------------------------------------------


class TestConfigIntegration:
    """Integration: get_config() loads from the .env file."""

    def test_config_loads_from_dotenv(self, tmp_path, monkeypatch, clean_config):
        """GIVEN a .env file with WEAVIATE_URL WHEN get_config() THEN config picks it up."""
        env = tmp_path / ".env"
        env.write_text("WEAVIATE_URL=http://localhost:8080\n")
        monkeypatch.delenv("WEAVIATE_URL", raising=False)

        # Patch DEFAULT_ENV_PATH so get_config() finds our test file
        monkeypatch.setattr("video_research_mcp.dotenv.DEFAULT_ENV_PATH", env)

        from video_research_mcp.config import get_config

        cfg = get_config()
        assert cfg.weaviate_url == "http://localhost:8080"

    def test_env_var_takes_precedence(self, tmp_path, monkeypatch, clean_config):
        """GIVEN both .env file and env var WHEN get_config() THEN env var wins."""
        env = tmp_path / ".env"
        env.write_text("WEAVIATE_URL=from-file\n")
        monkeypatch.setenv("WEAVIATE_URL", "https://from-env")
        monkeypatch.setattr("video_research_mcp.dotenv.DEFAULT_ENV_PATH", env)

        from video_research_mcp.config import get_config

        cfg = get_config()
        assert cfg.weaviate_url == "https://from-env"

    def test_placeholder_env_gets_replaced_by_dotenv(self, tmp_path, monkeypatch, clean_config):
        """GIVEN WEAVIATE_URL=${WEAVIATE_URL} WHEN get_config() THEN .env value wins."""
        env = tmp_path / ".env"
        env.write_text("WEAVIATE_URL=http://localhost:8080\n")
        monkeypatch.setenv("WEAVIATE_URL", "${WEAVIATE_URL}")
        monkeypatch.setattr("video_research_mcp.dotenv.DEFAULT_ENV_PATH", env)

        from video_research_mcp.config import get_config

        cfg = get_config()
        assert cfg.weaviate_url == "http://localhost:8080"
