"""Unit tests for event system."""

import pytest


@pytest.mark.skip(reason="TODO: Implement test")
def test_parse_command_string_with_simple_command():
    """Test that parse_command_string handles simple command.

    TODO: Test parsing:
    - Input: "new_session"
    - Verify returns ("new_session", [])
    """


@pytest.mark.skip(reason="TODO: Implement test")
def test_parse_command_string_with_arguments():
    """Test that parse_command_string extracts arguments.

    TODO: Test arguments:
    - Input: "cd /home/user"
    - Verify returns ("cd", ["/home/user"])
    """


@pytest.mark.skip(reason="TODO: Implement test")
def test_parse_command_string_strips_leading_slash():
    """Test that parse_command_string removes leading slash.

    TODO: Test slash removal:
    - Input: "/cd /path"
    - Verify returns ("cd", ["/path"])
    """


@pytest.mark.skip(reason="TODO: Implement test")
def test_parse_command_string_handles_quoted_arguments():
    """Test that parse_command_string preserves quoted strings.

    TODO: Test quotes:
    - Input: "/claude -m 'Hello world'"
    - Verify returns ("claude", ["-m", "Hello world"])
    """


@pytest.mark.skip(reason="TODO: Implement test")
def test_parse_command_string_handles_empty_string():
    """Test that parse_command_string handles empty input.

    TODO: Test edge case:
    - Input: ""
    - Verify returns (None, [])
    """


@pytest.mark.skip(reason="TODO: Implement test")
def test_parse_command_string_handles_whitespace_only():
    """Test that parse_command_string handles whitespace.

    TODO: Test edge case:
    - Input: "   "
    - Verify returns (None, [])
    """


@pytest.mark.skip(reason="TODO: Implement test")
def test_parse_command_string_handles_invalid_quotes():
    """Test that parse_command_string handles malformed quotes.

    TODO: Test error handling:
    - Input: "/cmd 'unclosed quote"
    - Verify fallback to simple split
    - Verify no crash
    """
