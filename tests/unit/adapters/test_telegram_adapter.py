"""Characterization tests for teleclaude.adapters.telegram_adapter."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.core.models import MessageMetadata, Session

TELEGRAM_MARKDOWN_V2_PARSE_MODE = "MarkdownV2"


@pytest.fixture()
def adapter(monkeypatch: pytest.MonkeyPatch) -> TelegramAdapter:
    """TelegramAdapter with all external dependencies mocked."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

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
    ):
        mock_client = MagicMock()
        return TelegramAdapter(mock_client)


def _make_session(session_id: str = "sess-1", *, native_log_file: str | None = None) -> Session:
    return Session(
        session_id=session_id,
        computer_name="test-computer",
        tmux_session_name=f"tmux-{session_id}",
        title="Test Session",
        native_log_file=native_log_file,
    )


# ---------------------------------------------------------------------------
# Class constants
# ---------------------------------------------------------------------------


def test_adapter_key_is_telegram(adapter: TelegramAdapter, snapshot: SnapshotAssertion) -> None:
    assert adapter.ADAPTER_KEY == snapshot


def test_simple_command_events_membership(adapter: TelegramAdapter, snapshot: SnapshotAssertion) -> None:
    assert adapter.SIMPLE_COMMAND_EVENTS == snapshot


def test_command_handler_overrides_membership(adapter: TelegramAdapter, snapshot: SnapshotAssertion) -> None:
    assert adapter.COMMAND_HANDLER_OVERRIDES == snapshot


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
    assert not adapter.format_output("")


def test_format_output_wraps_text_in_code_block(adapter: TelegramAdapter, snapshot: SnapshotAssertion) -> None:
    assert adapter.format_output("hello world") == snapshot


def test_format_output_shortens_long_separator_lines(adapter: TelegramAdapter, snapshot: SnapshotAssertion) -> None:
    assert adapter.format_output("─" * 118) == snapshot


def test_prepare_overflow_message_escapes_transcription_once(adapter: TelegramAdapter) -> None:
    metadata = MessageMetadata(is_transcription=True)

    prepared_text, prepared_metadata = adapter._prepare_overflow_message("hello_world", metadata)

    assert prepared_text != "hello_world"
    assert prepared_metadata is not None
    assert prepared_metadata.is_transcription is False
    assert prepared_metadata.parse_mode == TELEGRAM_MARKDOWN_V2_PARSE_MODE


# ---------------------------------------------------------------------------
# _event_to_command
# ---------------------------------------------------------------------------


def test_event_to_command_converts_underscores_to_hyphens(
    adapter: TelegramAdapter, snapshot: SnapshotAssertion
) -> None:
    assert adapter._event_to_command("key_up") == snapshot


def test_event_to_command_converts_multi_underscore(adapter: TelegramAdapter, snapshot: SnapshotAssertion) -> None:
    assert adapter._event_to_command("new_session") == snapshot


def test_event_to_command_passes_through_plain_name(adapter: TelegramAdapter, snapshot: SnapshotAssertion) -> None:
    assert adapter._event_to_command("cancel") == snapshot


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


# ---------------------------------------------------------------------------
# _build_metadata_for_thread
# ---------------------------------------------------------------------------


def test_build_metadata_for_thread_returns_markdownv2_parse_mode(
    adapter: TelegramAdapter, snapshot: SnapshotAssertion
) -> None:
    meta = adapter._build_metadata_for_thread()
    assert isinstance(meta, MessageMetadata)
    assert meta.parse_mode == snapshot


