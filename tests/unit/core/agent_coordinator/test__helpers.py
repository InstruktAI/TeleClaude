"""Characterization tests for teleclaude.core.agent_coordinator._helpers."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX
from teleclaude.core.agent_coordinator._helpers import (
    _MAX_FORWARDED_LINK_OUTPUT_CHARS,
    _NOOP_LOG_INTERVAL_SECONDS,
    _is_checkpoint_prompt,
    _SuppressionState,
)
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES


class TestConstants:
    @pytest.mark.unit
    def test_noop_log_interval_seconds(self):
        assert _NOOP_LOG_INTERVAL_SECONDS == 30.0

    @pytest.mark.unit
    def test_max_forwarded_link_output_chars(self):
        assert _MAX_FORWARDED_LINK_OUTPUT_CHARS == 12000

    @pytest.mark.unit
    def test_session_start_messages_is_non_empty_list(self):
        assert isinstance(SESSION_START_MESSAGES, list | tuple)
        assert len(SESSION_START_MESSAGES) > 0

    @pytest.mark.unit
    def test_session_start_messages_all_strings(self):
        assert all(isinstance(m, str) for m in SESSION_START_MESSAGES)


class TestSuppressionState:
    @pytest.mark.unit
    def test_dataclass_construction(self):
        now = datetime.now(UTC)
        state = _SuppressionState(signature="sig1", started_at=now, last_log_at=now)
        assert state.signature == "sig1"
        assert state.started_at == now
        assert state.last_log_at == now

    @pytest.mark.unit
    def test_suppressed_defaults_to_zero(self):
        now = datetime.now(UTC)
        state = _SuppressionState(signature="sig1", started_at=now, last_log_at=now)
        assert state.suppressed == 0

    @pytest.mark.unit
    def test_suppressed_can_be_set(self):
        now = datetime.now(UTC)
        state = _SuppressionState(signature="sig1", started_at=now, last_log_at=now, suppressed=5)
        assert state.suppressed == 5


class TestIsCheckpointPrompt:
    @pytest.mark.unit
    def test_empty_string_returns_false(self):
        assert _is_checkpoint_prompt("") is False

    @pytest.mark.unit
    def test_whitespace_only_returns_false(self):
        assert _is_checkpoint_prompt("   ") is False

    @pytest.mark.unit
    def test_checkpoint_prefix_returns_true(self):
        assert _is_checkpoint_prompt(CHECKPOINT_PREFIX + "extra content") is True

    @pytest.mark.unit
    def test_checkpoint_message_exact_returns_true(self):
        assert _is_checkpoint_prompt(CHECKPOINT_MESSAGE.strip()) is True

    @pytest.mark.unit
    def test_unrelated_prompt_returns_false(self):
        assert _is_checkpoint_prompt("Please help me fix this bug.") is False

    @pytest.mark.unit
    def test_prefix_not_at_start_returns_false(self):
        assert _is_checkpoint_prompt("hello " + CHECKPOINT_PREFIX) is False
