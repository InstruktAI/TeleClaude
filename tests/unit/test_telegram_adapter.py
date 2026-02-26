"""Unit tests for telegram_adapter.py."""

import asyncio
import inspect
import os
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest
from telegram.error import BadRequest, RetryAfter, TimedOut
from telegram.ext import filters

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude import config as config_module
from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.config import TrustedDir
from teleclaude.core.agents import AgentName
from teleclaude.core.events import SessionStatusContext
from teleclaude.core.models import MessageMetadata, Session, SessionAdapterMetadata, TelegramAdapterMetadata
from teleclaude.types.commands import KeysCommand
from teleclaude.utils.markdown import telegramify_markdown
from teleclaude.utils.transcript import render_agent_output


@pytest.fixture
def mock_full_config():
    """Mock full application configuration."""
    return {
        "computer": {
            "name": "test_computer",
            "default_working_dir": "/teleclaude",
            "trusted_dirs": [
                TrustedDir(name="tmp", desc="temp files", path="/tmp"),
                TrustedDir(name="user", desc="user home", path="/home/user"),
            ],
        },
        "telegram": {"enabled": True, "trusted_bots": ["teleclaude_bot1", "teleclaude_bot2"]},
    }


@pytest.fixture
def mock_env(monkeypatch):
    """Mock environment variables for Telegram."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
    monkeypatch.setenv("TELEGRAM_SUPERGROUP_ID", "-100123456789")
    monkeypatch.setenv("TELEGRAM_USER_IDS", "12345,67890")


@pytest.fixture
def mock_adapter_client():
    """Mock AdapterClient."""
    client = MagicMock()
    client.pre_handle_command = AsyncMock()
    client.post_handle_command = AsyncMock()
    client.broadcast_command_action = AsyncMock()
    return client


@pytest.fixture
def telegram_adapter(mock_full_config, mock_env, mock_adapter_client):
    """Create TelegramAdapter instance."""
    # Mock the config module
    with patch.object(config_module, "config") as mock_config:
        mock_config.computer.name = mock_full_config["computer"]["name"]
        mock_config.computer.default_working_dir = mock_full_config["computer"]["default_working_dir"]
        mock_config.computer.trusted_dirs = mock_full_config["computer"]["trusted_dirs"]
        mock_config.computer.get_all_trusted_dirs.return_value = mock_full_config["computer"]["trusted_dirs"]
        mock_config.telegram.enabled = mock_full_config["telegram"]["enabled"]
        return TelegramAdapter(mock_adapter_client)


class TestInitialization:
    """Tests for adapter initialization."""

    def test_ensure_started_raises_when_not_started(self, telegram_adapter):
        """Test _ensure_started raises when app is None."""
        with pytest.raises(AdapterError, match="not started"):
            telegram_adapter._ensure_started()

    @pytest.mark.asyncio
    async def test_stop_stops_qos_before_telegram_transport(self, telegram_adapter):
        call_order: list[str] = []

        async def _record_qos_stop() -> None:
            call_order.append("qos")

        async def _record_updater_stop() -> None:
            call_order.append("updater")

        async def _record_app_stop() -> None:
            call_order.append("app")

        async def _record_app_shutdown() -> None:
            call_order.append("shutdown")

        telegram_adapter._stop_output_scheduler = AsyncMock(side_effect=_record_qos_stop)  # type: ignore[method-assign]
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.updater = MagicMock()
        telegram_adapter.app.updater.stop = AsyncMock(side_effect=_record_updater_stop)
        telegram_adapter.app.stop = AsyncMock(side_effect=_record_app_stop)
        telegram_adapter.app.shutdown = AsyncMock(side_effect=_record_app_shutdown)

        await telegram_adapter.stop()

        telegram_adapter._stop_output_scheduler.assert_awaited_once()  # type: ignore[attr-defined]
        telegram_adapter.app.updater.stop.assert_awaited_once()
        telegram_adapter.app.stop.assert_awaited_once()
        telegram_adapter.app.shutdown.assert_awaited_once()
        assert call_order[:4] == ["qos", "updater", "app", "shutdown"]


class TestCommandHandlerFilters:
    """Tests for command handler update filters."""

    def test_command_handler_filter_is_message_only(self, telegram_adapter):
        """Command handlers should only process new messages (not edits)."""
        assert telegram_adapter._get_command_handler_update_filter() == filters.UpdateType.MESSAGE


class TestSimpleCommandHandlers:
    """Tests for simple command handling metadata propagation."""

    @pytest.mark.asyncio
    async def test_simple_command_propagates_message_id(self, telegram_adapter):
        """Simple commands should include message_id for UI cleanup tracking."""

        session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="tmux-123",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=999)),
        )

        update = MagicMock()
        update.effective_user = MagicMock()
        update.effective_user.id = 12345
        update.effective_message = MagicMock()
        update.effective_message.message_id = 456
        update.effective_message.message_thread_id = 999

        context = MagicMock()
        context.args = []

        mock_commands = MagicMock()
        mock_commands.keys = AsyncMock()

        with (
            patch("teleclaude.adapters.telegram_adapter.db") as mock_db,
            patch("teleclaude.adapters.ui_adapter.db") as mock_ui_db,
            patch("teleclaude.adapters.telegram_adapter.get_command_service", return_value=mock_commands),
        ):
            mock_db.get_sessions_by_adapter_metadata = AsyncMock(return_value=[session])
            mock_ui_db.update_session = AsyncMock()

            await telegram_adapter._handle_simple_command(update, context, "cancel")

        assert mock_commands.keys.await_count == 1
        args, _kwargs = mock_commands.keys.call_args
        cmd = args[0]
        assert isinstance(cmd, KeysCommand)
        assert cmd.session_id == "session-123"
        assert cmd.key == "cancel"

    def test_dynamic_handler_registration_does_not_override_callback_cancel(self, telegram_adapter):
        """Callback cancel handler must remain callback-shaped (query, args)."""
        params = list(inspect.signature(telegram_adapter._handle_cancel).parameters.keys())
        assert params == ["query", "args"]

    def test_cancel_command_uses_explicit_override_handler(self, telegram_adapter):
        """Slash /cancel command should resolve to _handle_cancel_command."""
        handlers = dict(telegram_adapter._get_command_handlers())
        cancel_handler = handlers.get("cancel")
        assert cancel_handler is not None
        assert getattr(cancel_handler, "__name__", "") == "_handle_cancel_command"


class TestMessaging:
    """Tests for message sending/editing methods."""

    @pytest.mark.asyncio
    async def test_edit_message_success(self, telegram_adapter):
        """Test editing a message."""

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock()

        # Mock session_manager
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_sm:
            mock_sm.get_session = AsyncMock(return_value=mock_session)

            metadata = MessageMetadata(parse_mode="MarkdownV2")
            result = await telegram_adapter.edit_message(mock_session, "456", "new text", metadata=metadata)

            calls = []

            async def record_edit_message_text(**kwargs):
                calls.append(kwargs)
                return True

            telegram_adapter.app.bot.edit_message_text = record_edit_message_text

            result = await telegram_adapter.edit_message(mock_session, "456", "updated text", metadata=metadata)

            assert result is True
            assert len(calls) == 1
            call_kwargs = calls[0]
            assert call_kwargs["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_edit_message_truncates_oversized_markdownv2_payload(self, telegram_adapter):
        """Edit payloads should be truncated safely to Telegram message size limit."""
        session = Session(
            session_id="session-edit-truncate",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        calls = []

        async def record_edit_message_text(**kwargs):
            calls.append(kwargs)
            return True

        telegram_adapter.app.bot.edit_message_text = record_edit_message_text

        # Oversized MarkdownV2 payload with punctuation and open inline code risk.
        long_text = ("prefix.with.symbols - value! " * 220) + "`unterminated snippet"
        result = await telegram_adapter.edit_message(
            session,
            "456",
            long_text,
            metadata=MessageMetadata(parse_mode="MarkdownV2"),
        )

        assert result is True
        assert len(calls) == 1
        sent_text = calls[0]["text"]
        assert len(sent_text) <= 4096
        assert not sent_text.endswith("\\")

    @pytest.mark.asyncio
    async def test_edit_message_timeout_treated_as_transient(self, telegram_adapter):
        """Session output edits should keep message id on transient timeout."""
        session = Session(
            session_id="session-edit-timeout",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock(side_effect=TimedOut("Timed out"))

        with patch("teleclaude.utils.asyncio.sleep", new=AsyncMock()):
            result = await telegram_adapter.edit_message(
                session,
                "456",
                "updated",
                metadata=MessageMetadata(parse_mode=None),
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_send_message_honors_parse_mode_none(self, telegram_adapter):
        """Explicit parse_mode=None should send plain text (no markdown parser)."""
        session = Session(
            session_id="session-plain",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter._wait_for_topic_ready = AsyncMock()  # type: ignore[method-assign]

        calls = []

        async def record_send_message(**kwargs):
            calls.append(kwargs)
            msg = MagicMock()
            msg.message_id = 777
            return msg

        telegram_adapter.app.bot.send_message = record_send_message

        result = await telegram_adapter.send_message(session, "plain footer", metadata=MessageMetadata(parse_mode=None))
        assert result == "777"
        assert len(calls) == 1
        assert calls[0]["parse_mode"] is None

    @pytest.mark.asyncio
    async def test_send_message_markdown_parse_error_is_not_fallbacked(self, telegram_adapter):
        """Markdown parse errors should surface (no silent plain-text fallback)."""
        fixture = Path("tests/fixtures/transcripts/gemini_real_escape_regression_snapshot.json")
        rendered, _ts = render_agent_output(
            str(fixture),
            AgentName.GEMINI,
            include_tools=True,
            include_tool_results=False,
        )
        assert rendered
        formatted = telegramify_markdown(rendered)

        session = Session(
            session_id="session-mdv2-fallback",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter._wait_for_topic_ready = AsyncMock()  # type: ignore[method-assign]

        calls = []

        async def fake_send_message(**kwargs):
            calls.append(kwargs)
            raise BadRequest("can't parse entities: character '.' is reserved")

        telegram_adapter.app.bot.send_message = fake_send_message

        with pytest.raises(BadRequest):
            await telegram_adapter.send_message(
                session,
                formatted,
                metadata=MessageMetadata(parse_mode="MarkdownV2"),
            )
        assert len(calls) == 1
        assert calls[0]["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_edit_general_message_timeout_treated_as_transient(self, telegram_adapter):
        """General menu edits should not force recreation on transient timeout."""
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock(side_effect=TimedOut("Timed out"))

        with patch("teleclaude.utils.asyncio.sleep", new=AsyncMock()):
            result = await telegram_adapter.edit_general_message(
                "123",
                "menu text",
                metadata=MessageMetadata(parse_mode=None),
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_edit_general_message_not_found_returns_false(self, telegram_adapter):
        """General menu edits should recreate only when message is actually missing."""
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock(side_effect=BadRequest("Message to edit not found"))

        result = await telegram_adapter.edit_general_message(
            "123",
            "menu text",
            metadata=MessageMetadata(parse_mode=None),
        )

        assert result is False

    @pytest.mark.asyncio
    async def test_send_file_uses_retry_wrapper(self, telegram_adapter):
        """send_file should route through _send_document_with_retry (retry-protected path)."""
        session = Session(
            session_id="session-file",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=123)),
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter._send_document_with_retry = AsyncMock()  # type: ignore[method-assign]
        mock_msg = MagicMock()
        mock_msg.message_id = 987
        telegram_adapter._send_document_with_retry.return_value = mock_msg  # type: ignore[attr-defined]

        result = await telegram_adapter.send_file(session, "/tmp/example.log", caption="cap")

        assert result == "987"
        telegram_adapter._send_document_with_retry.assert_awaited_once_with(  # type: ignore[attr-defined]
            telegram_adapter.supergroup_id,
            123,
            "/tmp/example.log",
            "example.log",
            "cap",
        )

    @pytest.mark.asyncio
    async def test_send_general_message_uses_retry_wrapper(self, telegram_adapter):
        """send_general_message should route through retry-protected helper."""
        telegram_adapter.app = MagicMock()
        telegram_adapter._send_general_message_with_retry = AsyncMock()  # type: ignore[method-assign]
        mock_msg = MagicMock()
        mock_msg.message_id = 1234
        telegram_adapter._send_general_message_with_retry.return_value = mock_msg  # type: ignore[attr-defined]

        result = await telegram_adapter.send_general_message(
            "menu",
            metadata=MessageMetadata(parse_mode=None, message_thread_id=10),
        )

        assert result == "1234"
        telegram_adapter._send_general_message_with_retry.assert_awaited_once_with(  # type: ignore[attr-defined]
            10,
            "menu",
            None,
            None,
        )

    @pytest.mark.asyncio
    async def test_send_message_to_topic_uses_retry_wrapper(self, telegram_adapter):
        """send_message_to_topic should use retry-protected helper for topic/general routes."""
        telegram_adapter.app = MagicMock()
        telegram_adapter._send_general_message_with_retry = AsyncMock()  # type: ignore[method-assign]
        topic_msg = MagicMock()
        topic_msg.message_id = 44
        general_msg = MagicMock()
        general_msg.message_id = 45
        telegram_adapter._send_general_message_with_retry.side_effect = [topic_msg, general_msg]  # type: ignore[attr-defined]

        result_topic = await telegram_adapter.send_message_to_topic(7, "hello", parse_mode="Markdown")
        result_general = await telegram_adapter.send_message_to_topic(None, "hi", parse_mode=None)

        assert result_topic.message_id == 44
        assert result_general.message_id == 45
        telegram_adapter._send_general_message_with_retry.assert_has_awaits(  # type: ignore[attr-defined]
            [
                call(7, "hello", "Markdown", None),
                call(None, "hi", None, None),
            ]
        )

    @pytest.mark.asyncio
    async def test_send_message_raises_when_topic_missing(self, telegram_adapter):
        """send_message should raise RuntimeError if topic_id is missing/None."""
        telegram_adapter._ensure_started = MagicMock()

        session = Session(
            session_id="session-no-topic",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=None),  # No telegram metadata
        )

        with pytest.raises(RuntimeError, match="Telegram topic_id missing"):
            await telegram_adapter.send_message(session, "hello")

        session.adapter_metadata.telegram = TelegramAdapterMetadata(topic_id=None)  # Metadata present but topic_id None
        with pytest.raises(RuntimeError, match="Telegram topic_id missing"):
            await telegram_adapter.send_message(session, "hello")

    @pytest.mark.asyncio
    async def test_send_file_raises_when_topic_missing(self, telegram_adapter):
        """send_file should raise RuntimeError if topic_id is missing/None."""
        telegram_adapter._ensure_started = MagicMock()

        session = Session(
            session_id="session-no-topic",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=None),
        )

        with pytest.raises(RuntimeError, match="Telegram topic_id missing"):
            await telegram_adapter.send_file(session, "/tmp/foo.txt")


class TestRecovery:
    """Tests for error recovery."""

    @pytest.mark.asyncio
    async def test_recover_lane_error_handles_missing_topic_exception(self, telegram_adapter):
        """recover_lane_error should catch RuntimeError('Telegram topic_id missing')."""
        session = Session(
            session_id="session-recovery",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=None)),
        )

        # Mock ensure_channel to simulate successful recovery
        telegram_adapter.ensure_channel = AsyncMock(return_value=session)

        async def task_factory(adapter, session):
            return "success"

        # Mock db calls inside recover_lane_error
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.set_output_message_id = AsyncMock()

            result = await telegram_adapter.recover_lane_error(
                session,
                RuntimeError("Telegram topic_id missing (no metadata)"),
                task_factory,
                "Title",
            )

        assert result == "success"
        telegram_adapter.ensure_channel.assert_awaited_once()

    def test_truncate_for_platform_keeps_markdownv2_balanced(self, telegram_adapter):
        """MarkdownV2 truncation should respect Telegram limit and avoid dangling escapes."""
        long_text = telegramify_markdown("Line one.\n" * 2000)
        truncated = telegram_adapter._truncate_for_platform(long_text, "MarkdownV2", 4096)
        assert len(truncated) <= 4096
        assert len(truncated.encode("utf-8")) <= 4096
        assert not truncated.endswith("\\")

    def test_truncate_for_platform_markdownv2_uses_telegram_byte_limit(self, telegram_adapter):
        """MarkdownV2 truncation enforces the 4096-byte Telegram API limit."""
        long_text = f"```\n{'😀' * 3000}\n```"
        truncated = telegram_adapter._truncate_for_platform(long_text, "MarkdownV2", 3900)
        assert len(truncated.encode("utf-8")) <= 4096

    def test_build_output_metadata_no_download_button(self, telegram_adapter):
        """Output metadata has MarkdownV2 parse_mode but no download button."""
        session = Session(
            session_id="session-download",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            native_log_file="/tmp/native.log",
        )

        metadata = telegram_adapter._build_output_metadata(session, _is_truncated=False)
        assert metadata.parse_mode == "MarkdownV2"
        assert metadata.reply_markup is None

    def test_build_footer_metadata_includes_download_button(self, telegram_adapter):
        """Footer metadata includes download button when native transcript exists."""
        session = Session(
            session_id="session-download",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            native_log_file="/tmp/native.log",
        )

        metadata = telegram_adapter._build_footer_metadata(session)
        assert metadata.reply_markup is not None
        keyboard = metadata.reply_markup.inline_keyboard
        assert keyboard[0][0].callback_data == "download_full:session-download"

    @pytest.mark.asyncio
    async def test_delete_message_success(self, telegram_adapter):
        """Test deleting a message."""

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.delete_message = AsyncMock()

        # Mock session_manager
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_sm:
            mock_sm.get_session = AsyncMock(return_value=mock_session)

            calls = []

            async def record_delete_message(chat_id, message_id):
                calls.append((chat_id, message_id))
                return True

            telegram_adapter.app.bot.delete_message = record_delete_message

            result = await telegram_adapter.delete_message("session-123", "456")

            assert result is True
            assert len(calls) == 1


class TestChannelManagement:
    """Tests for channel/topic management."""

    @pytest.mark.asyncio
    async def test_create_channel_success(self, telegram_adapter):
        """Test creating a forum topic."""
        from teleclaude.core.models import ChannelMetadata

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        mock_topic = MagicMock()
        mock_topic.message_thread_id = 123
        telegram_adapter.app.bot.create_forum_topic = AsyncMock(return_value=mock_topic)

        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-session",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Topic",
        )

        # Mock db.get_session to return session without topic_id (first creation)
        with (
            patch("teleclaude.adapters.telegram.channel_ops.db") as mock_db,
            patch.object(telegram_adapter, "_wait_for_topic_ready", new_callable=AsyncMock) as mock_wait,
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            mock_db.update_session = AsyncMock()
            result = await telegram_adapter.create_channel(mock_session, "Test Topic", ChannelMetadata())

            calls = []

            async def record_create_forum_topic(*args, **kwargs):
                calls.append((args, kwargs))
                return mock_topic

            telegram_adapter.app.bot.create_forum_topic = record_create_forum_topic

            result = await telegram_adapter.create_channel(mock_session, "Test Topic", ChannelMetadata())

            assert result == "123"
            assert len(calls) == 0
            mock_wait.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_wait_for_topic_ready_timeout_is_soft(self, telegram_adapter, monkeypatch):
        """Timeout waiting for topic readiness should not raise."""
        topic_id = 321
        telegram_adapter._topic_ready_cache.clear()
        telegram_adapter._topic_ready_events[topic_id] = asyncio.Event()

        monkeypatch.setattr("teleclaude.adapters.telegram.channel_ops.TOPIC_READY_TIMEOUT_S", 0.0)

        await telegram_adapter._wait_for_topic_ready(topic_id, "Slow Topic")

        assert topic_id in telegram_adapter._topic_ready_cache

    @pytest.mark.asyncio
    async def test_create_channel_deduplication_returns_existing_topic(self, telegram_adapter):
        """Test that create_channel returns existing topic_id instead of creating duplicate."""
        from teleclaude.core.models import ChannelMetadata

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.create_forum_topic = AsyncMock()  # Should NOT be called

        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-session",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Topic",
        )

        # Mock db.get_session to return session WITH existing topic_id
        session_with_topic = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-session",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Topic",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=999)),
        )

        with patch("teleclaude.adapters.telegram.channel_ops.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session_with_topic)
            mock_db.update_session = AsyncMock()
            result = await telegram_adapter.create_channel(mock_session, "Test Topic", ChannelMetadata())

        # Should return existing topic_id, NOT create new one
        assert result == "999"
        telegram_adapter.app.bot.create_forum_topic.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_channel_success(self, telegram_adapter):
        """Test deleting a forum topic."""

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.delete_forum_topic = AsyncMock()

        from teleclaude.core.models import SessionAdapterMetadata, TelegramAdapterMetadata

        # Mock db.get_session to return a session with channel metadata
        mock_session = Session(
            session_id="123",
            computer_name="test",
            tmux_session_name="test-session",
            last_input_origin=InputOrigin.TELEGRAM.value,
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=456)),
            title="Test",
        )

        calls = []

        async def record_delete_forum_topic(*args, **kwargs):
            calls.append((args, kwargs))
            return True

        telegram_adapter.app.bot.delete_forum_topic = record_delete_forum_topic

        result = await telegram_adapter.delete_channel(mock_session)

        assert result is True
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_close_channel_missing_topic_is_noop(self, telegram_adapter):
        """close_channel should be a safe no-op when topic_id is missing."""
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.close_forum_topic = AsyncMock()

        mock_session = Session(
            session_id="123",
            computer_name="test",
            tmux_session_name="test-session",
            last_input_origin=InputOrigin.TELEGRAM.value,
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=None)),
            title="Test",
        )

        result = await telegram_adapter.close_channel(mock_session)

        assert result is False
        telegram_adapter.app.bot.close_forum_topic.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_channel_missing_topic_is_noop(self, telegram_adapter):
        """delete_channel should be a safe no-op when topic_id is missing."""
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.delete_forum_topic = AsyncMock()

        mock_session = Session(
            session_id="123",
            computer_name="test",
            tmux_session_name="test-session",
            last_input_origin=InputOrigin.TELEGRAM.value,
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=None)),
            title="Test",
        )

        result = await telegram_adapter.delete_channel(mock_session)

        assert result is False
        telegram_adapter.app.bot.delete_forum_topic.assert_not_called()


class TestRateLimitHandling:
    """Tests for rate limit handling with retry."""

    @pytest.mark.asyncio
    async def test_edit_message_rate_limit_retries_and_succeeds(self, telegram_adapter):
        """Test that rate limit on edit sleeps and retries successfully."""

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        mock_bot = MagicMock()
        telegram_adapter.app.bot = mock_bot

        # First call raises rate limit, second succeeds
        mock_bot.edit_message_text = AsyncMock(side_effect=[RetryAfter(retry_after=0.01), None])

        calls = []

        async def record_edit_message_text(*args, **kwargs):
            calls.append((args, kwargs))
            if len(calls) == 1:
                raise RetryAfter(retry_after=0.01)
            return None

        mock_bot.edit_message_text = record_edit_message_text

        result = await telegram_adapter.edit_message(mock_session, "789", "updated text")

        assert result is True
        assert len(calls) == 2

    @pytest.mark.asyncio
    async def test_edit_message_rate_limit_retries_and_fails(self, telegram_adapter):
        """Test that rate limit fails after max retries."""

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        mock_bot = MagicMock()
        telegram_adapter.app.bot = mock_bot

        # Always raises rate limit
        mock_bot.edit_message_text = AsyncMock(side_effect=RetryAfter(retry_after=0.01))

        calls = []

        async def record_edit_message_text(*args, **kwargs):
            calls.append((args, kwargs))
            raise RetryAfter(retry_after=0.01)

        mock_bot.edit_message_text = record_edit_message_text

        result = await telegram_adapter.edit_message(mock_session, "789", "updated text")

        # Rate-limited edits return True (to preserve output_message_id for retry on next update)
        assert result is True
        # Should attempt 3 times (initial + 2 retries via @command_retry)
        assert len(calls) == 3


class TestPlatformParameters:
    """Tests for platform-specific parameters."""

    def test_get_max_message_length(self, telegram_adapter):
        """Test max message length for Telegram."""
        assert telegram_adapter.get_max_message_length() == 4096

    def test_get_ai_session_poll_interval(self, telegram_adapter):
        """Test AI session poll interval."""
        assert telegram_adapter.get_ai_session_poll_interval() == 0.5


class TestReplyMarkup:
    """Tests for reply markup (inline keyboards)."""

    @pytest.mark.asyncio
    async def test_edit_message_with_reply_markup(self, telegram_adapter):
        """Test editing message with reply markup."""

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock()

        markup = {"inline_keyboard": [[{"text": "Button", "callback_data": "data"}]]}

        # Mock session_manager
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_sm:
            mock_sm.get_session = AsyncMock(return_value=mock_session)

            metadata = MessageMetadata(reply_markup=markup)  # type: ignore[arg-type]  # reply_markup is InlineKeyboardMarkup, testing with dict
            calls = []

            async def record_edit_message_text(**kwargs):
                calls.append(kwargs)
                return True

            telegram_adapter.app.bot.edit_message_text = record_edit_message_text

            result = await telegram_adapter.edit_message(mock_session, "456", "text", metadata=metadata)

            assert result is True
            assert len(calls) == 1


class TestSessionLookup:
    """Tests for session lookup by Telegram topic."""

    @pytest.mark.asyncio
    async def test_get_session_from_topic_ignores_closing_session(self, telegram_adapter):
        """_get_session_from_topic should not return sessions in closing state."""
        from teleclaude.core.models import TelegramAdapterMetadata

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=12345),
            effective_message=SimpleNamespace(message_thread_id=101),
        )
        update.message = update.effective_message

        session = Session(
            session_id="session-closing",
            computer_name="test_computer",
            tmux_session_name="tmux-closing",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Closing",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=101)),
            lifecycle_status="closing",
        )

        with patch("teleclaude.adapters.telegram_adapter.db") as mock_db:
            mock_db.get_sessions_by_adapter_metadata = AsyncMock(return_value=[session])
            found_session = await telegram_adapter._get_session_from_topic(update)

        assert found_session is None

    @pytest.mark.asyncio
    async def test_get_session_from_topic_ignores_closed_session(self, telegram_adapter):
        """_get_session_from_topic should not return already closed sessions."""
        from teleclaude.core.models import TelegramAdapterMetadata

        update = SimpleNamespace(
            effective_user=SimpleNamespace(id=12345),
            effective_message=SimpleNamespace(message_thread_id=102),
        )
        update.message = update.effective_message

        session = Session(
            session_id="session-closed",
            computer_name="test_computer",
            tmux_session_name="tmux-closed",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Closed",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=102)),
            closed_at=datetime.now(timezone.utc),
            lifecycle_status="closed",
        )

        with patch("teleclaude.adapters.telegram_adapter.db") as mock_db:
            mock_db.get_sessions_by_adapter_metadata = AsyncMock(return_value=[session])
            found_session = await telegram_adapter._get_session_from_topic(update)

        assert found_session is None


class TestMessageNotModified:
    """Tests for handling 'Message is not modified' Telegram error."""

    @pytest.mark.asyncio
    async def test_edit_message_not_modified_returns_true(self, telegram_adapter):
        """Test that 'Message is not modified' error returns True (benign error).

        When Telegram returns this error, it means the message exists but
        the content is unchanged. This should NOT clear output_message_id.
        """

        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        mock_bot = MagicMock()
        telegram_adapter.app.bot = mock_bot

        # Raise "Message is not modified" error
        mock_bot.edit_message_text = AsyncMock(
            side_effect=BadRequest("Message is not modified: specified new message content is equal to current")
        )

        calls = []

        async def record_edit_message_text(*args, **kwargs):
            calls.append((args, kwargs))
            raise BadRequest("Message is not modified: specified new message content is equal to current")

        mock_bot.edit_message_text = record_edit_message_text

        result = await telegram_adapter.edit_message(mock_session, "789", "same text")

        # Should return True (message exists, just unchanged)
        assert result is True
        assert len(calls) == 1  # No retry needed

    @pytest.mark.asyncio
    async def test_edit_message_not_found_returns_false(self, telegram_adapter):
        """Test that 'Message to edit not found' error returns False (real error).

        When Telegram returns this error, the message was deleted.
        This should clear output_message_id so a new message is created.
        """

        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        mock_bot = MagicMock()
        telegram_adapter.app.bot = mock_bot

        # Raise "Message to edit not found" error
        mock_bot.edit_message_text = AsyncMock(side_effect=BadRequest("Message to edit not found"))

        calls = []

        async def record_edit_message_text(*args, **kwargs):
            calls.append((args, kwargs))
            raise BadRequest("Message to edit not found")

        mock_bot.edit_message_text = record_edit_message_text

        result = await telegram_adapter.edit_message(mock_session, "789", "new text")

        # Should return False (message was deleted)
        assert result is False
        assert len(calls) == 1  # No retry for BadRequest


# ---------------------------------------------------------------------------
# Telegram _handle_session_status (I2)
# ---------------------------------------------------------------------------


def _build_telegram_session(topic_id: int = 888) -> Session:
    meta = SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=topic_id))
    return Session(
        session_id="sess-tg-status",
        computer_name="local",
        tmux_session_name="tc_tg_status",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Telegram: Status Test",
        adapter_metadata=meta,
    )


def _make_tg_status_context(session_id: str = "sess-tg-status") -> SessionStatusContext:
    return SessionStatusContext(
        session_id=session_id,
        status="completed",
        reason="agent_turn_complete",
        timestamp="2026-01-01T00:00:00+00:00",
    )


@pytest.mark.asyncio
async def test_telegram_handle_session_status_updates_footer(mock_full_config, mock_env, mock_adapter_client):
    """_handle_session_status calls _send_footer with the formatted lifecycle status."""
    with patch.object(config_module, "config") as mock_config:
        mock_config.computer.name = mock_full_config["computer"]["name"]
        mock_config.computer.default_working_dir = mock_full_config["computer"]["default_working_dir"]
        mock_config.computer.trusted_dirs = mock_full_config["computer"]["trusted_dirs"]
        mock_config.computer.get_all_trusted_dirs.return_value = mock_full_config["computer"]["trusted_dirs"]
        mock_config.telegram.enabled = mock_full_config["telegram"]["enabled"]
        adapter = TelegramAdapter(mock_adapter_client)

    session = _build_telegram_session(topic_id=888)
    context = _make_tg_status_context()

    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)
    fake_db.update_session = AsyncMock()

    with (
        patch("teleclaude.adapters.telegram_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch.object(adapter, "_send_footer", new_callable=AsyncMock) as mock_footer,
    ):
        await adapter._handle_session_status("SESSION_STATUS", context)

    mock_footer.assert_awaited_once()
    _args, kwargs = mock_footer.await_args
    assert "status_line" in kwargs
    assert "✅" in kwargs["status_line"]  # completed emoji from _format_lifecycle_status


@pytest.mark.asyncio
async def test_telegram_handle_session_status_skips_when_no_topic(mock_full_config, mock_env, mock_adapter_client):
    """_handle_session_status does nothing when the session has no Telegram topic_id."""
    with patch.object(config_module, "config") as mock_config:
        mock_config.computer.name = mock_full_config["computer"]["name"]
        mock_config.computer.default_working_dir = mock_full_config["computer"]["default_working_dir"]
        mock_config.computer.trusted_dirs = mock_full_config["computer"]["trusted_dirs"]
        mock_config.computer.get_all_trusted_dirs.return_value = mock_full_config["computer"]["trusted_dirs"]
        mock_config.telegram.enabled = mock_full_config["telegram"]["enabled"]
        adapter = TelegramAdapter(mock_adapter_client)

    session = Session(
        session_id="sess-tg-no-topic",
        computer_name="local",
        tmux_session_name="tc_no_topic",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="No topic",
        adapter_metadata=SessionAdapterMetadata(),
    )
    context = _make_tg_status_context(session_id=session.session_id)

    fake_db = MagicMock()
    fake_db.get_session = AsyncMock(return_value=session)

    with (
        patch("teleclaude.adapters.telegram_adapter.db", fake_db),
        patch("teleclaude.adapters.ui_adapter.db", fake_db),
        patch.object(adapter, "_send_footer", new_callable=AsyncMock) as mock_footer,
    ):
        await adapter._handle_session_status("SESSION_STATUS", context)

    mock_footer.assert_not_awaited()
