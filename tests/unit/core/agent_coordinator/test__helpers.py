"""Characterization tests for teleclaude.core.agent_coordinator._helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX
from teleclaude.core.agent_coordinator._helpers import (
    _MAX_FORWARDED_LINK_OUTPUT_CHARS,
    _NOOP_LOG_INTERVAL_SECONDS,
    _is_checkpoint_prompt,
    _is_codex_input_already_recorded,
    _is_codex_synthetic_prompt_event,
    _SuppressionState,
    _to_utc,
)
from teleclaude.core.models import Session
from teleclaude.core.session_start_messages import SESSION_START_MESSAGES


def _make_session(**kwargs: object) -> Session:
    defaults: dict[str, object] = {  # guard: loose-dict - Session factory accepts varied field types
        "session_id": "sess-001",
        "computer_name": "local",
        "tmux_session_name": "test",
        "title": "Test Session",
    }
    defaults.update(kwargs)
    return Session(**defaults)


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

    @pytest.mark.unit
    def test_codex_synthetic_truncated_checkpoint_returns_true(self):
        # Truncated Codex synthetic: length >= 40 chars, CHECKPOINT_MESSAGE starts with it
        truncated = CHECKPOINT_MESSAGE.strip()[:45]
        raw = {"synthetic": True, "source": "codex_poll"}
        assert _is_checkpoint_prompt(truncated, raw_payload=raw) is True

    @pytest.mark.unit
    def test_codex_synthetic_too_short_returns_false(self):
        # Length < 40 — not matched even if prefix-compatible
        truncated = CHECKPOINT_MESSAGE.strip()[:10]
        raw = {"synthetic": True, "source": "codex_poll"}
        assert _is_checkpoint_prompt(truncated, raw_payload=raw) is False

    @pytest.mark.unit
    def test_codex_synthetic_non_checkpoint_text_returns_false(self):
        # Long enough but doesn't match checkpoint prefix
        raw = {"synthetic": True, "source": "codex_poll"}
        assert _is_checkpoint_prompt("x" * 45, raw_payload=raw) is False

    @pytest.mark.unit
    def test_non_checkpoint_text_with_synthetic_returns_false(self):
        # Unrelated text with synthetic flag but non-codex source does not match
        raw = {"synthetic": True, "source": "other_source"}
        assert _is_checkpoint_prompt("this is unrelated content " * 2, raw_payload=raw) is False


class TestIsCodexSyntheticPromptEvent:
    @pytest.mark.unit
    def test_non_mapping_returns_false(self):
        assert _is_codex_synthetic_prompt_event("not a dict") is False

    @pytest.mark.unit
    def test_none_returns_false(self):
        assert _is_codex_synthetic_prompt_event(None) is False

    @pytest.mark.unit
    def test_empty_dict_returns_false(self):
        assert _is_codex_synthetic_prompt_event({}) is False

    @pytest.mark.unit
    def test_synthetic_with_codex_source_returns_true(self):
        assert _is_codex_synthetic_prompt_event({"synthetic": True, "source": "codex_poll"}) is True

    @pytest.mark.unit
    def test_synthetic_false_returns_false(self):
        assert _is_codex_synthetic_prompt_event({"synthetic": False, "source": "codex_poll"}) is False

    @pytest.mark.unit
    def test_non_codex_source_returns_false(self):
        assert _is_codex_synthetic_prompt_event({"synthetic": True, "source": "claude"}) is False

    @pytest.mark.unit
    def test_missing_source_returns_false(self):
        assert _is_codex_synthetic_prompt_event({"synthetic": True}) is False


class TestToUtc:
    @pytest.mark.unit
    def test_naive_datetime_gets_utc_tzinfo(self):
        naive = datetime(2024, 1, 15, 12, 0, 0)
        result = _to_utc(naive)
        assert result.tzinfo == UTC

    @pytest.mark.unit
    def test_utc_aware_datetime_unchanged(self):
        aware = datetime(2024, 1, 15, 12, 0, 0, tzinfo=UTC)
        result = _to_utc(aware)
        assert result == aware

    @pytest.mark.unit
    def test_non_utc_aware_converted_to_utc(self):
        offset = timezone(timedelta(hours=2))
        aware_plus2 = datetime(2024, 1, 15, 14, 0, 0, tzinfo=offset)
        result = _to_utc(aware_plus2)
        assert result.tzinfo == UTC
        assert result.hour == 12  # 14:00+02:00 = 12:00 UTC


class TestIsCodexInputAlreadyRecorded:
    @pytest.mark.unit
    def test_none_session_returns_false(self):
        assert _is_codex_input_already_recorded(None, "some prompt") is False

    @pytest.mark.unit
    def test_empty_existing_prompt_returns_false(self):
        session = _make_session(last_message_sent=None)
        assert _is_codex_input_already_recorded(session, "new prompt") is False

    @pytest.mark.unit
    def test_empty_candidate_prompt_returns_false(self):
        session = _make_session(last_message_sent="existing")
        assert _is_codex_input_already_recorded(session, "") is False

    @pytest.mark.unit
    def test_different_prompts_returns_false(self):
        now = datetime.now(UTC)
        session = _make_session(last_message_sent="do this task", last_message_sent_at=now)
        assert _is_codex_input_already_recorded(session, "do something else") is False

    @pytest.mark.unit
    def test_matching_prompt_no_output_at_returns_true(self):
        now = datetime.now(UTC)
        session = _make_session(
            last_message_sent="do this task",
            last_message_sent_at=now,
            last_output_at=None,
        )
        assert _is_codex_input_already_recorded(session, "do this task") is True

    @pytest.mark.unit
    def test_matching_prompt_message_after_output_returns_true(self):
        output_at = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        message_at = datetime(2024, 1, 1, 11, 0, 0, tzinfo=UTC)
        session = _make_session(
            last_message_sent="do this task",
            last_message_sent_at=message_at,
            last_output_at=output_at,
        )
        assert _is_codex_input_already_recorded(session, "do this task") is True

    @pytest.mark.unit
    def test_matching_prompt_message_before_output_returns_false(self):
        message_at = datetime(2024, 1, 1, 9, 0, 0, tzinfo=UTC)
        output_at = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
        session = _make_session(
            last_message_sent="do this task",
            last_message_sent_at=message_at,
            last_output_at=output_at,
        )
        assert _is_codex_input_already_recorded(session, "do this task") is False

    @pytest.mark.unit
    def test_candidate_starts_with_existing_returns_true(self):
        now = datetime.now(UTC)
        session = _make_session(
            last_message_sent="short",
            last_message_sent_at=now,
            last_output_at=None,
        )
        assert _is_codex_input_already_recorded(session, "short and extended text") is True

    @pytest.mark.unit
    def test_existing_starts_with_candidate_returns_true(self):
        now = datetime.now(UTC)
        session = _make_session(
            last_message_sent="short and extended text",
            last_message_sent_at=now,
            last_output_at=None,
        )
        assert _is_codex_input_already_recorded(session, "short") is True
