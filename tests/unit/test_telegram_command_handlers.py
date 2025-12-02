"""Unit tests for Telegram adapter command handlers.

These tests verify that command handlers correctly handle events with proper payloads.
This is the CRITICAL test layer that would have caught the "missing command field" bug.

NOTE: These tests are currently obsolete after the event system refactoring.
Individual command handler methods (_handle_list_sessions, etc.) were removed.
Commands now flow through _handle_user_input() → event system → daemon handlers.
TODO: Rewrite these tests to verify the new architecture or remove them.
"""

import pytest

pytestmark = pytest.mark.skip(reason="Command handlers refactored - tests need rewrite for new architecture")

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from telegram import Chat, Message, Update, User
from telegram.ext import ContextTypes

from teleclaude.adapters.telegram_adapter import TelegramAdapter
from teleclaude.config import TrustedDir
from teleclaude.core.events import TeleClaudeEvents


def create_mock_update(text: str, user_id: int, chat_id: int = -100123456789, message_thread_id: int | None = None):
    """Create a mock Telegram Update object."""
    update = Mock(spec=Update)

    # Mock user
    user = Mock(spec=User)
    user.id = user_id
    user.first_name = "Test"
    user.last_name = "User"
    user.username = "testuser"

    # Mock chat
    chat = Mock(spec=Chat)
    chat.id = chat_id
    chat.type = "supergroup"

    # Mock message
    message = Mock(spec=Message)
    message.text = text
    message.from_user = user
    message.chat = chat
    message.message_id = 999
    message.message_thread_id = message_thread_id

    update.effective_user = user
    update.effective_chat = chat
    update.effective_message = message

    return update


def create_mock_context(args: list[str] | None = None):
    """Create a mock Telegram context."""
    context = MagicMock(spec=ContextTypes.DEFAULT_TYPE)
    context.args = args or []
    return context


@pytest.fixture
def mock_adapter_client():
    """Create mock AdapterClient."""
    client = Mock()
    client.handle_event = AsyncMock()
    return client


@pytest.fixture
def telegram_adapter(mock_adapter_client, monkeypatch):
    """Create TelegramAdapter with mocked client."""
    # Mock environment variables
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:ABC-DEF")
    monkeypatch.setenv("TELEGRAM_SUPERGROUP_ID", "-100123456789")
    monkeypatch.setenv("TELEGRAM_USER_IDS", "12345,67890")

    with patch("teleclaude.adapters.telegram_adapter.config") as mock_config:
        mock_config.computer.name = "test_computer"
        mock_config.computer.default_working_dir = "/teleclaude"
        mock_config.computer.trusted_dirs = [TrustedDir(name="tmp", desc="temp files", path="/tmp")]
        # Mock get_all_trusted_dirs to return teleclaude folder + trusted_dirs
        mock_config.computer.get_all_trusted_dirs.return_value = [
            TrustedDir(name="teleclaude", desc="TeleClaude folder", path="/teleclaude"),
            TrustedDir(name="tmp", desc="temp files", path="/tmp"),
        ]

        adapter = TelegramAdapter(mock_adapter_client)
        adapter.user_whitelist = [12345, 67890]  # Authorized users
        adapter.is_master = True

        return adapter


class TestNewSessionCommand:
    """Test /new_session command handler."""

    @pytest.mark.asyncio
    async def test_emits_event_with_command_field(self, telegram_adapter, mock_adapter_client):
        """Test that /new_session emits event with 'command' field in payload.

        This is the test that would have caught the bug!
        """
        update = create_mock_update("/new_session My Session", user_id=12345)
        context = create_mock_context(args=["My", "Session"])

        await telegram_adapter._handle_new_session(update, context)

        # Verify event was emitted
        mock_adapter_client.handle_event.assert_called_once()

        # Extract call arguments
        call_kwargs = mock_adapter_client.handle_event.call_args.kwargs
        event = call_kwargs["event"]
        payload = call_kwargs["payload"]
        metadata = call_kwargs["metadata"]

        # CRITICAL ASSERTIONS - would have caught the bug
        assert event == TeleClaudeEvents.NEW_SESSION
        assert "command" in payload, "Payload must include 'command' field"
        assert payload["command"] == "new-session", "Command should use hyphens, not underscores"
        assert payload["args"] == ["My", "Session"]

        # Verify metadata (MessageMetadata dataclass)
        assert metadata.adapter_type == "telegram"
        # Note: user_id and chat_id are not fields in MessageMetadata
        # They would be in the Update object, not metadata

    @pytest.mark.asyncio
    async def test_unauthorized_user_does_not_handle_event(self, telegram_adapter, mock_adapter_client):
        """Test that unauthorized user cannot trigger command."""
        update = create_mock_update("/new_session Hacker Session", user_id=99999)  # Not in whitelist
        context = create_mock_context(args=["Hacker", "Session"])

        await telegram_adapter._handle_new_session(update, context)

        # Should NOT handle event
        mock_adapter_client.handle_event.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_args(self, telegram_adapter, mock_adapter_client):
        """Test /new_session with no arguments."""
        update = create_mock_update("/new_session", user_id=12345)
        context = create_mock_context(args=[])

        await telegram_adapter._handle_new_session(update, context)

        mock_adapter_client.handle_event.assert_called_once()
        payload = mock_adapter_client.handle_event.call_args.kwargs["payload"]

        assert payload["command"] == "new-session"
        assert payload["args"] == []


