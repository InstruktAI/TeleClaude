"""Unit tests for memory context injection in hook receiver."""

import json
from unittest.mock import MagicMock, patch

from teleclaude.config.schema import PersonEntry
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


def _make_session_row(human_email=None, adapter_metadata=None):
    """Create a mock session row for tests."""
    row = MagicMock()
    row.human_email = human_email
    row.adapter_metadata = adapter_metadata
    return row


def _make_config_with_person(name, email, proficiency=None, expertise=None):
    """Create a mock config with one person."""
    person = PersonEntry(name=name, email=email, proficiency=proficiency, expertise=expertise)
    cfg = MagicMock()
    cfg.people = [person]
    return cfg


def test_print_memory_injection_proficiency_line_prepended(capsys):
    """Proficiency line is prepended to memory context when session has human_email."""
    adapter = ClaudeAdapter()
    session_id = "test-session-id"
    mock_row = _make_session_row(human_email="alice@example.com")
    mock_config = _make_config_with_person("Alice", "alice@example.com", proficiency="expert")

    with (
        patch("teleclaude.hooks.receiver._get_memory_context", return_value="memory notes"),
        patch("teleclaude.hooks.receiver._create_sync_engine"),
        patch("teleclaude.hooks.receiver.config", mock_config),
        patch("sqlmodel.Session") as mock_sql_session,
    ):
        mock_sql_session.return_value.__enter__.return_value.get.return_value = mock_row
        _print_memory_injection("/tmp/myproject", adapter, session_id=session_id)

    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("Human in the loop: Alice (expert)")
    assert "memory notes" in context


def test_print_memory_injection_proficiency_line_only(capsys):
    """Proficiency line is injected even when memory context is empty."""
    adapter = ClaudeAdapter()
    session_id = "test-session-id"
    mock_row = _make_session_row(human_email="bob@example.com")
    mock_config = _make_config_with_person("Bob", "bob@example.com", proficiency="novice")

    with (
        patch("teleclaude.hooks.receiver._get_memory_context", return_value=""),
        patch("teleclaude.hooks.receiver._create_sync_engine"),
        patch("teleclaude.hooks.receiver.config", mock_config),
        patch("sqlmodel.Session") as mock_sql_session,
    ):
        mock_sql_session.return_value.__enter__.return_value.get.return_value = mock_row
        _print_memory_injection("/tmp/myproject", adapter, session_id=session_id)

    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert context == "Human in the loop: Bob (novice)"


def test_print_memory_injection_no_person_match_no_proficiency_line(capsys):
    """When no person matches the session email, no proficiency line is injected."""
    adapter = ClaudeAdapter()
    session_id = "test-session-id"
    mock_row = _make_session_row(human_email="unknown@example.com")
    mock_config = _make_config_with_person("Alice", "alice@example.com", proficiency="expert")

    with (
        patch("teleclaude.hooks.receiver._get_memory_context", return_value="memory notes"),
        patch("teleclaude.hooks.receiver._create_sync_engine"),
        patch("teleclaude.hooks.receiver.config", mock_config),
        patch("sqlmodel.Session") as mock_sql_session,
    ):
        mock_sql_session.return_value.__enter__.return_value.get.return_value = mock_row
        _print_memory_injection("/tmp/myproject", adapter, session_id=session_id)

    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "Human in the loop" not in context
    assert context == "memory notes"


# --- Expertise block injection tests ---


def test_print_memory_injection_expertise_flat_domains(capsys):
    """Expertise with flat domains renders as simple domain: level lines."""
    adapter = ClaudeAdapter()
    session_id = "test-session-id"
    mock_row = _make_session_row(human_email="alice@example.com")
    mock_config = _make_config_with_person(
        "Alice",
        "alice@example.com",
        expertise={"teleclaude": "expert", "marketing": "novice"},
    )

    with (
        patch("teleclaude.hooks.receiver._get_memory_context", return_value=""),
        patch("teleclaude.hooks.receiver._create_sync_engine"),
        patch("teleclaude.hooks.receiver.config", mock_config),
        patch("sqlmodel.Session") as mock_sql_session,
    ):
        mock_sql_session.return_value.__enter__.return_value.get.return_value = mock_row
        _print_memory_injection("/tmp/myproject", adapter, session_id=session_id)

    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("Human in the loop: Alice")
    assert "Expertise:" in context
    assert "teleclaude: expert" in context
    assert "marketing: novice" in context


def test_print_memory_injection_expertise_structured_domain(capsys):
    """Expertise with structured domain renders default and sub-areas."""
    adapter = ClaudeAdapter()
    session_id = "test-session-id"
    mock_row = _make_session_row(human_email="alice@example.com")
    mock_config = _make_config_with_person(
        "Alice",
        "alice@example.com",
        expertise={"software-development": {"default": "advanced", "frontend": "intermediate"}},
    )

    with (
        patch("teleclaude.hooks.receiver._get_memory_context", return_value=""),
        patch("teleclaude.hooks.receiver._create_sync_engine"),
        patch("teleclaude.hooks.receiver.config", mock_config),
        patch("sqlmodel.Session") as mock_sql_session,
    ):
        mock_sql_session.return_value.__enter__.return_value.get.return_value = mock_row
        _print_memory_injection("/tmp/myproject", adapter, session_id=session_id)

    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert "software-development: advanced (frontend: intermediate)" in context


def test_print_memory_injection_expertise_fallback_no_level(capsys):
    """When neither expertise nor proficiency is set, header has no level suffix."""
    adapter = ClaudeAdapter()
    session_id = "test-session-id"
    mock_row = _make_session_row(human_email="alice@example.com")
    mock_config = _make_config_with_person("Alice", "alice@example.com")

    with (
        patch("teleclaude.hooks.receiver._get_memory_context", return_value="notes"),
        patch("teleclaude.hooks.receiver._create_sync_engine"),
        patch("teleclaude.hooks.receiver.config", mock_config),
        patch("sqlmodel.Session") as mock_sql_session,
    ):
        mock_sql_session.return_value.__enter__.return_value.get.return_value = mock_row
        _print_memory_injection("/tmp/myproject", adapter, session_id=session_id)

    output = json.loads(capsys.readouterr().out)
    context = output["hookSpecificOutput"]["additionalContext"]
    assert context.startswith("Human in the loop: Alice\n")
    assert "Expertise:" not in context
