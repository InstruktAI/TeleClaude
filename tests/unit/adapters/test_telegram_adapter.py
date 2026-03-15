"""Characterization tests for teleclaude.adapters.telegram_adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.adapters.telegram.callback_handlers import CallbackAction
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.core.models import MessageMetadata, Session, SessionAdapterMetadata, TelegramAdapterMetadata


@pytest.fixture()
def adapter(monkeypatch: pytest.MonkeyPatch) -> TelegramAdapter:
    """TelegramAdapter with all external dependencies mocked."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_SUPERGROUP_ID", "12345")

    mock_cfg = MagicMock()
    mock_cfg.computer.get_all_trusted_dirs.return_value = []
    mock_cfg.telegram.trusted_bots = ["trusted_bot"]
    mock_cfg.computer.name = "test-computer"
    mock_cfg.computer.is_master = True
    mock_cfg.telegram.qos.mode = "off"

    with (
        patch("teleclaude.adapters.telegram_adapter.config", mock_cfg),
        patch("teleclaude.adapters.telegram_adapter.telegram_policy"),
        patch("teleclaude.adapters.telegram_adapter.OutputQoSScheduler"),
        patch("teleclaude.adapters.ui_adapter.event_bus"),
    ):
        mock_client = MagicMock()
        return TelegramAdapter(mock_client)


def _make_session(session_id: str = "sess-1", *, native_log_file: str | None = None) -> Session:
    return Session(
        session_id=session_id,
        computer_name="test-computer",
        tmux_session_name=f"tmux-{session_id}",
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata()),
        native_log_file=native_log_file,
    )


# ---------------------------------------------------------------------------
# Class constants
# ---------------------------------------------------------------------------


def test_adapter_key_is_telegram(adapter: TelegramAdapter) -> None:
    assert adapter.ADAPTER_KEY == "telegram"


def test_simple_command_events_contains_cancel2x(adapter: TelegramAdapter) -> None:
    assert "cancel2x" in adapter.SIMPLE_COMMAND_EVENTS


def test_simple_command_events_contains_kill(adapter: TelegramAdapter) -> None:
    assert "kill" in adapter.SIMPLE_COMMAND_EVENTS


def test_simple_command_events_contains_key_up(adapter: TelegramAdapter) -> None:
    assert "key_up" in adapter.SIMPLE_COMMAND_EVENTS


def test_command_handler_overrides_contains_agent_resume(adapter: TelegramAdapter) -> None:
    assert "agent_resume" in adapter.COMMAND_HANDLER_OVERRIDES


# ---------------------------------------------------------------------------
# get_max_message_length
# ---------------------------------------------------------------------------


def test_get_max_message_length_returns_4096(adapter: TelegramAdapter) -> None:
    assert adapter.get_max_message_length() == 4096


# ---------------------------------------------------------------------------
# get_ai_session_poll_interval
# ---------------------------------------------------------------------------


def test_get_ai_session_poll_interval_returns_half_second(adapter: TelegramAdapter) -> None:
    assert adapter.get_ai_session_poll_interval() == 0.5


# ---------------------------------------------------------------------------
# format_output
# ---------------------------------------------------------------------------


def test_format_output_returns_empty_for_empty_input(adapter: TelegramAdapter) -> None:
    assert adapter.format_output("") == ""


def test_format_output_wraps_text_in_code_block(adapter: TelegramAdapter) -> None:
    result = adapter.format_output("hello world")
    assert result.startswith("```")
    assert result.endswith("```")


def test_format_output_shortens_long_separator_lines(adapter: TelegramAdapter) -> None:
    long_sep = "─" * 118
    result = adapter.format_output(long_sep)
    # After shortening, the repeated char should be 47 occurrences
    assert "─" * 118 not in result


# ---------------------------------------------------------------------------
# _event_to_command
# ---------------------------------------------------------------------------


def test_event_to_command_converts_underscores_to_hyphens(adapter: TelegramAdapter) -> None:
    assert adapter._event_to_command("key_up") == "key-up"


def test_event_to_command_converts_multi_underscore(adapter: TelegramAdapter) -> None:
    assert adapter._event_to_command("new_session") == "new-session"


def test_event_to_command_passes_through_plain_name(adapter: TelegramAdapter) -> None:
    assert adapter._event_to_command("cancel") == "cancel"


# ---------------------------------------------------------------------------
# _validate_update_for_command
# ---------------------------------------------------------------------------


def test_validate_update_returns_true_when_user_and_message_present(adapter: TelegramAdapter) -> None:
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_message = MagicMock()
    assert adapter._validate_update_for_command(update) is True


def test_validate_update_returns_false_when_user_is_none(adapter: TelegramAdapter) -> None:
    update = MagicMock()
    update.effective_user = None
    update.effective_message = MagicMock()
    assert adapter._validate_update_for_command(update) is False


def test_validate_update_returns_false_when_message_is_none(adapter: TelegramAdapter) -> None:
    update = MagicMock()
    update.effective_user = MagicMock()
    update.effective_message = None
    assert adapter._validate_update_for_command(update) is False


# ---------------------------------------------------------------------------
# _is_message_from_trusted_bot
# ---------------------------------------------------------------------------


