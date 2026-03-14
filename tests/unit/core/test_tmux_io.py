"""Characterization tests for teleclaude.core.tmux_io."""

from __future__ import annotations

import pytest

from teleclaude.core.tmux_io import wrap_bracketed_paste


class TestWrapBracketedPaste:
    @pytest.mark.unit
    def test_empty_text_returned_unchanged(self):
        assert wrap_bracketed_paste("") == ""

    @pytest.mark.unit
    def test_slash_command_not_wrapped(self):
        result = wrap_bracketed_paste("/help")
        assert result == "/help"

    @pytest.mark.unit
    def test_path_with_multiple_slashes_wrapped(self):
        result = wrap_bracketed_paste("/Users/foo/file.txt")
        assert "\x1b[200~" in result
        assert "\x1b[201~" in result

    @pytest.mark.unit
    def test_text_with_special_chars_wrapped(self):
        result = wrap_bracketed_paste("hello & world")
        assert "\x1b[200~" in result

    @pytest.mark.unit
    def test_plain_text_no_wrapping(self):
        result = wrap_bracketed_paste("hello world")
        assert result == "hello world"

    @pytest.mark.unit
    def test_codex_next_command_normalized(self):
        result = wrap_bracketed_paste("/next-build my-slug", active_agent="codex")
        # After normalization, /next-build becomes /prompts:next-build
        assert "/prompts:next-build" in result

    @pytest.mark.unit
    def test_non_codex_agent_not_normalized(self):
        result = wrap_bracketed_paste("/next-build my-slug", active_agent="claude")
        assert result.strip().startswith("/next-build")