class TestListSessionsCommand:
    """Test /list_sessions command handler."""

    @pytest.mark.asyncio
    async def test_emits_event_with_command_field(self, telegram_adapter, mock_adapter_client):
        """Test /list_sessions emits correct event."""
        update = create_mock_update("/list_sessions", user_id=12345)
        context = create_mock_context(args=[])

        await telegram_adapter._handle_list_sessions(update, context)

        mock_adapter_client.handle_event.assert_called_once()
        call_kwargs = mock_adapter_client.handle_event.call_args.kwargs

        assert call_kwargs["event"] == TeleClaudeEvents.LIST_SESSIONS
        assert call_kwargs["payload"]["command"] == "list-sessions"
        assert call_kwargs["payload"]["args"] == []


class TestCancelCommand:
    """Test /cancel command handler."""

    @pytest.mark.asyncio
    async def test_emits_event_with_command_field(self, telegram_adapter, mock_adapter_client):
        """Test /cancel emits correct event with session context."""
        # Mock session lookup
        from teleclaude.core.models import Session

        mock_session = Session(
            session_id="test-123",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            adapter_metadata={"topic_id": "456"},
            title="Test",
        )

        with patch.object(telegram_adapter, "_get_session_from_topic", return_value=mock_session):
            update = create_mock_update("/cancel", user_id=12345, message_thread_id=456)
            context = create_mock_context(args=[])

            await telegram_adapter._handle_cancel(update, context)

            mock_adapter_client.handle_event.assert_called_once()
            call_kwargs = mock_adapter_client.handle_event.call_args.kwargs

            assert call_kwargs["event"] == TeleClaudeEvents.CANCEL
            assert call_kwargs["payload"]["command"] == "cancel"
            assert call_kwargs["payload"]["args"] == []
            assert call_kwargs["payload"]["session_id"] == "test-123"


class TestKeyCommands:
    """Test keyboard control commands."""

    @pytest.mark.asyncio
    async def test_key_up_emits_event_with_command(self, telegram_adapter, mock_adapter_client):
        """Test /key_up emits correct event."""
        from teleclaude.core.models import Session

        mock_session = Session(
            session_id="test-456",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            adapter_metadata={"topic_id": "789"},
            title="Test",
        )

        with patch.object(telegram_adapter, "_get_session_from_topic", return_value=mock_session):
            update = create_mock_update("/key_up 3", user_id=12345, message_thread_id=789)
            context = create_mock_context(args=["3"])

            await telegram_adapter._handle_key_up(update, context)

            mock_adapter_client.handle_event.assert_called_once()
            call_kwargs = mock_adapter_client.handle_event.call_args.kwargs

            assert call_kwargs["event"] == TeleClaudeEvents.KEY_UP
            assert call_kwargs["payload"]["command"] == "key-up"
            assert call_kwargs["payload"]["args"] == ["3"]
            assert call_kwargs["payload"]["session_id"] == "test-456"


class TestEventToCommandTranslation:
    """Test _event_to_command helper method."""

    def test_converts_underscores_to_hyphens(self, telegram_adapter):
        """Test event names are converted to command format."""
        assert telegram_adapter._event_to_command("new_session") == "new-session"
        assert telegram_adapter._event_to_command("list_sessions") == "list-sessions"
        assert telegram_adapter._event_to_command("key_up") == "key-up"
        assert telegram_adapter._event_to_command("key_down") == "key-down"
        assert telegram_adapter._event_to_command("shift_tab") == "shift-tab"

    def test_handles_no_underscores(self, telegram_adapter):
        """Test event names without underscores pass through."""
        assert telegram_adapter._event_to_command("cancel") == "cancel"
        assert telegram_adapter._event_to_command("kill") == "kill"
        assert telegram_adapter._event_to_command("cancel2x") == "cancel2x"


class TestClaudeCommands:
    """Test Claude Code integration commands."""

    @pytest.mark.asyncio
    async def test_claude_command_emits_event(self, telegram_adapter, mock_adapter_client):
        """Test /claude emits correct event."""
        from teleclaude.core.models import Session

        mock_session = Session(
            session_id="test-789",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            adapter_metadata={"topic_id": "111"},
            title="Test",
        )

        with patch.object(telegram_adapter, "_get_session_from_topic", return_value=mock_session):
            update = create_mock_update("/claude", user_id=12345, message_thread_id=111)
            context = create_mock_context(args=[])

            await telegram_adapter._handle_claude(update, context)

            mock_adapter_client.handle_event.assert_called_once()
            call_kwargs = mock_adapter_client.handle_event.call_args.kwargs

            assert call_kwargs["event"] == TeleClaudeEvents.CLAUDE
            assert call_kwargs["payload"]["command"] == "claude"
            assert call_kwargs["payload"]["args"] == []
            assert call_kwargs["payload"]["session_id"] == "test-789"

    @pytest.mark.asyncio
    async def test_claude_resume_emits_event(self, telegram_adapter, mock_adapter_client):
        """Test /claude_resume emits correct event."""
        from teleclaude.core.models import Session

        mock_session = Session(
            session_id="test-012",
            computer_name="test",
            tmux_session_name="test-tmux",
            origin_adapter="telegram",
            adapter_metadata={"topic_id": "222"},
            title="Test",
        )

        with patch.object(telegram_adapter, "_get_session_from_topic", return_value=mock_session):
            update = create_mock_update("/claude_resume", user_id=12345, message_thread_id=222)
            context = create_mock_context(args=[])

            await telegram_adapter._handle_claude_resume(update, context)

            mock_adapter_client.handle_event.assert_called_once()
            call_kwargs = mock_adapter_client.handle_event.call_args.kwargs

            assert call_kwargs["event"] == TeleClaudeEvents.CLAUDE_RESUME
            assert call_kwargs["payload"]["command"] == "claude-resume"
            assert call_kwargs["payload"]["args"] == []
            assert call_kwargs["payload"]["session_id"] == "test-012"
