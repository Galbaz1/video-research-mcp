"""Credential leaks through upstream exceptions and configuration endpoints."""

import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from video_explainer_mcp.errors import make_tool_error
from video_explainer_mcp.redaction import redact_text


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
    """GIVEN an embedded known secret WHEN an error is returned THEN both fields redact it."""
    monkeypatch.setattr(
        "video_explainer_mcp.redaction.os.environ", {"EXAMPLE_API_KEY": "dummy key/value"}
    )
    result = make_tool_error(RuntimeError(f"Diagnostic {prefix}{encoded}{suffix}"))
    expected = f"Diagnostic {prefix}[redacted]{suffix}"
    assert result["error"] == expected
    assert result["hint"] == expected


def test_known_alphanumeric_secret_embedded_without_field(monkeypatch):
    """GIVEN the reported word-boundary counterexample THEN the whole known value is removed."""
    monkeypatch.setattr("video_explainer_mcp.redaction.os.environ", {"EXAMPLE_API_KEY": "abcdefgh"})
    assert redact_text("diagnostic prefixabcdefghsuffix") == "diagnostic prefix[redacted]suffix"


@pytest.mark.parametrize("diagnostic", ["letters", "dotted"])
def test_long_nonmatching_diagnostic_finishes_in_subprocess(diagnostic):
    """Long unchanged diagnostics complete under an isolated subprocess deadline."""
    source = Path(__file__).parents[1] / "src" / "video_explainer_mcp" / "redaction.py"
    script = """
import importlib.util
import json
import sys
import time

spec = importlib.util.spec_from_file_location("fixture_redaction", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.os.environ = {}
message = "a" * 200_000 if sys.argv[2] == "letters" else "a." * 100_000
started = time.perf_counter()
assert module.redact_text(message) == message
print(json.dumps({"characters": len(message), "redaction_seconds": time.perf_counter() - started}))
"""
    started = time.perf_counter()
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(source), diagnostic],
        capture_output=True,
        text=True,
        check=True,
        timeout=15,
        env={},
    )
    observation = json.loads(result.stdout)
    assert observation["characters"] == 200_000
    print(f"{diagnostic}: {observation}; subprocess_seconds={time.perf_counter() - started:.6f}")


@pytest.mark.parametrize(
    "url,resource",
    [
        (
            "https://bucket.s3.amazonaws.com/nested/clip%20one.mp4"
            "?X-Amz-Credential=fake%2F20261006%2Feu-west-1%2Fs3%2Faws4_request"
            "&X-Amz-Signature=fake-signature",
            "https://bucket.s3.amazonaws.com/nested/clip%20one.mp4",
        ),
        (
            "https://storage.googleapis.com/example-bucket/nested/clip.mp4"
            "?X-Goog-Credential=fake&X-Goog-Signature=fake-signature",
            "https://storage.googleapis.com/example-bucket/nested/clip.mp4",
        ),
    ],
)
def test_signed_storage_url_preserves_resource_path(url, resource):
    """Signed storage URL shapes retain the path while every query value is removed."""
    assert redact_text(f"Fetch {url}") == f"Fetch {resource}?[redacted]"
