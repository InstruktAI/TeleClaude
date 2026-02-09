"""Unit tests for memory context injection in hook receiver."""

import json
from unittest.mock import patch

from teleclaude.hooks.receiver import _format_injection_payload, _get_memory_context, _print_memory_injection


def test_get_memory_context_success():
    """Test successful fetch from local database."""
    with patch("teleclaude.memory.context.generate_context_sync", return_value="Memory timeline for project foo"):
        result = _get_memory_context("foo")
        assert result == "Memory timeline for project foo"


def test_get_memory_context_failure():
    """Test graceful failure when database is unavailable."""
    with patch("teleclaude.memory.context.generate_context_sync", side_effect=Exception("db error")):
        result = _get_memory_context("foo")
        assert result == ""


def test_format_injection_payload_claude():
    """Test Claude Code gets hookSpecificOutput with hookEventName."""
    result = json.loads(_format_injection_payload("claude", "test context"))
    assert result == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "test context",
        }
    }


def test_format_injection_payload_gemini():
    """Test Gemini gets hookSpecificOutput without hookEventName."""
    result = json.loads(_format_injection_payload("gemini", "test context"))
    assert result == {
        "hookSpecificOutput": {
            "additionalContext": "test context",
        }
    }


def test_format_injection_payload_codex():
    """Test Codex returns empty (no SessionStart hook mechanism)."""
    result = _format_injection_payload("codex", "test context")
    assert result == ""


def test_print_memory_injection_no_cwd(capsys):
    """Test no output when cwd is None."""
    _print_memory_injection(None, "claude")
    assert capsys.readouterr().out == ""


def test_print_memory_injection_empty_context(capsys):
    """Test no output when context returns empty."""
    with patch("teleclaude.hooks.receiver._get_memory_context", return_value=""):
        _print_memory_injection("/tmp/foo", "claude")
        assert capsys.readouterr().out == ""


def test_print_memory_injection_claude(capsys):
    """Test Claude output is valid hookSpecificOutput JSON."""
    with patch("teleclaude.hooks.receiver._get_memory_context", return_value="memory context here"):
        _print_memory_injection("/tmp/myproject", "claude")
        output = json.loads(capsys.readouterr().out)
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert output["hookSpecificOutput"]["additionalContext"] == "memory context here"


def test_print_memory_injection_gemini(capsys):
    """Test Gemini output is valid hookSpecificOutput JSON without hookEventName."""
    with patch("teleclaude.hooks.receiver._get_memory_context", return_value="memory context here"):
        _print_memory_injection("/tmp/myproject", "gemini")
        output = json.loads(capsys.readouterr().out)
        assert "hookEventName" not in output["hookSpecificOutput"]
        assert output["hookSpecificOutput"]["additionalContext"] == "memory context here"
