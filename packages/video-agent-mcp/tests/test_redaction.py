"""Credential leaks through upstream exceptions and configuration endpoints."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from video_agent_mcp.errors import make_tool_error
from video_agent_mcp.redaction import redact_text


@pytest.mark.parametrize(
    "message",
    [
        "Upstream rejected api_key=unknown-key while fetching document",
        'Upstream rejected {"access_token": "unknown token with spaces"}',
        "Authorization: Bearer unknown-credential\nUpstream returned 429",
        "Authorization=Bearer unknown-credential\nUpstream returned 429",
        "Cookie=session=unknown-cookie; account=unknown-account\nUpstream returned 429",
        "Cookie: session=unknown-cookie; account=private\nUpstream returned 429",
        "Set-Cookie: session=unknown-cookie; HttpOnly\nUpstream returned 429",
        "Fetch https://alice:unknown-password@example.org/report?signature=unknown-signature#unknown-secret",
    ],
)
def test_errors_remove_unrecognized_credential_forms(message):
    result = make_tool_error(RuntimeError(message))
    assert "unknown-" not in str(result)
    assert "unknown token" not in str(result)
    assert "alice:" not in str(result)
    assert "Upstream" in result["error"] or "example.org/report" in result["error"]


def test_known_secret_without_field_name_and_encoded_variants(monkeypatch):
    monkeypatch.setenv("EXAMPLE_API_KEY", "private key/value")
    value = redact_text("Failed with private key/value, private%20key%2Fvalue, private+key%2Fvalue")
    assert value == "Failed with [redacted], [redacted], [redacted]"


def test_nonsecret_diagnostic_context_is_preserved():
    assert redact_text("DNS failed for example.org; retry after 60 seconds") == (
        "DNS failed for example.org; retry after 60 seconds"
    )


def test_url_retains_resource_and_strips_all_query_values():
    assert redact_text("Fetch https://example.org/report?odd_signed_field=private#secret.") == (
        "Fetch https://example.org/report?[redacted]#[redacted]."
    )


@pytest.mark.parametrize("encoded", ["dummy key/value", "dummy%20key%2Fvalue", "dummy+key%2Fvalue"])
@pytest.mark.parametrize("prefix,suffix", [("prefix", "suffix"), ("_", "_"), ("-", "-")])
def test_known_secret_embedded_in_diagnostic_word(monkeypatch, encoded, prefix, suffix):
    """GIVEN an embedded known secret WHEN an error is returned THEN it cannot escape."""
    monkeypatch.setattr("video_agent_mcp.redaction.os.environ", {"EXAMPLE_API_KEY": "dummy key/value"})
    result = make_tool_error(RuntimeError(f"Diagnostic {prefix}{encoded}{suffix}"))
    assert result["error"] == f"Diagnostic {prefix}[redacted]{suffix}"
    assert encoded not in str(result)


def test_known_alphanumeric_secret_embedded_without_field(monkeypatch):
    """GIVEN a known value inside a word WHEN redacted THEN the full value is removed."""
    monkeypatch.setattr("video_agent_mcp.redaction.os.environ", {"EXAMPLE_API_KEY": "abcdefgh"})
    assert redact_text("diagnostic prefixabcdefghsuffix") == "diagnostic prefix[redacted]suffix"


@pytest.mark.parametrize("name,secret", [("EXAMPLE_API_KEY", "abc"), ("OTHER_SETTING", "abcdefgh")])
def test_known_secret_policy_is_preserved(monkeypatch, name, secret):
    """GIVEN an excluded short value or name WHEN redacted THEN the policy is preserved."""
    monkeypatch.setattr("video_agent_mcp.redaction.os.environ", {name: secret})
    diagnostic = f"diagnostic prefix{secret}suffix"
    assert redact_text(diagnostic) == diagnostic


@pytest.mark.parametrize("case", ["letters", "hyphens", "field"])
def test_long_agent_diagnostic_is_bounded_and_preserved(tmp_path, case):
    """GIVEN long foreign text WHEN the agent redacts it THEN it finishes without truncation."""
    agent_src = Path(__file__).resolve().parents[1] / "src"
    source = agent_src / "video_agent_mcp" / "redaction.py"
    script = """import json, socket, sys
from pathlib import Path

def deny(*args, **kwargs):
    raise AssertionError('Network denied in agent redaction unit subprocess')
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
socket.getaddrinfo = deny
from video_agent_mcp.redaction import redact_text
assert redact_text.__code__.co_filename == sys.argv[1]
value = {'letters': 'x' * 60000, 'hyphens': 'a-' * 30000,
         'field': 'x' * 60000 + 'token=private'}[sys.argv[2]]
expected = 'x' * 60000 + 'token=[redacted]' if sys.argv[2] == 'field' else value
result = redact_text(value)
assert result == expected
assert redact_text('DNS failed for example.org; retry after 60 seconds') == 'DNS failed for example.org; retry after 60 seconds'
print(json.dumps({'case': sys.argv[2], 'code_filename': redact_text.__code__.co_filename,
                  'input_length': len(value), 'output_length': len(result), 'preserved': True}))
"""
    argv = [sys.executable, "-c", script, str(source), case]
    environment = {
        "PATH": "/usr/bin:/bin", "PYTHONPATH": str(agent_src),
        "PYTHONDONTWRITEBYTECODE": "1", "PYTHONPYCACHEPREFIX": str(tmp_path / "bytecode"),
        "EXAMPLE_API_KEY": "dummy-known-secret",
    }
    record = {"argv": argv, "environment": environment, "cwd": str(tmp_path),
              "timeout_seconds": 2, "status": "REGISTERED"}
    receipt = tmp_path / "subprocess.json"
    receipt.write_text(json.dumps(record, indent=2))
    start = time.monotonic()
    try:
        result = subprocess.run(argv, env=environment, cwd=tmp_path, capture_output=True,
                                text=True, timeout=2)
    except subprocess.TimeoutExpired as exc:
        record.update(status="TIMEOUT", stdout=repr(exc.stdout), stderr=repr(exc.stderr),
                      elapsed_seconds=time.monotonic() - start, exit_code=None)
        receipt.write_text(json.dumps(record, indent=2))
        raise
    record.update(status="FINISHED", stdout=result.stdout, stderr=result.stderr,
                  elapsed_seconds=time.monotonic() - start, exit_code=result.returncode)
    receipt.write_text(json.dumps(record, indent=2))
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["case"] == case
    assert observed["code_filename"] == str(source)
    assert observed["preserved"] is True
