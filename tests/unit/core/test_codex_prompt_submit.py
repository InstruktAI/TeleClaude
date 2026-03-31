"""Characterization tests for teleclaude.core.codex_prompt_submit."""

from __future__ import annotations

import pytest

# _find_prompt_input, _has_agent_marker, _is_live_agent_marker_line: pure
# text-scanning helpers; the public submit function requires a live tmux pane,
# making direct helper testing the practical characterization boundary.
from teleclaude.core.codex_prompt_submit import (
    CODEX_AGENT_MARKERS,
    CODEX_INPUT_MAX_CHARS,
    CODEX_PROMPT_MARKER,
    CodexInputState,
    _find_prompt_input,
    _has_agent_marker,
    _is_live_agent_marker_line,
    cleanup_codex_prompt_state,
    seed_codex_prompt_from_message,
)


class TestCodexConstants:
    @pytest.mark.unit
    def test_prompt_marker_is_single_char(self):
        assert len(CODEX_PROMPT_MARKER) == 1

    @pytest.mark.unit
    def test_input_max_chars_is_positive(self):
        assert CODEX_INPUT_MAX_CHARS > 0

    @pytest.mark.unit
    def test_agent_markers_is_frozenset(self):
        assert isinstance(CODEX_AGENT_MARKERS, frozenset)
        assert len(CODEX_AGENT_MARKERS) > 0


class TestCodexInputState:
    @pytest.mark.unit
    def test_default_state_is_empty(self):
        state = CodexInputState()
        assert state.last_prompt_input == ""
        assert state.last_emitted_prompt == ""
        assert state.submitted_for_current_response is False
        assert state.has_authoritative_seed is False


class TestSeedCodexPromptFromMessage:
    @pytest.mark.unit
    def test_seeds_prompt_for_session(self):
        cleanup_codex_prompt_state("seed-test-session")
        seed_codex_prompt_from_message("seed-test-session", "  hello world  ")
        # _codex_input_state is the only observation point: seed has no return value
        # and the public API offers no getter. Known tech debt: couples test to
        # internal storage structure; acceptable until a public introspection API exists.
        from teleclaude.core.codex_prompt_submit import _codex_input_state

        state = _codex_input_state.get("seed-test-session")
        assert state is not None
        assert state.last_prompt_input == "hello world"
        assert state.has_authoritative_seed is True
        cleanup_codex_prompt_state("seed-test-session")

    @pytest.mark.unit
    def test_empty_prompt_does_not_create_state(self):
        cleanup_codex_prompt_state("empty-seed-session")
        seed_codex_prompt_from_message("empty-seed-session", "   ")
        from teleclaude.core.codex_prompt_submit import _codex_input_state  # see I-1 note above

        # Empty prompt should not create a state entry
        assert "empty-seed-session" not in _codex_input_state

    @pytest.mark.unit
    def test_prompt_truncated_to_max_chars(self):
        cleanup_codex_prompt_state("trunc-session")
        long_prompt = "x" * (CODEX_INPUT_MAX_CHARS + 500)
        seed_codex_prompt_from_message("trunc-session", long_prompt)
        from teleclaude.core.codex_prompt_submit import _codex_input_state  # see I-1 note above

        state = _codex_input_state["trunc-session"]
        assert len(state.last_prompt_input) == CODEX_INPUT_MAX_CHARS
        cleanup_codex_prompt_state("trunc-session")


class TestCleanupCodexPromptState:
    @pytest.mark.unit
    def test_cleanup_removes_state(self):
        seed_codex_prompt_from_message("cleanup-session", "test prompt")
        cleanup_codex_prompt_state("cleanup-session")
        from teleclaude.core.codex_prompt_submit import _codex_input_state  # see I-1 note above

        assert "cleanup-session" not in _codex_input_state

    @pytest.mark.unit
    def test_cleanup_on_nonexistent_session_is_noop(self):
        # Should not raise
        cleanup_codex_prompt_state("nonexistent-session-xyz")


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