def test_is_message_from_trusted_bot_returns_false_when_no_message(adapter: TelegramAdapter) -> None:
    assert adapter._is_message_from_trusted_bot(None) is False


def test_is_message_from_trusted_bot_returns_false_when_no_from_user(adapter: TelegramAdapter) -> None:
    msg = MagicMock()
    msg.from_user = None
    assert adapter._is_message_from_trusted_bot(msg) is False


def test_is_message_from_trusted_bot_returns_false_for_human_user(adapter: TelegramAdapter) -> None:
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.is_bot = False
    assert adapter._is_message_from_trusted_bot(msg) is False


def test_is_message_from_trusted_bot_returns_true_for_trusted_bot(adapter: TelegramAdapter) -> None:
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.is_bot = True
    msg.from_user.username = "trusted_bot"
    assert adapter._is_message_from_trusted_bot(msg) is True


def test_is_message_from_trusted_bot_returns_false_for_unknown_bot(adapter: TelegramAdapter) -> None:
    msg = MagicMock()
    msg.from_user = MagicMock()
    msg.from_user.is_bot = True
    msg.from_user.username = "unknown_bot"
    assert adapter._is_message_from_trusted_bot(msg) is False


# ---------------------------------------------------------------------------
# store_channel_id
# ---------------------------------------------------------------------------


def test_store_channel_id_sets_topic_id_as_int(adapter: TelegramAdapter) -> None:
    adapter_metadata = SessionAdapterMetadata()
    adapter.store_channel_id(adapter_metadata, "999")
    assert adapter_metadata.get_ui().get_telegram().topic_id == 999


def test_store_channel_id_ignores_non_session_adapter_metadata(adapter: TelegramAdapter) -> None:
    # Should not raise; non-SessionAdapterMetadata is silently ignored
    adapter.store_channel_id(object(), "999")


# ---------------------------------------------------------------------------
# _build_metadata_for_thread
# ---------------------------------------------------------------------------


def test_build_metadata_for_thread_returns_markdownv2_parse_mode(adapter: TelegramAdapter) -> None:
    meta = adapter._build_metadata_for_thread()
    assert isinstance(meta, MessageMetadata)
    assert meta.parse_mode == "MarkdownV2"


# ---------------------------------------------------------------------------
# _build_output_metadata
# ---------------------------------------------------------------------------


def test_build_output_metadata_returns_markdownv2_parse_mode(adapter: TelegramAdapter) -> None:
    session = MagicMock()
    meta = adapter._build_output_metadata(session, False)
    assert isinstance(meta, MessageMetadata)
    assert meta.parse_mode == "MarkdownV2"


# ---------------------------------------------------------------------------
# _build_footer_metadata
# ---------------------------------------------------------------------------


def test_build_footer_metadata_has_no_parse_mode(adapter: TelegramAdapter) -> None:
    session = MagicMock()
    session.native_log_file = None
    meta = adapter._build_footer_metadata(session)
    assert meta.parse_mode is None


def test_build_footer_metadata_adds_keyboard_when_log_file_present(adapter: TelegramAdapter) -> None:
    session = MagicMock()
    session.native_log_file = "/tmp/session.log"
    session.session_id = "sess-1"
    meta = adapter._build_footer_metadata(session)
    assert meta.reply_markup is not None


def test_build_footer_metadata_keyboard_has_download_button(adapter: TelegramAdapter) -> None:
    session = MagicMock()
    session.native_log_file = "/tmp/session.log"
    session.session_id = "sess-42"
    meta = adapter._build_footer_metadata(session)
    # Keyboard should contain a download_full callback
    keyboard_data = str(meta.reply_markup)
    assert CallbackAction.DOWNLOAD_FULL.value in keyboard_data


# ---------------------------------------------------------------------------
# _build_project_keyboard
# ---------------------------------------------------------------------------


def test_build_project_keyboard_returns_empty_when_no_trusted_dirs(adapter: TelegramAdapter) -> None:
    adapter.trusted_dirs = []
    keyboard = adapter._build_project_keyboard("s")
    assert len(keyboard.inline_keyboard) == 0


# ---------------------------------------------------------------------------
# user-input lifecycle hooks
# ---------------------------------------------------------------------------


async def test_pre_handle_user_input_deletes_pending_messages_and_clears_tracking(adapter: TelegramAdapter) -> None:
    session = _make_session()
    adapter.delete_message = AsyncMock(side_effect=[True, True])

    with patch("teleclaude.adapters.telegram_adapter.db") as mock_db:
        mock_db.get_pending_deletions = AsyncMock(return_value=["11", "12"])
        mock_db.clear_pending_deletions = AsyncMock()

        await adapter._pre_handle_user_input(session)

    assert [call.args for call in adapter.delete_message.await_args_list] == [(session, "11"), (session, "12")]
    mock_db.clear_pending_deletions.assert_awaited_once_with(session.session_id)


async def test_post_handle_user_input_tracks_message_for_next_cleanup(adapter: TelegramAdapter) -> None:
    session = _make_session()

    with patch("teleclaude.adapters.telegram_adapter.db") as mock_db:
        mock_db.add_pending_deletion = AsyncMock()

        await adapter._post_handle_user_input(session, "42")

    mock_db.add_pending_deletion.assert_awaited_once_with(session.session_id, "42")
