"""Characterization tests for teleclaude.core.codex_prompt_submit."""

from __future__ import annotations

import pytest

# _find_prompt_input, _has_agent_marker, _is_live_agent_marker_line: pure
# text-scanning helpers; the public submit function requires a live tmux pane,
# making direct helper testing the practical characterization boundary.
from teleclaude.core.codex_prompt_submit import (
    CODEX_AGENT_MARKERS,
    CODEX_PROMPT_MARKER,
    _find_prompt_input,
    _has_agent_marker,
    _is_live_agent_marker_line,
)


class TestCodexConstants:
    @pytest.mark.unit
    def test_prompt_marker_is_single_char(self):
        assert len(CODEX_PROMPT_MARKER) == 1

    @pytest.mark.unit
    def test_agent_markers_is_frozenset(self):
        assert isinstance(CODEX_AGENT_MARKERS, frozenset)
        assert len(CODEX_AGENT_MARKERS) > 0


class TestFindPromptInput:
    @pytest.mark.unit
    def test_returns_empty_for_no_prompt_marker(self):
        result = _find_prompt_input("some output without marker\nmore lines")
        assert result == ""

    @pytest.mark.unit
    def test_returns_text_after_prompt_marker(self):
        output = f"{CODEX_PROMPT_MARKER} user typed this"
        result = _find_prompt_input(output)
        assert result == "user typed this"


class TestHasAgentMarker:
    @pytest.mark.unit
    def test_returns_false_for_plain_text(self):
        assert _has_agent_marker("just some plain text output\nmore text") is False

    @pytest.mark.unit
    def test_returns_true_for_bullet_marker(self):
        # A known agent marker in the last 10 lines
        output = "some output\n" + "• Working...\n"
        assert _has_agent_marker(output) is True


class TestIsLiveAgentMarkerLine:
    @pytest.mark.unit
    def test_empty_line_returns_false(self):
        assert _is_live_agent_marker_line("") is False

    @pytest.mark.unit
    def test_plain_text_line_returns_false(self):
        assert _is_live_agent_marker_line("Hello world") is False

    @pytest.mark.unit
    def test_marker_only_line_returns_true(self):
        # A line with just the bullet marker and no other content
        assert _is_live_agent_marker_line("•") is True
