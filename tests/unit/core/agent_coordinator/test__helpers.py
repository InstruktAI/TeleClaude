"""Characterization tests for teleclaude.core.agent_coordinator._helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.constants import CHECKPOINT_MESSAGE, CHECKPOINT_PREFIX
from teleclaude.core.agent_coordinator._helpers import (
    _MAX_FORWARDED_LINK_OUTPUT_CHARS,
    _NOOP_LOG_INTERVAL_SECONDS,
    SESSION_START_MESSAGES,
    _coerce_nonempty_str,
    _discord_identity_meta,
    _fallback_hook_actor_name,
    _has_active_output_message,
    _identity_resolution_candidates,
    _is_checkpoint_prompt,
    _is_codex_input_already_recorded,
    _is_codex_synthetic_prompt_event,
    _resolve_hook_actor_name,
    _SuppressionState,
    _telegram_identity_meta,
    _to_utc,
    _whatsapp_identity_meta,
)
from teleclaude.core.models import Session
from teleclaude.core.models._adapter import (
    DiscordAdapterMetadata,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
    WhatsAppAdapterMetadata,
)
from teleclaude.core.origins import InputOrigin


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
        assert isinstance(SESSION_START_MESSAGES, list)
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


class TestHasActiveOutputMessage:
    @pytest.mark.unit
    def test_no_output_message_ids_returns_false(self):
        session = _make_session()
        assert _has_active_output_message(session) is False

    @pytest.mark.unit
    def test_telegram_output_message_id_returns_true(self):
        meta = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(output_message_id="msg-123"))
        session = _make_session(adapter_metadata=meta)
        assert _has_active_output_message(session) is True

    @pytest.mark.unit
    def test_discord_output_message_id_returns_true(self):
        meta = SessionAdapterMetadata(discord=DiscordAdapterMetadata(output_message_id="msg-456"))
        session = _make_session(adapter_metadata=meta)
        assert _has_active_output_message(session) is True

    @pytest.mark.unit
    def test_whatsapp_output_message_id_returns_true(self):
        meta = SessionAdapterMetadata(whatsapp=WhatsAppAdapterMetadata(output_message_id="msg-789"))
        session = _make_session(adapter_metadata=meta)
        assert _has_active_output_message(session) is True


class TestCoerceNonemptyStr:
    @pytest.mark.unit
    def test_none_returns_none(self):
        assert _coerce_nonempty_str(None) is None

    @pytest.mark.unit
    def test_empty_string_returns_none(self):
        assert _coerce_nonempty_str("") is None

    @pytest.mark.unit
    def test_whitespace_returns_none(self):
        assert _coerce_nonempty_str("   ") is None

    @pytest.mark.unit
    def test_valid_string_returned_stripped(self):
        assert _coerce_nonempty_str("  hello  ") == "hello"

    @pytest.mark.unit
    def test_integer_converted_to_string(self):
        assert _coerce_nonempty_str(123) == "123"


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


class TestTelegramIdentityMeta:
    @pytest.mark.unit
    def test_none_user_id_returns_none(self):
        assert _telegram_identity_meta(None) is None

    @pytest.mark.unit
    def test_valid_user_id_returns_mapping(self):
        result = _telegram_identity_meta(12345)
        assert result is not None
        assert result["user_id"] == "12345"
        assert result["telegram_user_id"] == "12345"


class TestDiscordIdentityMeta:
    @pytest.mark.unit
    def test_none_user_id_returns_none(self):
        assert _discord_identity_meta(None) is None

    @pytest.mark.unit
    def test_empty_string_returns_none(self):
        assert _discord_identity_meta("") is None

    @pytest.mark.unit
    def test_valid_user_id_returns_mapping(self):
        result = _discord_identity_meta("user123")
        assert result is not None
        assert result["user_id"] == "user123"
        assert result["discord_user_id"] == "user123"


class TestWhatsappIdentityMeta:
    @pytest.mark.unit
    def test_none_phone_returns_none(self):
        assert _whatsapp_identity_meta(None) is None

    @pytest.mark.unit
    def test_empty_phone_returns_none(self):
        assert _whatsapp_identity_meta("") is None

    @pytest.mark.unit
    def test_valid_phone_returns_mapping(self):
        result = _whatsapp_identity_meta("+1234567890")
        assert result is not None
        assert result["phone_number"] == "+1234567890"


class TestFallbackHookActorName:
    @pytest.mark.unit
    def test_telegram_hint_with_telegram_id(self):
        result = _fallback_hook_actor_name("telegram", 12345, None, None)
        assert result == "telegram:12345"

    @pytest.mark.unit
    def test_discord_hint_with_discord_id(self):
        result = _fallback_hook_actor_name("discord", None, "user123", None)
        assert result == "discord:user123"

    @pytest.mark.unit
    def test_whatsapp_hint_with_phone(self):
        result = _fallback_hook_actor_name("whatsapp", None, None, "+1234567890")
        assert result == "whatsapp:+1234567890"

    @pytest.mark.unit
    def test_no_hint_but_telegram_id_returns_telegram(self):
        result = _fallback_hook_actor_name("", 12345, None, None)
        assert result == "telegram:12345"

    @pytest.mark.unit
    def test_no_ids_returns_none(self):
        result = _fallback_hook_actor_name("", None, None, None)
        assert result is None


class TestIdentityResolutionCandidates:
    @pytest.mark.unit
    def test_telegram_hint_with_telegram_id_prioritized(self):
        result = _identity_resolution_candidates("telegram", 12345, None, None)
        assert len(result) >= 1
        assert result[0][0] == InputOrigin.TELEGRAM.value

    @pytest.mark.unit
    def test_discord_hint_with_discord_id_prioritized(self):
        result = _identity_resolution_candidates("discord", None, "user123", None)
        assert len(result) >= 1
        assert result[0][0] == InputOrigin.DISCORD.value

    @pytest.mark.unit
    def test_no_ids_returns_empty_list(self):
        result = _identity_resolution_candidates("", None, None, None)
        assert result == []

    @pytest.mark.unit
    def test_no_hint_all_ids_ordered_by_telegram_discord_whatsapp(self):
        result = _identity_resolution_candidates("", 12345, "user123", "+1234567890")
        origins = [r[0] for r in result]
        assert origins.index(InputOrigin.TELEGRAM.value) < origins.index(InputOrigin.DISCORD.value)


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


class TestResolveHookActorName:
    @pytest.mark.unit
    def test_no_ids_no_email_returns_operator(self):
        session = _make_session(last_input_origin=None, human_email=None)
        with patch("teleclaude.core.agent_coordinator._helpers.get_identity_resolver") as mock_resolver:
            mock_instance = MagicMock()
            mock_instance.resolve.return_value = None
            mock_resolver.return_value = mock_instance
            result = _resolve_hook_actor_name(session)
        assert result == "operator"

    @pytest.mark.unit
    def test_human_email_used_as_fallback(self):
        session = _make_session(last_input_origin=None, human_email="user@example.com")
        with patch("teleclaude.core.agent_coordinator._helpers.get_identity_resolver") as mock_resolver:
            mock_instance = MagicMock()
            mock_instance.resolve.return_value = None
            mock_resolver.return_value = mock_instance
            result = _resolve_hook_actor_name(session)
        assert result == "user@example.com"

    @pytest.mark.unit
    def test_resolved_person_name_returned(self):
        meta = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(user_id=12345))
        session = _make_session(
            last_input_origin=InputOrigin.TELEGRAM.value,
            adapter_metadata=meta,
            human_email=None,
        )
        with patch("teleclaude.core.agent_coordinator._helpers.get_identity_resolver") as mock_resolver:
            mock_identity = MagicMock()
            mock_identity.person_name = "Alice Smith"
            mock_instance = MagicMock()
            mock_instance.resolve.return_value = mock_identity
            mock_resolver.return_value = mock_instance
            result = _resolve_hook_actor_name(session)
        assert result == "Alice Smith"
