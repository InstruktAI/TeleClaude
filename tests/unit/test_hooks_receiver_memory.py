"""Unit tests for memory context injection in hook receiver."""

import json
from unittest.mock import patch

from teleclaude.hooks.receiver import _fetch_context_inject, _format_injection_payload, _print_memory_injection


def test_fetch_context_inject_success():
    """Test successful fetch from context/inject endpoint."""
    import urllib.request

    class FakeResponse:
        status = 200

        def read(self):
            return b"Memory timeline for project foo"

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    with patch.object(urllib.request, "urlopen", return_value=FakeResponse()) as mock_urlopen:
        result = _fetch_context_inject("foo")
        assert result == "Memory timeline for project foo"
        call_url = mock_urlopen.call_args[0][0]
        assert "api/context/inject" in call_url
        assert "projects=foo" in call_url


def test_fetch_context_inject_failure():
    """Test graceful failure when worker is down."""
    import urllib.request

    with patch.object(urllib.request, "urlopen", side_effect=ConnectionError("refused")):
        result = _fetch_context_inject("foo")
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
    """Test no output when context endpoint returns empty."""
    with patch("teleclaude.hooks.receiver._fetch_context_inject", return_value=""):
        _print_memory_injection("/tmp/foo", "claude")
        assert capsys.readouterr().out == ""


def test_print_memory_injection_claude(capsys):
    """Test Claude output is valid hookSpecificOutput JSON."""
    with patch("teleclaude.hooks.receiver._fetch_context_inject", return_value="memory context here"):
        _print_memory_injection("/tmp/myproject", "claude")
        output = json.loads(capsys.readouterr().out)
        assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
        assert output["hookSpecificOutput"]["additionalContext"] == "memory context here"


def test_print_memory_injection_gemini(capsys):
    """Test Gemini output is valid hookSpecificOutput JSON without hookEventName."""
    with patch("teleclaude.hooks.receiver._fetch_context_inject", return_value="memory context here"):
        _print_memory_injection("/tmp/myproject", "gemini")
        output = json.loads(capsys.readouterr().out)
        assert "hookEventName" not in output["hookSpecificOutput"]
        assert output["hookSpecificOutput"]["additionalContext"] == "memory context here"
