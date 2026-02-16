"""Unit tests for memory context injection in hook receiver."""

import json
from unittest.mock import patch

from teleclaude.hooks.adapters.claude import ClaudeAdapter
from teleclaude.hooks.adapters.codex import CodexAdapter
from teleclaude.hooks.adapters.gemini import GeminiAdapter
from teleclaude.hooks.receiver import _get_memory_context, _print_memory_injection


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


def test_format_memory_injection_claude():
    """Test Claude adapter formats hookSpecificOutput with hookEventName."""
    adapter = ClaudeAdapter()
    result = json.loads(adapter.format_memory_injection("test context"))
    assert result == {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": "test context",
        }
    }


def test_format_memory_injection_gemini():
    """Test Gemini adapter formats hookSpecificOutput without hookEventName."""
    adapter = GeminiAdapter()
    result = json.loads(adapter.format_memory_injection("test context"))
    assert result == {
        "hookSpecificOutput": {
            "additionalContext": "test context",
        }
    }


def test_format_memory_injection_codex():
    """Test Codex adapter returns empty (no SessionStart hook mechanism)."""
    adapter = CodexAdapter()
    result = adapter.format_memory_injection("test context")
    assert result == ""


def test_print_memory_injection_no_cwd(capsys):
    """Test no output when cwd is None."""
    adapter = ClaudeAdapter()
    _print_memory_injection(None, adapter)
    assert capsys.readouterr().out == ""


def test_print_memory_injection_empty_context(capsys):
    """Test no output when context returns empty."""
    adapter = ClaudeAdapter()
    with patch("teleclaude.hooks.receiver._get_memory_context", return_value=""):
        _print_memory_injection("/tmp/foo", adapter)
        assert capsys.readouterr().out == ""


def test_print_memory_injection_claude(capsys):
    """Test Claude output is valid hookSpecificOutput JSON."""
    adapter = ClaudeAdapter()
    with patch("teleclaude.hooks.receiver._get_memory_context", return_value="memory context here"):
        _print_memory_injection("/tmp/myproject", adapter)
        output = json.loads(capsys.readouterr().out)
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert output["hookSpecificOutput"]["additionalContext"] == "memory context here"


def test_print_memory_injection_gemini(capsys):
    """Test Gemini output is valid hookSpecificOutput JSON without hookEventName."""
    adapter = GeminiAdapter()
    with patch("teleclaude.hooks.receiver._get_memory_context", return_value="memory context here"):
        _print_memory_injection("/tmp/myproject", adapter)
        output = json.loads(capsys.readouterr().out)
        assert "hookEventName" not in output["hookSpecificOutput"]
        assert output["hookSpecificOutput"]["additionalContext"] == "memory context here"
