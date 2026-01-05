"""Unit tests for telegram_adapter.py."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import BadRequest, RetryAfter
from telegram.ext import filters

from teleclaude import config as config_module
from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.config import TrustedDir
from teleclaude.core.models import MessageMetadata


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
    client.handle_event = AsyncMock()
    return client


@pytest.fixture
def telegram_adapter(mock_full_config, mock_env, mock_adapter_client):
    """Create TelegramAdapter instance."""
    # Mock the config module
    with patch.object(config_module, "config") as mock_config:
        mock_config.computer.name = mock_full_config["computer"]["name"]
        mock_config.computer.default_working_dir = mock_full_config["computer"]["default_working_dir"]
        mock_config.computer.trusted_dirs = mock_full_config["computer"]["trusted_dirs"]
        # Mock get_all_trusted_dirs to return teleclaude folder + trusted_dirs
        mock_config.computer.get_all_trusted_dirs.return_value = [
            TrustedDir(name="teleclaude", desc="TeleClaude folder", path="/teleclaude")
        ] + mock_full_config["computer"]["trusted_dirs"]
        mock_config.telegram.enabled = mock_full_config["telegram"]["enabled"]
        return TelegramAdapter(mock_adapter_client)


class TestInitialization:
    """Tests for adapter initialization."""

    def test_ensure_started_raises_when_not_started(self, telegram_adapter):
        """Test _ensure_started raises when app is None."""
        with pytest.raises(AdapterError, match="not started"):
            telegram_adapter._ensure_started()


class TestCommandHandlerFilters:
    """Tests for command handler update filters."""

    def test_command_handler_filter_is_message_only(self, telegram_adapter):
        """Command handlers should only process new messages (not edits)."""
        assert telegram_adapter._get_command_handler_update_filter() == filters.UpdateType.MESSAGE


class TestMessaging:
    """Tests for message sending/editing methods."""

    @pytest.mark.asyncio
    async def test_edit_message_success(self, telegram_adapter):
        """Test editing a message."""
        from teleclaude.core.models import Session

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
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
            result = await telegram_adapter.edit_message(mock_session, "456", "new text", metadata)

            assert result is True
            telegram_adapter.app.bot.edit_message_text.assert_called_once()
            call_kwargs = telegram_adapter.app.bot.edit_message_text.call_args.kwargs
            assert call_kwargs["parse_mode"] == "MarkdownV2"

    @pytest.mark.asyncio
    async def test_delete_message_success(self, telegram_adapter):
        """Test deleting a message."""
        from teleclaude.core.models import Session

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.delete_message = AsyncMock()

        # Mock session_manager
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_sm:
            mock_sm.get_session = AsyncMock(return_value=mock_session)

            result = await telegram_adapter.delete_message("session-123", "456")

            assert result is True
            telegram_adapter.app.bot.delete_message.assert_called_once()


class TestChannelManagement:
    """Tests for channel/topic management."""

    @pytest.mark.asyncio
    async def test_create_channel_success(self, telegram_adapter):
        """Test creating a forum topic."""
        from teleclaude.core.models import ChannelMetadata, Session

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        mock_topic = MagicMock()
        mock_topic.message_thread_id = 123
        telegram_adapter.app.bot.create_forum_topic = AsyncMock(return_value=mock_topic)

        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-session",
            origin_adapter="telegram",
            title="Test Topic",
        )

        # Mock db.get_session to return session without topic_id (first creation)
        with (
            patch("teleclaude.adapters.telegram_adapter.db") as mock_db,
            patch.object(telegram_adapter, "_wait_for_topic_ready", new_callable=AsyncMock) as mock_wait,
        ):
            mock_db.get_session = AsyncMock(return_value=mock_session)
            result = await telegram_adapter.create_channel(mock_session, "Test Topic", ChannelMetadata())

        assert result == "123"
        telegram_adapter.app.bot.create_forum_topic.assert_called_once()
        mock_wait.assert_awaited_once_with(123, "Test Topic")

    @pytest.mark.asyncio
    async def test_wait_for_topic_ready_timeout_is_soft(self, telegram_adapter, monkeypatch):
        """Timeout waiting for topic readiness should not raise."""
        topic_id = 321
        telegram_adapter._topic_ready_cache.clear()
        telegram_adapter._topic_ready_events[topic_id] = asyncio.Event()

        monkeypatch.setattr("teleclaude.adapters.telegram_adapter.TOPIC_READY_TIMEOUT_S", 0.0)

        await telegram_adapter._wait_for_topic_ready(topic_id, "Slow Topic")

        assert topic_id in telegram_adapter._topic_ready_cache

    @pytest.mark.asyncio
    async def test_create_channel_deduplication_returns_existing_topic(self, telegram_adapter):
        """Test that create_channel returns existing topic_id instead of creating duplicate."""
        from teleclaude.core.models import (
            ChannelMetadata,
            Session,
            SessionAdapterMetadata,
            TelegramAdapterMetadata,
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.create_forum_topic = AsyncMock()  # Should NOT be called

        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-session",
            origin_adapter="telegram",
            title="Test Topic",
        )

        # Mock db.get_session to return session WITH existing topic_id
        session_with_topic = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-session",
            origin_adapter="telegram",
            title="Test Topic",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=999)),
        )

        with patch("teleclaude.adapters.telegram_adapter.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session_with_topic)
            result = await telegram_adapter.create_channel(mock_session, "Test Topic", ChannelMetadata())

        # Should return existing topic_id, NOT create new one
        assert result == "999"
        telegram_adapter.app.bot.create_forum_topic.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_channel_success(self, telegram_adapter):
        """Test deleting a forum topic."""
        from teleclaude.core.models import Session

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.delete_forum_topic = AsyncMock()

        from teleclaude.core.models import (
            SessionAdapterMetadata,
            TelegramAdapterMetadata,
        )

        # Mock db.get_session to return a session with channel metadata
        mock_session = Session(
            session_id="123",
            computer_name="test",
            tmux_session_name="test-session",
            origin_adapter="telegram",
            adapter_metadata=SessionAdapterMetadata(telegram=TelegramAdapterMetadata(topic_id=456)),
            title="Test",
        )

        result = await telegram_adapter.delete_channel(mock_session)

        assert result is True
        telegram_adapter.app.bot.delete_forum_topic.assert_called_once()


class TestRateLimitHandling:
    """Tests for rate limit handling with retry."""

    @pytest.mark.asyncio
    async def test_edit_message_rate_limit_retries_and_succeeds(self, telegram_adapter):
        """Test that rate limit on edit sleeps and retries successfully."""
        from teleclaude.core.models import Session

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        mock_bot = MagicMock()
        telegram_adapter.app.bot = mock_bot

        # First call raises rate limit, second succeeds
        mock_bot.edit_message_text = AsyncMock(side_effect=[RetryAfter(retry_after=0.01), None])

        metadata = MessageMetadata()
        result = await telegram_adapter.edit_message(mock_session, "789", "updated text", metadata)

        assert result is True
        assert mock_bot.edit_message_text.call_count == 2

    @pytest.mark.asyncio
    async def test_edit_message_rate_limit_retries_and_fails(self, telegram_adapter):
        """Test that rate limit fails after max retries."""
        from teleclaude.core.models import Session

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        mock_bot = MagicMock()
        telegram_adapter.app.bot = mock_bot

        # Always raises rate limit
        mock_bot.edit_message_text = AsyncMock(side_effect=RetryAfter(retry_after=0.01))

        metadata = MessageMetadata()
        result = await telegram_adapter.edit_message(mock_session, "789", "updated text", metadata)

        assert result is False
        # Should attempt 3 times (initial + 2 retries)
        assert mock_bot.edit_message_text.call_count == 3


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
        from teleclaude.core.models import Session

        # Mock session with channel metadata
        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
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
            result = await telegram_adapter.edit_message(mock_session, "456", "text", metadata)

            assert result is True
            telegram_adapter.app.bot.edit_message_text.assert_called_once()


class TestMessageNotModified:
    """Tests for handling 'Message is not modified' Telegram error."""

    @pytest.mark.asyncio
    async def test_edit_message_not_modified_returns_true(self, telegram_adapter):
        """Test that 'Message is not modified' error returns True (benign error).

        When Telegram returns this error, it means the message exists but
        the content is unchanged. This should NOT clear output_message_id.
        """
        from teleclaude.core.models import Session

        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
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

        metadata = MessageMetadata()
        result = await telegram_adapter.edit_message(mock_session, "789", "same text", metadata)

        # Should return True (message exists, just unchanged)
        assert result is True
        assert mock_bot.edit_message_text.call_count == 1  # No retry needed

    @pytest.mark.asyncio
    async def test_edit_message_not_found_returns_false(self, telegram_adapter):
        """Test that 'Message to edit not found' error returns False (real error).

        When Telegram returns this error, the message was deleted.
        This should clear output_message_id so a new message is created.
        """
        from teleclaude.core.models import Session

        mock_session = Session(
            session_id="session-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            title="Test Session",
            adapter_metadata={"channel_id": "123"},
        )

        telegram_adapter.app = MagicMock()
        mock_bot = MagicMock()
        telegram_adapter.app.bot = mock_bot

        # Raise "Message to edit not found" error
        mock_bot.edit_message_text = AsyncMock(side_effect=BadRequest("Message to edit not found"))

        metadata = MessageMetadata()
        result = await telegram_adapter.edit_message(mock_session, "789", "new text", metadata)

        # Should return False (message was deleted)
        assert result is False
        assert mock_bot.edit_message_text.call_count == 1  # No retry for BadRequest
