"""Characterization tests for teleclaude.core.checkpoint_dispatch."""

from __future__ import annotations

import pytest

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX

# Public API (inject_checkpoint_if_needed) is async and requires live tmux state;
# testing _is_checkpoint_prompt pins the pure classification logic.
from teleclaude.core.checkpoint_dispatch import _is_checkpoint_prompt


class TestIsCheckpointPrompt:
    @pytest.mark.unit
    def test_empty_string_returns_false(self):
        assert _is_checkpoint_prompt("") is False

    @pytest.mark.unit
    def test_whitespace_only_returns_false(self):
        assert _is_checkpoint_prompt("   ") is False

    @pytest.mark.unit
    def test_checkpoint_prefix_match_returns_true(self):
        prompt = CHECKPOINT_PREFIX + " some content"
        assert _is_checkpoint_prompt(prompt) is True

    @pytest.mark.unit
    def test_checkpoint_message_exact_returns_true(self):
        assert _is_checkpoint_prompt(CHECKPOINT_MESSAGE.strip()) is True

    @pytest.mark.unit
    def test_unrelated_prompt_returns_false(self):
        assert _is_checkpoint_prompt("Please help me refactor this code.") is False

    @pytest.mark.unit
    def test_partial_prefix_not_at_start_returns_false(self):
        prompt = "hello " + CHECKPOINT_PREFIX + " world"
        assert _is_checkpoint_prompt(prompt) is False
