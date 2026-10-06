"""Failure diagnostics must not expose result text, tool contents or secret fields."""

import importlib.util
import json
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "claude_review_diagnostic", Path(__file__).parents[1] / "scripts/claude_review_diagnostic.py",
)
diagnostic = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(diagnostic)


def test_error_result_keeps_categories_and_discards_free_form_content():
    """An SDK error with secrets must yield only fixed categories and numeric metadata."""
    secret = "PRIVATE_SENTINEL_TOKEN_DO_NOT_PUBLISH"
    result = diagnostic.summarize([
        {"type": "user", "content": secret},
        {"type": "assistant", "error": "authentication_failed", "message": secret},
        {"type": "assistant", "error": secret, "message": {"tool_result": secret}},
        {"type": "result", "subtype": "success", "is_error": True, "num_turns": 1,
         "duration_ms": 2319, "total_cost_usd": 0, "result": "Invalid API key " + secret,
         "errors": ["Please run /login " + secret], "modelUsage": {secret: {}}},
    ])
    assert secret not in json.dumps(result)
    assert result["lexical_markers"] == ["authentication"]
    assert result["api_errors"] == ["authentication_failed"]
    assert result["is_error"] is True and result["num_turns"] == 1


def test_successful_review_prose_is_not_classified_as_a_failure():
    result = diagnostic.summarize([{
        "type": "result", "subtype": "success", "is_error": False,
        "result": "The new code handles invalid API keys and rate limits.",
    }])
    assert result["lexical_markers"] == []


@pytest.mark.parametrize("value", ["PRIVATE", float("nan"), float("inf"), True, -1, 10**400])
def test_untrusted_numeric_and_subtype_fields_are_not_printed(value):
    result = diagnostic.summarize([{
        "type": "result", "subtype": "PRIVATE", "duration_ms": value, "is_error": "PRIVATE",
    }])
    assert result["subtype"] == "unknown" and result["is_error"] is None
    assert "duration_ms" not in result


@pytest.mark.parametrize("kind", ["outside", "symlink", "parent_loop", "fifo", "invalid", "oversized", "missing",
                                 "nested", "missing_runner", "non_list", "non_dict"])
def test_execution_file_boundary(tmp_path, monkeypatch, capsys, kind):
    """Only a bounded regular JSON array inside runner temp may be inspected."""
    temporary = tmp_path / "runner"
    temporary.mkdir()
    path = temporary / "result.json"
    monkeypatch.setenv("RUNNER_TEMP", str(temporary))
    monkeypatch.setenv("CLAUDE_EXECUTION_FILE", str(path))
    if kind == "outside":
        path = tmp_path / "outside.json"
        path.write_text('[{"type":"result","result":"PRIVATE"}]')
        monkeypatch.setenv("CLAUDE_EXECUTION_FILE", str(path))
    elif kind == "symlink":
        target = temporary / "target.json"
        target.write_text('[{"type":"result","result":"PRIVATE"}]')
        path.symlink_to(target)
    elif kind == "parent_loop":
        loop = temporary / "loop"
        loop.symlink_to(loop)
        monkeypatch.setenv("CLAUDE_EXECUTION_FILE", str(loop / "result.json"))
    elif kind == "invalid":
        path.write_text("PRIVATE invalid JSON")
    elif kind == "fifo":
        import os

        os.mkfifo(path)
    elif kind == "oversized":
        monkeypatch.setattr(diagnostic, "MAX_BYTES", 8)
        path.write_text("PRIVATE beyond the eight byte ceiling")
    elif kind == "nested":
        import sys

        depth = sys.getrecursionlimit() + 10
        path.write_text("[" * depth + "0" + "]" * depth)
    elif kind == "missing_runner":
        monkeypatch.delenv("RUNNER_TEMP")
        path.write_text("[]")
    elif kind == "non_list":
        path.write_text('{"PRIVATE":"unexpected envelope"}')
    elif kind == "non_dict":
        path.write_text('[123, ["PRIVATE"]]')
    else:
        monkeypatch.setenv("CLAUDE_EXECUTION_FILE", "")
    diagnostic.main()
    output = capsys.readouterr().out
    assert "PRIVATE" not in output
    if kind == "nested":
        assert json.loads(output)["state"] in {"no_result", "output_unreadable"}
        return
    assert json.loads(output)["state"] == {
        "oversized": "output_too_large", "missing": "output_unavailable", "non_dict": "no_result",
    }.get(kind, "output_unreadable")


def test_parser_recursion_refusal_returns_fixed_state(tmp_path, monkeypatch, capsys):
    """A parser refusing depth must yield bounded metadata without a traceback."""
    path = tmp_path / "result.json"
    path.write_text("[]")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("CLAUDE_EXECUTION_FILE", str(path))
    parse_output = json.loads

    def refuse(_):
        raise RecursionError("PRIVATE parser detail")

    monkeypatch.setattr(diagnostic.json, "loads", refuse)
    diagnostic.main()
    assert parse_output(capsys.readouterr().out) == {"state": "output_unreadable"}


def test_regular_execution_file_reports_only_final_metadata(tmp_path, monkeypatch, capsys):
    path = tmp_path / "result.json"
    path.write_text(json.dumps([{
        "type": "result", "subtype": "success", "is_error": True,
        "result": "PRIVATE", "errors": ["Credit balance is too low PRIVATE"],
    }]))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    monkeypatch.setenv("CLAUDE_EXECUTION_FILE", str(path))
    diagnostic.main()
    output = capsys.readouterr().out
    assert "PRIVATE" not in output
    assert json.loads(output)["lexical_markers"] == ["billing"]
