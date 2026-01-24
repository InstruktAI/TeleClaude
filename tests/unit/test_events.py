"""Unit tests for event system."""


def test_parse_command_string_with_simple_command():
    """Test that parse_command_string handles simple command."""
    from teleclaude.core.events import parse_command_string

    cmd, args = parse_command_string("new_session")

    assert cmd == "new_session"
    assert args == []


def test_parse_command_string_with_arguments():
    """Test that parse_command_string extracts arguments."""
    from teleclaude.core.events import parse_command_string

    cmd, args = parse_command_string("new_session My Project")

    assert cmd == "new_session"
    assert args == ["My", "Project"]


def test_parse_command_string_strips_leading_slash():
    """Test that parse_command_string removes leading slash."""
    from teleclaude.core.events import parse_command_string

    cmd, args = parse_command_string("/new_session My Project")

    assert cmd == "new_session"
    assert args == ["My", "Project"]


def test_parse_command_string_handles_quoted_arguments():
    """Test that parse_command_string preserves quoted strings."""
    from teleclaude.core.events import parse_command_string

    cmd, args = parse_command_string("/claude -m 'Hello world'")

    assert cmd == "claude"
    assert args == ["-m", "Hello world"]


def test_parse_command_string_handles_empty_string():
    """Test that parse_command_string handles empty input."""
    from teleclaude.core.events import parse_command_string

    cmd, args = parse_command_string("")

    assert cmd is None
    assert args == []


def test_parse_command_string_handles_whitespace_only():
    """Test that parse_command_string handles whitespace."""
    from teleclaude.core.events import parse_command_string

    cmd, args = parse_command_string("   ")

    assert cmd is None
    assert args == []


def test_parse_command_string_handles_invalid_quotes():
    """Test that parse_command_string handles malformed quotes."""
    from teleclaude.core.events import parse_command_string

    # Unclosed quote - should fall back to simple split
    cmd, args = parse_command_string("/cmd 'unclosed quote")

    # Should not crash, falls back to simple split
    assert cmd == "cmd"
    # Simple split keeps the quote characters
    assert "'unclosed" in args
