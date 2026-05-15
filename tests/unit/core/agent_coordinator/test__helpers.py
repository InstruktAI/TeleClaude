"""Characterization tests for teleclaude.core.agent_coordinator._helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX
from teleclaude.core.agent_coordinator._helpers import (
    _MAX_FORWARDED_LINK_OUTPUT_CHARS,
    _NOOP_LOG_INTERVAL_SECONDS,
    _is_checkpoint_prompt,
    _SuppressionState,
    transcript_expected_to_exist,
    transcript_has_assistant_entry,
    wait_for_transcript_ready,
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


def _session_ns(**kwargs: object) -> object:
    """Lightweight stand-in for Session — only the fields wait_for_transcript_ready reads."""
    defaults = {
        "session_id": "sess-001",
        "native_log_file": None,
        "active_agent": "claude",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


class TestTranscriptExpectedToExist:
    @pytest.mark.unit
    def test_returns_false_when_native_log_file_unset(self):
        assert transcript_expected_to_exist(_session_ns(native_log_file=None)) is False

    @pytest.mark.unit
    def test_returns_true_when_native_log_file_set(self):
        assert transcript_expected_to_exist(_session_ns(native_log_file="/tmp/x.jsonl")) is True


class TestTranscriptHasAssistantEntry:
    @pytest.mark.unit
    def test_empty_entries_returns_false(self):
        assert transcript_has_assistant_entry([]) is False

    @pytest.mark.unit
    def test_assistant_entry_via_message_field_returns_true(self):
        # Claude-shape: top-level "message" object with role+content
        entries = [{"message": {"role": "assistant", "content": [{"text": "anything"}]}}]
        assert transcript_has_assistant_entry(entries) is True

    @pytest.mark.unit
    def test_assistant_entry_via_payload_field_returns_true(self):
        # Codex-shape: nested in "payload"
        entries = [{"type": "message", "payload": {"role": "assistant", "content": []}}]
        assert transcript_has_assistant_entry(entries) is True

    @pytest.mark.unit
    def test_assistant_entry_with_empty_text_still_returns_true(self):
        # Codex's empty final_answer must count as "file ready" — the agent
        # finished, it just had nothing to say. Don't make the wait helper
        # block on text content.
        entries = [{"payload": {"role": "assistant", "content": [{"type": "output_text", "text": ""}]}}]
        assert transcript_has_assistant_entry(entries) is True

    @pytest.mark.unit
    def test_only_user_entries_returns_false(self):
        entries = [{"message": {"role": "user", "content": "hello"}}]
        assert transcript_has_assistant_entry(entries) is False


class TestWaitForTranscriptReady:
    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_unset_native_log_file_returns_true_immediately(self):
        session = _session_ns(native_log_file=None)
        result = await wait_for_transcript_ready(
            session,
            content_predicate=lambda _entries: False,  # would never pass
            timeout_s=0.1,
        )
        assert result is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_true_when_predicate_passes_first_poll(self):
        session = _session_ns(native_log_file="/tmp/ready.jsonl", active_agent="claude")
        with patch(
            "teleclaude.core.agent_coordinator._helpers._get_entries_for_agent",
            return_value=[{"message": {"role": "assistant", "content": []}}],
        ):
            result = await wait_for_transcript_ready(
                session,
                content_predicate=transcript_has_assistant_entry,
                timeout_s=1.0,
                poll_interval_s=0.01,
            )
        assert result is True

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_false_on_timeout_when_predicate_never_passes(self):
        session = _session_ns(native_log_file="/tmp/never.jsonl", active_agent="claude")
        with patch(
            "teleclaude.core.agent_coordinator._helpers._get_entries_for_agent",
            return_value=[],  # no assistant entry ever
        ):
            result = await wait_for_transcript_ready(
                session,
                content_predicate=transcript_has_assistant_entry,
                timeout_s=0.1,
                poll_interval_s=0.02,
            )
        assert result is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_false_when_transcript_expected_but_active_agent_missing(self):
        """Contract violation: native_log_file set but active_agent is None.
        Downstream extraction has no iterator to pick — fail loud instead
        of falsely signalling 'ready' and letting silent skips propagate."""
        session = _session_ns(native_log_file="/tmp/x.jsonl", active_agent=None)
        result = await wait_for_transcript_ready(
            session,
            content_predicate=transcript_has_assistant_entry,
            timeout_s=0.05,
        )
        assert result is False

    @pytest.mark.unit
    @pytest.mark.asyncio
    async def test_returns_false_when_transcript_expected_but_active_agent_invalid(self):
        """Same fail-loud surface for an active_agent string that doesn't
        resolve to a known AgentName."""
        session = _session_ns(native_log_file="/tmp/x.jsonl", active_agent="not-a-real-agent")
        result = await wait_for_transcript_ready(
            session,
            content_predicate=transcript_has_assistant_entry,
            timeout_s=0.05,
        )
        assert result is False
