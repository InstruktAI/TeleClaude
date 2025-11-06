"""Unit tests for telegram_adapter.py."""

import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, User, Message, Chat
from telegram.ext import ContextTypes
from telegram.error import RetryAfter

from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.base_adapter import AdapterError
from teleclaude.config import init_config


@pytest.fixture
def mock_full_config():
    """Mock full application configuration."""
    return {
        "computer": {
            "name": "test_computer",
            "trusted_dirs": ["/tmp", "/home/user"]
        },
        "telegram": {
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
def mock_session_manager():
    """Mock SessionManager."""
    manager = MagicMock()
    manager.get_session = AsyncMock()
    manager.get_sessions_by_adapter_metadata = AsyncMock()
    return manager


@pytest.fixture
def mock_daemon():
    """Mock daemon."""
    daemon = MagicMock()
    daemon.session_output_buffers = {}
    return daemon


@pytest.fixture
def telegram_adapter(mock_full_config, mock_env, mock_session_manager, mock_daemon):
    """Create TelegramAdapter instance."""
    # Reset config state before each test
    import teleclaude.config as config_module
    config_module._config = None

    init_config(mock_full_config)
    return TelegramAdapter(mock_session_manager, mock_daemon)


@pytest.fixture
def mock_update():
    """Create mock Update object."""
    update = MagicMock(spec=Update)
    update.effective_user = User(id=12345, first_name="Test", is_bot=False)

    # Setup both message and effective_message (telegram-python-bot uses effective_message)
    mock_message = MagicMock(spec=Message)
    mock_message.message_id = 999
    mock_message.message_thread_id = 123
    mock_message.text = "test message"
    mock_message.chat = Chat(id=-100123456789, type="supergroup")

    update.message = mock_message
    update.effective_message = mock_message
    return update


class TestInitialization:
    """Tests for adapter initialization."""

    def test_init_with_config(self, mock_full_config, mock_env, mock_session_manager, mock_daemon):
        """Test adapter initializes with config and env vars."""
        # Reset config state
        import teleclaude.config as config_module
        config_module._config = None

        init_config(mock_full_config)
        adapter = TelegramAdapter(mock_session_manager, mock_daemon)

        assert adapter.bot_token == "123456:ABC-DEF"
        assert adapter.supergroup_id == -100123456789
        assert adapter.user_whitelist == [12345, 67890]
        assert adapter.trusted_dirs == ["/tmp", "/home/user"]
        assert adapter.computer_name == "test_computer"

    def test_ensure_started_raises_when_not_started(self, telegram_adapter):
        """Test _ensure_started raises when app is None."""
        with pytest.raises(AdapterError, match="not started"):
            telegram_adapter._ensure_started()


class TestSessionFromTopic:
    """Tests for _get_session_from_topic helper."""

    @pytest.mark.asyncio
    async def test_unauthorized_user(self, telegram_adapter, mock_update):
        """Test that unauthorized user returns None."""
        # Set user to unauthorized ID
        mock_update.effective_user = User(id=99999, first_name="Unauthorized", is_bot=False)

        result = await telegram_adapter._get_session_from_topic(mock_update)

        assert result is None

    @pytest.mark.asyncio
    async def test_authorized_user_no_topic(self, telegram_adapter, mock_update, mock_session_manager):
        """Test authorized user but no topic returns None."""
        # Set message_thread_id to None (general chat)
        mock_update.effective_message.message_thread_id = None

        result = await telegram_adapter._get_session_from_topic(mock_update)

        assert result is None

    @pytest.mark.asyncio
    async def test_authorized_user_with_session(self, telegram_adapter, mock_update, mock_session_manager):
        """Test authorized user with valid session."""
        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"
        mock_session_manager.get_sessions_by_adapter_metadata.return_value = [mock_session]

        result = await telegram_adapter._get_session_from_topic(mock_update)

        assert result == mock_session
        mock_session_manager.get_sessions_by_adapter_metadata.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_to_topic_id(self, telegram_adapter, mock_update, mock_session_manager):
        """Test fallback to old topic_id format when channel_id fails."""
        # First call returns empty (no channel_id), second returns session (topic_id)
        mock_session = MagicMock()
        mock_session.session_id = "test-session-456"
        mock_session_manager.get_sessions_by_adapter_metadata.side_effect = [[], [mock_session]]

        result = await telegram_adapter._get_session_from_topic(mock_update)

        assert result == mock_session
        assert mock_session_manager.get_sessions_by_adapter_metadata.call_count == 2


class TestCommandHandlers:
    """Tests for command handler methods."""

    @pytest.mark.asyncio
    async def test_handle_cancel(self, telegram_adapter, mock_update):
        """Test /cancel command handler."""
        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_cancel(mock_update, MagicMock())

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "cancel"

    @pytest.mark.asyncio
    async def test_handle_cancel2x(self, telegram_adapter, mock_update):
        """Test /cancel2x command handler."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_cancel2x(mock_update, MagicMock())

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "cancel2x"

    @pytest.mark.asyncio
    async def test_handle_escape(self, telegram_adapter, mock_update):
        """Test /escape command handler passes arguments through."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        mock_context = MagicMock()
        mock_context.args = [":q"]

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_escape(mock_update, mock_context)

                mock_emit.assert_called_once_with(
                    "escape",
                    [":q"],
                    {
                        "adapter_type": "telegram",
                        "session_id": "test-session",
                        "user_id": mock_update.effective_user.id,
                        "message_id": mock_update.effective_message.message_id,
                    },
                )

    @pytest.mark.asyncio
    async def test_handle_escape2x(self, telegram_adapter, mock_update):
        """Test /escape2x command handler passes arguments through."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        mock_context = MagicMock()
        mock_context.args = [":wq"]

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_escape2x(mock_update, mock_context)

                mock_emit.assert_called_once_with(
                    "escape2x",
                    [":wq"],
                    {
                        "adapter_type": "telegram",
                        "session_id": "test-session",
                        "user_id": mock_update.effective_user.id,
                        "message_id": mock_update.effective_message.message_id,
                    },
                )


    @pytest.mark.asyncio
    async def test_handle_list_sessions(self, telegram_adapter, mock_update):
        """Test /list_sessions command handler."""
        with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
            await telegram_adapter._handle_list_sessions(mock_update, MagicMock())

            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][0] == "list-sessions"

    @pytest.mark.asyncio
    async def test_handle_new_session(self, telegram_adapter, mock_update):
        """Test /new_session command handler."""
        # Mock context with args
        mock_context = MagicMock()
        mock_context.args = ["Test", "Session"]

        with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
            await telegram_adapter._handle_new_session(mock_update, mock_context)

            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][0] == "new-session"
            assert call_args[0][1] == ["Test", "Session"]

    @pytest.mark.asyncio
    async def test_command_with_no_session_returns_early(self, telegram_adapter, mock_update):
        """Test command handler returns early when no session found."""
        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=None):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_cancel(mock_update, MagicMock())

                # Should not emit command when no session
                mock_emit.assert_not_called()


class TestMessaging:
    """Tests for message sending/editing methods."""

    @pytest.mark.asyncio
    async def test_send_message_not_started(self, telegram_adapter):
        """Test send_message raises when not started."""
        with pytest.raises(AdapterError, match="not started"):
            await telegram_adapter.send_message("session-123", "test message")

    @pytest.mark.asyncio
    async def test_send_message_success(self, telegram_adapter, mock_session_manager):
        """Test successful message send."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.send_message = AsyncMock(return_value=MagicMock(message_id=456))

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session.return_value = mock_session

        result = await telegram_adapter.send_message("session-123", "test message")

        assert result == "456"
        telegram_adapter.app.bot.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_edit_message_success(self, telegram_adapter, mock_session_manager):
        """Test successful message edit."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock()

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session.return_value = mock_session

        result = await telegram_adapter.edit_message("session-123", "789", "updated text")

        assert result is True
        telegram_adapter.app.bot.edit_message_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_message_success(self, telegram_adapter):
        """Test successful message deletion."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.delete_message = AsyncMock()

        result = await telegram_adapter.delete_message("session-123", "789")

        assert result is True
        telegram_adapter.app.bot.delete_message.assert_called_once()


class TestChannelManagement:
    """Tests for channel (topic) management methods."""

    @pytest.mark.asyncio
    async def test_create_channel_success(self, telegram_adapter):
        """Test successful channel creation."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        mock_topic = MagicMock()
        mock_topic.message_thread_id = 12345
        telegram_adapter.app.bot.create_forum_topic = AsyncMock(return_value=mock_topic)

        result = await telegram_adapter.create_channel("session-123", "Test Topic")

        assert result == "12345"
        telegram_adapter.app.bot.create_forum_topic.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_channel_title_success(self, telegram_adapter):
        """Test successful channel title update."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_forum_topic = AsyncMock()

        result = await telegram_adapter.update_channel_title("123", "New Title")

        assert result is True
        telegram_adapter.app.bot.edit_forum_topic.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_channel_success(self, telegram_adapter):
        """Test successful channel deletion."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.delete_forum_topic = AsyncMock()

        result = await telegram_adapter.delete_channel("123")

        assert result is True
        telegram_adapter.app.bot.delete_forum_topic.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_channel_status(self, telegram_adapter, mock_session_manager):
        """Test setting channel status with emoji."""
        # Mock session
        mock_session = MagicMock()
        mock_session.title = "Test Session"
        mock_session.computer_name = "TestPC"
        mock_session_manager.get_sessions_by_adapter_metadata.return_value = [mock_session]

        # Mock update_channel_title
        with patch.object(telegram_adapter, 'update_channel_title', return_value=True) as mock_update:
            result = await telegram_adapter.set_channel_status("123", "active")

            assert result is True
            mock_update.assert_called_once()
            # Check that emoji is in the title
            call_args = mock_update.call_args
            assert "🟢" in call_args[0][1]  # active emoji


class TestTextMessageHandling:
    """Tests for text message handling."""

    @pytest.mark.asyncio
    async def test_handle_text_message(self, telegram_adapter, mock_update):
        """Test text message handling."""
        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_message', new_callable=AsyncMock) as mock_emit:
                mock_update.effective_message.text = "ls -la"
                await telegram_adapter._handle_text_message(mock_update, MagicMock())

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "test-session"
                assert call_args[0][1] == "ls -la"

    @pytest.mark.asyncio
    async def test_handle_text_message_no_session(self, telegram_adapter, mock_update):
        """Test text message with no session returns early."""
        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=None):
            with patch.object(telegram_adapter, '_emit_message', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_text_message(mock_update, MagicMock())

                # Should not emit message when no session
                mock_emit.assert_not_called()


class TestCdCommand:
    """Tests for /cd command handler."""

    @pytest.mark.asyncio
    async def test_handle_cd_with_valid_directory(self, telegram_adapter, mock_update):
        """Test /cd command with directory in trusted_dirs."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        telegram_adapter.trusted_dirs = ["/tmp", "/home/user"]

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                mock_context = MagicMock()
                mock_context.args = ["/tmp"]

                await telegram_adapter._handle_cd(mock_update, mock_context)

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "cd"
                assert call_args[0][1] == ["/tmp"]

    @pytest.mark.asyncio
    async def test_handle_cd_with_any_directory(self, telegram_adapter, mock_update):
        """Test /cd command with any directory path."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        telegram_adapter.trusted_dirs = ["/tmp"]

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                mock_context = MagicMock()
                mock_context.args = ["/etc"]  # Any path is emitted to daemon

                await telegram_adapter._handle_cd(mock_update, mock_context)

                # Should emit command (validation happens in daemon)
                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "cd"
                assert call_args[0][1] == ["/etc"]

    @pytest.mark.asyncio
    async def test_handle_cd_no_args(self, telegram_adapter, mock_update):
        """Test /cd command without arguments shows directory selector."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        telegram_adapter.trusted_dirs = ["/tmp", "/home/user"]
        mock_update.effective_message.reply_text = AsyncMock()

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                mock_context = MagicMock()
                mock_context.args = []

                await telegram_adapter._handle_cd(mock_update, mock_context)

                # Should NOT emit command
                mock_emit.assert_not_called()
                # Should send directory selector
                mock_update.effective_message.reply_text.assert_called_once()


class TestClaudeCommand:
    """Tests for /claude command handler."""

    @pytest.mark.asyncio
    async def test_handle_claude(self, telegram_adapter, mock_update):
        """Test /claude command handler."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                mock_context = MagicMock()

                await telegram_adapter._handle_claude(mock_update, mock_context)

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "claude"
                assert call_args[0][1] == []  # Claude command takes no args


class TestRenameCommand:
    """Tests for /rename command handler."""

    @pytest.mark.asyncio
    async def test_handle_rename_with_title(self, telegram_adapter, mock_update):
        """Test /rename command with title."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                mock_context = MagicMock()
                mock_context.args = ["New", "Title"]

                await telegram_adapter._handle_rename(mock_update, mock_context)

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "rename"
                assert call_args[0][1] == ["New", "Title"]

    @pytest.mark.asyncio
    async def test_handle_rename_no_args(self, telegram_adapter, mock_update):
        """Test /rename command without arguments."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        mock_update.effective_message.reply_text = AsyncMock()

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                mock_context = MagicMock()
                mock_context.args = []

                await telegram_adapter._handle_rename(mock_update, mock_context)

                # Should NOT emit command
                mock_emit.assert_not_called()
                # Should send usage message
                mock_update.effective_message.reply_text.assert_called_once()


class TestCallbackQuery:
    """Tests for callback query handler."""

    @pytest.mark.asyncio
    async def test_handle_callback_query_cd(self, telegram_adapter, mock_session_manager):
        """Test callback query for cd command."""
        # Mock callback query
        mock_query = MagicMock()
        mock_query.data = "cd:/tmp/test"
        mock_query.message = MagicMock()
        mock_query.message.message_thread_id = 123
        mock_query.answer = AsyncMock()
        mock_query.edit_message_text = AsyncMock()

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = "test-session"
        mock_session_manager.get_sessions_by_adapter_metadata.return_value = [mock_session]

        # Mock update
        mock_update = MagicMock()
        mock_update.callback_query = mock_query

        with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
            await telegram_adapter._handle_callback_query(mock_update, MagicMock())

            mock_query.answer.assert_called_once()
            mock_emit.assert_called_once()
            call_args = mock_emit.call_args
            assert call_args[0][0] == "cd"
            assert call_args[0][1] == ["/tmp/test"]

    @pytest.mark.asyncio
    async def test_handle_callback_query_no_session(self, telegram_adapter, mock_session_manager):
        """Test callback query with no session."""
        # Mock callback query
        mock_query = MagicMock()
        mock_query.data = "cd:/tmp"
        mock_query.message = MagicMock()
        mock_query.message.message_thread_id = None  # No topic
        mock_query.answer = AsyncMock()

        # Mock update
        mock_update = MagicMock()
        mock_update.callback_query = mock_query

        with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
            await telegram_adapter._handle_callback_query(mock_update, MagicMock())

            mock_query.answer.assert_called_once()
            # Should NOT emit command when no session
            mock_emit.assert_not_called()


@pytest.mark.unit
class TestRateLimitHandling:
    """Tests for rate limit handling with retry."""

    @pytest.mark.asyncio
    async def test_edit_message_rate_limit_retries_and_succeeds(self, telegram_adapter, mock_session_manager):
        """Test that rate limit on edit sleeps and retries successfully."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        # First call raises rate limit, second succeeds
        telegram_adapter.app.bot.edit_message_text = AsyncMock(
            side_effect=[RetryAfter(retry_after=0.01), None]  # Use 0.01s for fast test
        )

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session.return_value = mock_session

        result = await telegram_adapter.edit_message("session-123", "789", "updated text")

        # Should return True after retry succeeds
        assert result is True
        # Should be called twice (initial + retry)
        assert telegram_adapter.app.bot.edit_message_text.call_count == 2

    @pytest.mark.asyncio
    async def test_edit_message_rate_limit_retries_and_fails(self, telegram_adapter, mock_session_manager):
        """Test that rate limit on edit sleeps, retries, and continues on failure."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        # Both calls raise rate limit
        telegram_adapter.app.bot.edit_message_text = AsyncMock(
            side_effect=RetryAfter(retry_after=0.01)
        )

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session.return_value = mock_session

        result = await telegram_adapter.edit_message("session-123", "789", "updated text")

        # Should return False after all retries exhausted (decorator raises, caught at line 322)
        assert result is False
        # Should be called 3 times (initial + 2 retries with max_retries=3)
        assert telegram_adapter.app.bot.edit_message_text.call_count == 3

    @pytest.mark.asyncio
    async def test_send_message_rate_limit_retries_and_succeeds(self, telegram_adapter, mock_session_manager):
        """Test that rate limit on send sleeps and retries successfully."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        # First call raises rate limit, second succeeds
        mock_message = MagicMock()
        mock_message.message_id = 999
        telegram_adapter.app.bot.send_message = AsyncMock(
            side_effect=[RetryAfter(retry_after=0.01), mock_message]
        )

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session.return_value = mock_session

        result = await telegram_adapter.send_message("session-123", "test message")

        # Should return message ID after retry succeeds
        assert result == "999"
        # Should be called twice (initial + retry)
        assert telegram_adapter.app.bot.send_message.call_count == 2

    @pytest.mark.asyncio
    async def test_send_message_rate_limit_retries_and_fails(self, telegram_adapter, mock_session_manager):
        """Test that rate limit on send sleeps, retries, and returns None on failure."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()

        # Both calls raise rate limit
        telegram_adapter.app.bot.send_message = AsyncMock(
            side_effect=RetryAfter(retry_after=0.01)
        )

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_session_manager.get_session.return_value = mock_session

        result = await telegram_adapter.send_message("session-123", "test message")

        # Should return None (message not sent, caught at line 278)
        assert result is None
        # Should be called 3 times (initial + 2 retries with max_retries=3)
        assert telegram_adapter.app.bot.send_message.call_count == 3


@pytest.mark.unit
class TestPlatformParameters:
    """Tests for platform-specific parameter methods."""

    def test_get_max_message_length(self, telegram_adapter):
        """Test Telegram max message length is 4096."""
        assert telegram_adapter.get_max_message_length() == 4096

    def test_get_ai_session_poll_interval(self, telegram_adapter):
        """Test AI session poll interval is faster than human mode."""
        interval = telegram_adapter.get_ai_session_poll_interval()
        assert interval == 0.5
        assert interval < 1.0  # Faster than typical human polling


@pytest.mark.unit
class TestReplyMarkup:
    """Tests for inline keyboard reply_markup handling."""

    @pytest.mark.asyncio
    async def test_send_message_with_reply_markup(self, telegram_adapter, mock_session_manager):
        """Test that send_message passes reply_markup from metadata."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.send_message = AsyncMock(return_value=MagicMock(message_id=123))

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "456"}
        mock_session_manager.get_session.return_value = mock_session

        # Create inline keyboard
        keyboard = [[InlineKeyboardButton("Test Button", callback_data="test:data")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Send message with reply_markup
        result = await telegram_adapter.send_message(
            "session-123", "test message", {"reply_markup": reply_markup}
        )

        assert result == "123"
        telegram_adapter.app.bot.send_message.assert_called_once()
        call_kwargs = telegram_adapter.app.bot.send_message.call_args[1]
        assert "reply_markup" in call_kwargs
        assert call_kwargs["reply_markup"] == reply_markup

    @pytest.mark.asyncio
    async def test_edit_message_with_reply_markup(self, telegram_adapter, mock_session_manager):
        """Test that edit_message passes reply_markup from metadata."""
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.edit_message_text = AsyncMock()

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "456"}
        mock_session_manager.get_session.return_value = mock_session

        # Create inline keyboard
        keyboard = [[InlineKeyboardButton("Download", callback_data="download:123")]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Edit message with reply_markup
        result = await telegram_adapter.edit_message(
            "session-123", "789", "updated text", {"reply_markup": reply_markup}
        )

        assert result is True
        telegram_adapter.app.bot.edit_message_text.assert_called_once()
        call_kwargs = telegram_adapter.app.bot.edit_message_text.call_args[1]
        assert "reply_markup" in call_kwargs
        assert call_kwargs["reply_markup"] == reply_markup

    @pytest.mark.asyncio
    async def test_send_message_without_reply_markup(self, telegram_adapter, mock_session_manager):
        """Test that send_message works without reply_markup."""
        # Mock app and bot
        telegram_adapter.app = MagicMock()
        telegram_adapter.app.bot = MagicMock()
        telegram_adapter.app.bot.send_message = AsyncMock(return_value=MagicMock(message_id=123))

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_metadata = {"channel_id": "456"}
        mock_session_manager.get_session.return_value = mock_session

        # Send message without reply_markup
        result = await telegram_adapter.send_message("session-123", "test message")

        assert result == "123"
        telegram_adapter.app.bot.send_message.assert_called_once()
        call_kwargs = telegram_adapter.app.bot.send_message.call_args[1]
        # reply_markup should be None
        assert call_kwargs.get("reply_markup") is None