# ---------------------------------------------------------------------------
# send_threaded_output QoS wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_threaded_output_off_mode_calls_ui_adapter_directly(adapter: TelegramAdapter) -> None:
    adapter._qos_scheduler._policy.mode = "off"
    session = _make_session()
    expected = object()

    with patch(
        "teleclaude.adapters.telegram_adapter.UiAdapter.send_threaded_output", AsyncMock(return_value=expected)
    ) as mock_send:
        result = await adapter.send_threaded_output(session, "hello")

    assert result is expected
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_threaded_output_qos_enqueues_deferred_lane_work(adapter: TelegramAdapter) -> None:
    adapter._qos_scheduler._policy.mode = "coalesce_only"
    adapter._qos_scheduler.enqueue = MagicMock()
    expected_dispatched = "dispatched-result-sentinel"
    adapter.client._run_deferred_ui_lane = AsyncMock(return_value=expected_dispatched)
    session = _make_session()

    result = await adapter.send_threaded_output(session, "hello", delivery_ts=None)

    assert result is None
    adapter._qos_scheduler.enqueue.assert_called_once()
    args = adapter._qos_scheduler.enqueue.call_args.args
    kwargs = adapter._qos_scheduler.enqueue.call_args.kwargs
    assert args[0] == session.session_id
    dispatch = args[1]
    assert kwargs["is_final"] is False

    dispatched = await dispatch()

    assert dispatched == expected_dispatched
    adapter.client._run_deferred_ui_lane.assert_awaited_once()
    lane_args = adapter.client._run_deferred_ui_lane.await_args.args
    assert lane_args[0] is session
    assert lane_args[1] == TelegramAdapter.ADAPTER_KEY


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


# ---------------------------------------------------------------------------
# recover_lane_error — stale cache and readiness
# ---------------------------------------------------------------------------


def _make_session_with_topic(session_id: str = "sess-1", topic_id: int = 999) -> Session:
    """Create a session with Telegram origin metadata containing a topic_id."""
    session = _make_session(session_id)
    session.origin_metadata = {"telegram": {"topic_id": topic_id, "output_message_id": "42", "char_offset": 10}}
    return session


@pytest.mark.unit
async def test_recover_lane_error_clears_stale_topic_from_ready_cache(adapter: TelegramAdapter) -> None:
    """Recovery must evict old topic_id from _topic_ready_cache so subsequent
    sends to the same (stale) topic_id trigger proper readiness waits."""
    session = _make_session_with_topic(topic_id=999)
    adapter._topic_ready_cache.add(999)

    # New topic created during recovery
    new_session = _make_session_with_topic(topic_id=5000)

    with patch("teleclaude.adapters.telegram_adapter.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_origin_metadata = AsyncMock()
        mock_db.update_session = AsyncMock()

        adapter.ensure_channel = AsyncMock(return_value=new_session)
        adapter._wait_for_topic_ready = AsyncMock()
        task_factory = AsyncMock(return_value="ok")

        error = TimeoutError("message thread not found")
        await adapter.recover_lane_error(session, error, task_factory, "title")

    assert 999 not in adapter._topic_ready_cache


@pytest.mark.unit
async def test_recover_lane_error_waits_for_new_topic_readiness(adapter: TelegramAdapter) -> None:
    """Recovery must wait for the newly created topic to be ready before
    retrying the task factory, preventing immediate 'thread not found'."""
    old_session = _make_session_with_topic(topic_id=999)
    new_session = _make_session_with_topic(topic_id=5000)
    call_order: list[str] = []

    async def wait_side_effect(*_args: object) -> None:
        call_order.append("wait")

    async def factory_side_effect(*_args: object) -> str:
        call_order.append("factory")
        return "ok"

    with patch("teleclaude.adapters.telegram_adapter.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=old_session)
        mock_db.update_origin_metadata = AsyncMock()
        mock_db.update_session = AsyncMock()

        adapter.ensure_channel = AsyncMock(return_value=new_session)
        adapter._wait_for_topic_ready = AsyncMock(side_effect=wait_side_effect)
        task_factory = AsyncMock(side_effect=factory_side_effect)

        error = TimeoutError("message thread not found")
        await adapter.recover_lane_error(old_session, error, task_factory, "title")

    adapter._wait_for_topic_ready.assert_awaited_once_with(5000, new_session.title)
    assert call_order == ["wait", "factory"], (
        f"task_factory must not run before readiness gate; got order: {call_order}"
    )
