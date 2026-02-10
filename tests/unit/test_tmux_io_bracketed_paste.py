"""Unit tests for tmux_io bracketed paste wrapping."""

import os

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core import tmux_io


def test_wrap_bracketed_paste_skips_slash_only() -> None:
    """Test that plain slashes do not trigger bracketed paste wrapping."""
    text = "path/with/slash"
    assert tmux_io.wrap_bracketed_paste(text) == text


def test_wrap_bracketed_paste_wraps_special_chars() -> None:
    """Test that special characters trigger bracketed paste wrapping."""
    text = "can you? update mozbook tmux.conf!"
    wrapped = tmux_io.wrap_bracketed_paste(text)
    assert wrapped == f"\x1b[200~{text}\x1b[201~"


def test_wrap_bracketed_paste_empty() -> None:
    """Test that empty strings stay empty."""
    assert tmux_io.wrap_bracketed_paste("") == ""


def test_wrap_bracketed_paste_skips_slash_commands() -> None:
    """Test that slash commands remain unwrapped."""
    text = "/prime-orchestrator"
    assert tmux_io.wrap_bracketed_paste(text) == text


def test_wrap_bracketed_paste_wraps_absolute_paths() -> None:
    """Test that absolute paths are wrapped to prevent shell echo."""
    text = "/Users/Morriz/Applications/ClaudeLauncher.app/Contents/MacOS/claude-launcher --resume abc123"
    wrapped = tmux_io.wrap_bracketed_paste(text)
    assert wrapped == f"\x1b[200~{text}\x1b[201~"
