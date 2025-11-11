"""Unit tests for telegram_adapter.py."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from telegram.error import RetryAfter

from teleclaude import config as config_module
from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.adapters.telegram_adapter import TelegramAdapter


@pytest.fixture
def mock_full_config():
    """Mock full application configuration."""
    return {
        "computer": {
            "name": "test_computer",
            "trusted_dirs": ["/tmp", "/home/user"]
        },
        "telegram": {
            "enabled": True,
            "trusted_bots": ["teleclaude_bot1", "teleclaude_bot2"]
        }
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
    with patch.object(config_module, 'config') as mock_config:
        mock_config.computer.name = mock_full_config["computer"]["name"]
        mock_config.computer.trusted_dirs = mock_full_config["computer"]["trusted_dirs"]
        mock_config.telegram.enabled = mock_full_config["telegram"]["enabled"]
        return TelegramAdapter(mock_adapter_client)


class TestInitialization:
    """Tests for adapter initialization."""

    def test_ensure_started_raises_when_not_started(self, telegram_adapter):
        """Test _ensure_started raises when app is None."""
        with pytest.raises(AdapterError, match="not started"):
            telegram_adapter._ensure_started()


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
            adapter_metadata={"channel_id": "123"}
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock()

        # Mock session_manager
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_sm:
            mock_sm.get_session = AsyncMock(return_value=mock_session)

            result = await telegram_adapter.edit_message("session-123", "456", "new text")

            assert result is True
            telegram_adapter.app.bot.edit_message_text.assert_called_once()

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
            adapter_metadata={"channel_id": "123"}
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
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        mock_topic = MagicMock()
        mock_topic.message_thread_id = 123
        telegram_adapter.app.bot.create_forum_topic = AsyncMock(return_value=mock_topic)

        result = await telegram_adapter.create_channel("session-123", "Test Topic", {})

        assert result == "123"
        telegram_adapter.app.bot.create_forum_topic.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_channel_success(self, telegram_adapter):
        """Test deleting a forum topic."""
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.delete_forum_topic = AsyncMock()

        result = await telegram_adapter.delete_channel("123")

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
            adapter_metadata={"channel_id": "123"}
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        # First call raises rate limit, second succeeds
        telegram_adapter.app.bot.edit_message_text = AsyncMock(
            side_effect=[RetryAfter(retry_after=0.01), None]
        )

        # Mock session_manager
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_sm:
            mock_sm.get_session = AsyncMock(return_value=mock_session)

            result = await telegram_adapter.edit_message("session-123", "789", "updated text")

            assert result is True
            assert telegram_adapter.app.bot.edit_message_text.call_count == 2

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
            adapter_metadata={"channel_id": "123"}
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        # Always raises rate limit
        telegram_adapter.app.bot.edit_message_text = AsyncMock(
            side_effect=RetryAfter(retry_after=0.01)
        )

        # Mock session_manager
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_sm:
            mock_sm.get_session = AsyncMock(return_value=mock_session)

            result = await telegram_adapter.edit_message("session-123", "789", "updated text")

            assert result is False
            # Should attempt 3 times (initial + 2 retries)
            assert telegram_adapter.app.bot.edit_message_text.call_count == 3


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
            adapter_metadata={"channel_id": "123"}
        )

        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock()

        markup = {"inline_keyboard": [[{"text": "Button", "callback_data": "data"}]]}

        # Mock session_manager
        with patch("teleclaude.adapters.telegram_adapter.db") as mock_sm:
            mock_sm.get_session = AsyncMock(return_value=mock_session)

            result = await telegram_adapter.edit_message("session-123", "456", "text", metadata={"reply_markup": markup})

            assert result is True
            telegram_adapter.app.bot.edit_message_text.assert_called_once()
