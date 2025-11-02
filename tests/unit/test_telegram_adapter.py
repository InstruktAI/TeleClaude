"""Unit tests for telegram_adapter.py."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from telegram import Update, User, Message, Chat
from telegram.ext import ContextTypes

from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.adapters.base_adapter import AdapterError


@pytest.fixture
def mock_config():
    """Mock Telegram adapter configuration."""
    return {
        "bot_token": "123456:ABC-DEF",
        "supergroup_id": -100123456789,
        "user_whitelist": [12345, 67890],
        "trusted_dirs": ["/tmp", "/home/user"]
    }


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
def telegram_adapter(mock_config, mock_session_manager, mock_daemon):
    """Create TelegramAdapter instance."""
    return TelegramAdapter(mock_config, mock_session_manager, mock_daemon)


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

    def test_init_with_config(self, mock_config, mock_session_manager, mock_daemon):
        """Test adapter initializes with config."""
        adapter = TelegramAdapter(mock_config, mock_session_manager, mock_daemon)

        assert adapter.bot_token == "123456:ABC-DEF"
        assert adapter.supergroup_id == -100123456789
        assert adapter.user_whitelist == [12345, 67890]
        assert adapter.trusted_dirs == ["/tmp", "/home/user"]

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
        """Test /escape command handler."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_escape(mock_update, MagicMock())

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "escape"

    @pytest.mark.asyncio
    async def test_handle_escape2x(self, telegram_adapter, mock_update):
        """Test /escape2x command handler."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_escape2x(mock_update, MagicMock())

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "escape2x"

    @pytest.mark.asyncio
    async def test_handle_exit(self, telegram_adapter, mock_update):
        """Test /exit command handler."""
        mock_session = MagicMock()
        mock_session.session_id = "test-session"

        with patch.object(telegram_adapter, '_get_session_from_topic', return_value=mock_session):
            with patch.object(telegram_adapter, '_emit_command', new_callable=AsyncMock) as mock_emit:
                await telegram_adapter._handle_exit(mock_update, MagicMock())

                mock_emit.assert_called_once()
                call_args = mock_emit.call_args
                assert call_args[0][0] == "exit"

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
