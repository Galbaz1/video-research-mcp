"""Credential leaks through upstream exceptions and configuration endpoints."""

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
