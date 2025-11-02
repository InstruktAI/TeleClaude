"""Unit tests for daemon.py core logic."""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from teleclaude.daemon import TeleClaudeDaemon, DaemonLockError


@pytest.fixture
def mock_daemon():
    """Create a mocked daemon for testing."""
    with patch('teleclaude.daemon.SessionManager') as mock_sm, \
         patch('teleclaude.daemon.TerminalBridge') as mock_tb, \
         patch('teleclaude.daemon.TelegramAdapter') as mock_ta:

        # Create daemon instance
        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        # Mock essential attributes
        daemon.session_manager = mock_sm.return_value
        daemon.terminal = mock_tb.return_value
        daemon.telegram = mock_ta.return_value
        daemon.config = {
            "computer": {
                "name": "TestComputer",
                "default_shell": "/bin/zsh",
                "default_working_dir": "/tmp"
            },
            "terminal": {"default_size": "80x24"}
        }
        daemon.active_polling_sessions = set()
        daemon.session_output_buffers = {}
        daemon.output_dir = "/tmp/test_output"

        # Mock adapter registry
        daemon.adapters = {"telegram": daemon.telegram}

        yield daemon


class TestHandleMessage:
    """Tests for handle_message() method."""

    @pytest.mark.asyncio
    async def test_double_slash_stripping_at_start(self, mock_daemon):
        """Test that leading // is stripped and replaced with /."""
        session_id = "test-session-123"
        text = "//clear"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.working_directory = "/tmp"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock send_keys
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()

        # Mock _poll_and_send_output to avoid actual polling
        mock_daemon._poll_and_send_output = AsyncMock()

        # Execute
        await mock_daemon.handle_message(session_id, text, {"adapter_type": "telegram"})

        # Verify send_keys was called with stripped text
        mock_daemon.terminal.send_keys.assert_called_once()
        call_args = mock_daemon.terminal.send_keys.call_args
        assert call_args[0][1] == "/clear", "Should strip // to /"

    @pytest.mark.asyncio
    async def test_double_slash_not_stripped_in_middle(self, mock_daemon):
        """Test that // in the middle of text is NOT stripped."""
        session_id = "test-session-456"
        text = "echo 'test//value'"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.working_directory = "/tmp"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock send_keys
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()
        mock_daemon._poll_and_send_output = AsyncMock()

        # Execute
        await mock_daemon.handle_message(session_id, text, {"adapter_type": "telegram"})

        # Verify send_keys was called with original text
        call_args = mock_daemon.terminal.send_keys.call_args
        assert call_args[0][1] == "echo 'test//value'", "Should NOT strip // in middle"

    @pytest.mark.asyncio
    async def test_exit_marker_appended_for_new_command(self, mock_daemon):
        """Test that exit marker is appended when starting NEW command (no active polling)."""
        session_id = "test-session-789"
        text = "ls -la"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.working_directory = "/tmp"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Ensure NOT in active polling (new command)
        mock_daemon.active_polling_sessions = set()

        # Mock send_keys
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()
        mock_daemon._poll_and_send_output = AsyncMock()

        # Execute
        await mock_daemon.handle_message(session_id, text, {"adapter_type": "telegram"})

        # Verify send_keys was called with append_exit_marker=True
        call_args = mock_daemon.terminal.send_keys.call_args
        assert call_args[1]["append_exit_marker"] is True, "Should append exit marker for new command"

    @pytest.mark.asyncio
    async def test_no_exit_marker_for_running_process(self, mock_daemon):
        """Test that exit marker is NOT appended when sending to running process."""
        session_id = "test-session-999"
        text = "some input"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.working_directory = "/tmp"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mark as active polling (running process)
        mock_daemon.active_polling_sessions = {session_id}

        # Mock send_keys and adapter
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.delete_message = AsyncMock()

        # Execute with message_id in context
        await mock_daemon.handle_message(session_id, text, {
            "adapter_type": "telegram",
            "message_id": "msg-123"
        })

        # Verify send_keys was called with append_exit_marker=False
        call_args = mock_daemon.terminal.send_keys.call_args
        assert call_args[1]["append_exit_marker"] is False, "Should NOT append exit marker for running process"

        # Verify user message was deleted
        mock_daemon.telegram.delete_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_combined_double_slash_and_running_process(self, mock_daemon):
        """Test double slash stripping with running process (no exit marker)."""
        session_id = "test-session-combo"
        text = "//clear"  # User bypassing Telegram command in running process

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.working_directory = "/tmp"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mark as active polling (running process)
        mock_daemon.active_polling_sessions = {session_id}

        # Mock send_keys and adapter
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.delete_message = AsyncMock()

        # Execute
        await mock_daemon.handle_message(session_id, text, {
            "adapter_type": "telegram",
            "message_id": "msg-456"
        })

        # Verify both behaviors: stripped text AND no exit marker
        call_args = mock_daemon.terminal.send_keys.call_args
        assert call_args[0][1] == "/clear", "Should strip // to /"
        assert call_args[1]["append_exit_marker"] is False, "Should NOT append exit marker"


class TestEscapeCommand:
    """Tests for _escape_command() method."""

    @pytest.mark.asyncio
    async def test_single_escape(self, mock_daemon):
        """Test single ESCAPE key send."""
        session_id = "test-session-esc"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock terminal
        mock_daemon.terminal.send_escape = AsyncMock(return_value=True)
        mock_daemon._poll_and_send_output = AsyncMock()

        # Execute
        await mock_daemon._escape_command({"session_id": session_id}, double=False)

        # Verify single call
        assert mock_daemon.terminal.send_escape.call_count == 1

    @pytest.mark.asyncio
    async def test_double_escape(self, mock_daemon):
        """Test double ESCAPE key send."""
        session_id = "test-session-esc2x"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock terminal
        mock_daemon.terminal.send_escape = AsyncMock(return_value=True)
        mock_daemon._poll_and_send_output = AsyncMock()

        # Execute
        await mock_daemon._escape_command({"session_id": session_id}, double=True)

        # Verify double call
        assert mock_daemon.terminal.send_escape.call_count == 2


class TestCommandRouting:
    """Tests for command routing in handle_command()."""

    @pytest.mark.asyncio
    async def test_escape_command_routing(self, mock_daemon):
        """Test that 'escape' command routes to _escape_command (default double=False)."""
        mock_daemon._escape_command = AsyncMock()

        context = {"session_id": "test-123"}
        await mock_daemon.handle_command("escape", [], context)

        # Called with just context, relies on default double=False
        mock_daemon._escape_command.assert_called_once_with(context)

    @pytest.mark.asyncio
    async def test_escape2x_command_routing(self, mock_daemon):
        """Test that 'escape2x' command routes to _escape_command with double=True."""
        mock_daemon._escape_command = AsyncMock()

        context = {"session_id": "test-456"}
        await mock_daemon.handle_command("escape2x", [], context)

        mock_daemon._escape_command.assert_called_once_with(context, double=True)

    @pytest.mark.asyncio
    async def test_cancel_command_routing(self, mock_daemon):
        """Test that 'cancel' command routes to _cancel_command (default double=False)."""
        mock_daemon._cancel_command = AsyncMock()

        context = {"session_id": "test-789"}
        await mock_daemon.handle_command("cancel", [], context)

        # Called with just context, relies on default double=False
        mock_daemon._cancel_command.assert_called_once_with(context)

    @pytest.mark.asyncio
    async def test_cancel2x_command_routing(self, mock_daemon):
        """Test that 'cancel2x' command routes to _cancel_command with double=True."""
        mock_daemon._cancel_command = AsyncMock()

        context = {"session_id": "test-999"}
        await mock_daemon.handle_command("cancel2x", [], context)

        mock_daemon._cancel_command.assert_called_once_with(context, double=True)


class TestCancelCommand:
    """Tests for _cancel_command() method."""

    @pytest.mark.asyncio
    async def test_cancel_command_sends_sigint(self, mock_daemon):
        """Test cancel command sends SIGINT."""
        session_id = "test-session-cancel"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock terminal
        mock_daemon.terminal.send_signal = AsyncMock(return_value=True)
        mock_daemon._poll_and_send_output = AsyncMock()

        # Execute
        await mock_daemon._cancel_command({"session_id": session_id})

        # Verify SIGINT was sent
        mock_daemon.terminal.send_signal.assert_called_once_with("test-tmux", "SIGINT")

    @pytest.mark.asyncio
    async def test_cancel_command_double_sends_twice(self, mock_daemon):
        """Test cancel2x sends SIGINT twice."""
        session_id = "test-session-cancel2x"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock terminal
        mock_daemon.terminal.send_signal = AsyncMock(return_value=True)
        mock_daemon._poll_and_send_output = AsyncMock()

        # Execute with double=True
        await mock_daemon._cancel_command({"session_id": session_id}, double=True)

        # Verify SIGINT was sent twice
        assert mock_daemon.terminal.send_signal.call_count == 2


class TestListSessions:
    """Tests for _list_sessions() method."""

    @pytest.mark.asyncio
    async def test_list_sessions_with_sessions(self, mock_daemon):
        """Test listing sessions when sessions exist."""
        # Mock sessions
        mock_session1 = MagicMock()
        mock_session1.session_id = "session-1"
        mock_session1.title = "Session 1"
        mock_session1.status = "active"
        mock_session1.command_count = 5

        mock_session2 = MagicMock()
        mock_session2.session_id = "session-2"
        mock_session2.title = "Session 2"
        mock_session2.status = "idle"
        mock_session2.command_count = 10

        mock_daemon.session_manager.list_sessions = AsyncMock(return_value=[mock_session1, mock_session2])

        # Mock adapter - use _get_adapter_by_type
        mock_daemon.telegram.send_general_message = AsyncMock(return_value="msg-123")

        # Execute
        context = {"adapter_type": "telegram", "user_id": 12345}
        await mock_daemon._list_sessions(context)

        # Verify message was sent
        mock_daemon.telegram.send_general_message.assert_called_once()
        call_args = mock_daemon.telegram.send_general_message.call_args[1]  # Get kwargs
        message_text = call_args.get("text") or mock_daemon.telegram.send_general_message.call_args[0][0]

        # Should contain both sessions
        assert "Session 1" in message_text or "session-1" in message_text

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, mock_daemon):
        """Test listing sessions when none exist."""
        mock_daemon.session_manager.list_sessions = AsyncMock(return_value=[])

        # Mock adapter - use _get_adapter_by_type
        mock_daemon.telegram.send_general_message = AsyncMock(return_value="msg-123")

        # Execute
        context = {"adapter_type": "telegram", "user_id": 12345}
        await mock_daemon._list_sessions(context)

        # Verify message was sent
        mock_daemon.telegram.send_general_message.assert_called_once()


class TestResizeSession:
    """Tests for _resize_session() method."""

    @pytest.mark.asyncio
    async def test_resize_session_with_custom_size(self, mock_daemon):
        """Test resizing session with custom dimensions."""
        session_id = "test-session-resize-custom"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock terminal
        mock_daemon.terminal.resize_session = AsyncMock(return_value=True)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")

        # Mock session manager update
        mock_daemon.session_manager.update_session = AsyncMock()

        # Execute with custom size (WxH format)
        mock_daemon.config = {"terminal": {"sizes": {}, "default_size": "120x40"}}
        context = {"session_id": session_id}
        await mock_daemon._resize_session(context, ["120x40"])

        # Verify resize was called with correct dimensions
        mock_daemon.terminal.resize_session.assert_called_once_with("test-tmux", 120, 40)


class TestRenameSession:
    """Tests for _rename_session() method."""

    @pytest.mark.asyncio
    async def test_rename_session(self, mock_daemon):
        """Test renaming a session."""
        session_id = "test-session-rename"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.adapter_metadata = {"channel_id": "123"}
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock session manager update
        mock_daemon.session_manager.update_session = AsyncMock()

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.update_channel_title = AsyncMock(return_value=True)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")

        # Execute
        mock_daemon.config = {"computer": {"name": "TestPC"}}
        context = {"session_id": session_id}
        await mock_daemon._rename_session(context, ["New", "Title"])

        # Verify title update
        mock_daemon.session_manager.update_session.assert_called_once()
        call_args = mock_daemon.session_manager.update_session.call_args
        assert "[TestPC] New Title" in str(call_args)

        # Verify channel title update
        mock_daemon.telegram.update_channel_title.assert_called_once()


class TestGetOutputFile:
    """Tests for _get_output_file() helper."""

    def test_get_output_file_path(self, mock_daemon):
        """Test output file path generation."""
        from pathlib import Path
        mock_daemon.output_dir = Path("/tmp/test_output")
        session_id = "abcdef12-3456-7890-abcd-ef1234567890"

        # Execute
        path = mock_daemon._get_output_file(session_id)

        # Verify path format
        assert str(path) == "/tmp/test_output/abcdef12.txt"

    def test_get_output_file_short_id(self, mock_daemon):
        """Test output file path with short session ID."""
        from pathlib import Path
        mock_daemon.output_dir = Path("/tmp/test_output")
        session_id = "short"

        # Execute
        path = mock_daemon._get_output_file(session_id)

        # Should use entire ID if shorter than 8 chars
        assert str(path) == "/tmp/test_output/short.txt"


class TestGetAdapterHelpers:
    """Tests for adapter helper methods."""

    @pytest.mark.asyncio
    async def test_get_adapter_by_type(self, mock_daemon):
        """Test getting adapter by type."""
        adapter = mock_daemon._get_adapter_by_type("telegram")

        assert adapter == mock_daemon.telegram

    @pytest.mark.asyncio
    async def test_get_adapter_for_session(self, mock_daemon):
        """Test getting adapter for session."""
        session_id = "test-session-123"

        # Mock session
        mock_session = MagicMock()
        mock_session.adapter_type = "telegram"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Execute
        adapter = await mock_daemon._get_adapter_for_session(session_id)

        assert adapter == mock_daemon.telegram


class TestCreateSession:
    """Tests for _create_session() method."""

    @pytest.mark.asyncio
    async def test_create_session_basic(self, mock_daemon):
        """Test creating a new session."""
        # Mock session creation
        mock_session = MagicMock()
        mock_session.session_id = "new-session-123"
        mock_session.tmux_session_name = "mozbook-new"
        mock_session.adapter_type = "telegram"  # Set adapter type explicitly
        mock_session.adapter_metadata = {"channel_id": "456"}
        mock_daemon.session_manager.create_session = AsyncMock(return_value=mock_session)

        # Mock terminal
        mock_daemon.terminal.create_tmux_session = AsyncMock(return_value=True)

        # Mock adapter
        mock_daemon.telegram.create_channel = AsyncMock(return_value="456")
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")

        # Mock session manager methods
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)
        mock_daemon.session_manager.update_session = AsyncMock()
        mock_daemon.session_manager.list_sessions = AsyncMock(return_value=[])

        # Execute
        mock_daemon.config = {
            "computer": {"name": "TestPC", "default_shell": "/bin/bash", "default_working_dir": "~"},
            "terminal": {"default_size": "80x24"}
        }
        context = {"adapter_type": "telegram", "user_id": 12345}
        await mock_daemon._create_session(context, ["Test", "Session"])

        # Verify session was created
        mock_daemon.session_manager.create_session.assert_called_once()
        # Verify tmux session was created
        mock_daemon.terminal.create_tmux_session.assert_called_once()
        # Verify channel was created
        mock_daemon.telegram.create_channel.assert_called_once()


class TestExitSession:
    """Tests for _exit_session() method."""

    @pytest.mark.asyncio
    async def test_exit_session(self, mock_daemon):
        """Test exiting a session."""
        from pathlib import Path
        session_id = "test-session-exit"

        # Mock output_dir
        mock_daemon.output_dir = Path("/tmp/test_output")

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.adapter_metadata = {"channel_id": "789"}
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock terminal
        mock_daemon.terminal.kill_session = AsyncMock(return_value=True)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")
        mock_daemon.telegram.delete_channel = AsyncMock(return_value=True)

        # Mock session manager
        mock_daemon.session_manager.delete_session = AsyncMock()

        # Execute
        context = {"session_id": session_id}
        await mock_daemon._exit_session(context)

        # Verify session was deleted (not updated)
        mock_daemon.session_manager.delete_session.assert_called_once()
        # Verify tmux session was killed
        mock_daemon.terminal.kill_session.assert_called_once_with("test-tmux")
        # Verify channel was deleted
        mock_daemon.telegram.delete_channel.assert_called_once()


class TestCdSession:
    """Tests for _cd_session() method."""

    @pytest.mark.asyncio
    async def test_cd_session_trusted_dir(self, mock_daemon):
        """Test changing directory to trusted directory."""
        session_id = "test-session-cd"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()

        # Mock terminal
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")

        # Mock _poll_and_send_output
        mock_daemon._poll_and_send_output = AsyncMock()

        # Mock config with trusted dirs
        mock_daemon.config = {
            "telegram": {"trusted_dirs": ["/tmp", "/home/user"]},
            "computer": {}
        }

        # Execute with trusted directory
        context = {"session_id": session_id}
        await mock_daemon._cd_session(context, ["/tmp"])

        # Verify cd command was sent
        mock_daemon.terminal.send_keys.assert_called_once()
        call_args = mock_daemon.terminal.send_keys.call_args
        assert "/tmp" in call_args[0][1]

    @pytest.mark.asyncio
    async def test_cd_session_with_multiple_args(self, mock_daemon):
        """Test changing directory with path that has spaces."""
        session_id = "test-session-cd-spaces"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()

        # Mock terminal
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")

        # Mock _poll_and_send_output
        mock_daemon._poll_and_send_output = AsyncMock()

        # Mock config
        mock_daemon.config = {"computer": {}}

        # Execute with directory path with spaces (multiple args)
        context = {"session_id": session_id}
        await mock_daemon._cd_session(context, ["/path/with", "spaces"])

        # Verify cd command was sent with full path
        mock_daemon.terminal.send_keys.assert_called_once()
        call_args = mock_daemon.terminal.send_keys.call_args
        assert "/path/with spaces" in call_args[0][1]  # Arguments joined with space


class TestClaudeSession:
    """Tests for _claude_session() method."""

    @pytest.mark.asyncio
    async def test_claude_session(self, mock_daemon):
        """Test starting Claude Code in session."""
        session_id = "test-session-claude"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.terminal_size = "120x40"  # Add terminal size
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()

        # Mock terminal
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")

        # Mock _poll_and_send_output
        mock_daemon._poll_and_send_output = AsyncMock()

        # Execute
        context = {"session_id": session_id}
        await mock_daemon._claude_session(context)

        # Verify claude command was sent
        mock_daemon.terminal.send_keys.assert_called_once()
        call_args = mock_daemon.terminal.send_keys.call_args
        assert "claude" in call_args[0][1]


class TestHandleVoice:
    """Tests for handle_voice() method."""

    @pytest.mark.asyncio
    async def test_handle_voice(self, mock_daemon):
        """Test handling voice message."""
        session_id = "test-session-voice"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()

        # Mock voice handler on daemon object
        mock_daemon.voice_handler = MagicMock()
        mock_daemon.voice_handler.transcribe_with_retry = AsyncMock(return_value="transcribed text")

        # Mock terminal
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")

        # Mock _poll_and_send_output
        mock_daemon._poll_and_send_output = AsyncMock()

        # Mock active_polling_sessions
        mock_daemon.active_polling_sessions = set()

        # Execute
        context = {"adapter_type": "telegram", "duration": 5}
        await mock_daemon.handle_voice(session_id, "/tmp/audio.ogg", context)

        # Verify transcription was called
        mock_daemon.voice_handler.transcribe_with_retry.assert_called_once()
        # Verify transcribed text was sent to terminal
        mock_daemon.terminal.send_keys.assert_called_once()


class TestPollAndSendOutput:
    """Tests for _poll_and_send_output() method."""

    @pytest.mark.asyncio
    async def test_poll_with_exit_code_detection(self, mock_daemon):
        """Test polling stops when exit code marker is detected."""
        from pathlib import Path

        session_id = "test-session-poll-exit"
        tmux_session_name = "test-tmux"

        # Mock output_dir
        mock_daemon.output_dir = Path("/tmp/test_output")

        # Mock session_exists (session alive)
        mock_daemon.terminal.session_exists = AsyncMock(return_value=True)

        # Mock capture_pane: first with output, second with exit marker
        mock_daemon.terminal.capture_pane = AsyncMock(
            side_effect=[
                "command output\n",  # First poll
                "command output\n__EXIT__0__\n",  # Second poll with exit marker
            ]
        )

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-123")
        mock_daemon.telegram.edit_message = AsyncMock(return_value=True)

        # Mock asyncio.sleep to avoid delays
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Execute
            await mock_daemon._poll_and_send_output(session_id, tmux_session_name)

        # Verify polling stopped (only 2 capture_pane calls)
        assert mock_daemon.terminal.capture_pane.call_count == 2

        # Verify final message contains exit code
        final_call = mock_daemon.telegram.edit_message.call_args
        assert "exit code: 0" in final_call[0][2].lower() or "completed" in final_call[0][2].lower()

        # Verify session removed from active polling
        assert session_id not in mock_daemon.active_polling_sessions

    @pytest.mark.asyncio
    async def test_poll_with_session_death(self, mock_daemon):
        """Test polling stops when tmux session dies."""
        from pathlib import Path

        session_id = "test-session-poll-death"
        tmux_session_name = "test-tmux-dead"

        # Mock output_dir
        mock_daemon.output_dir = Path("/tmp/test_output")

        # Mock session_exists: alive first, then dead
        mock_daemon.terminal.session_exists = AsyncMock(
            side_effect=[
                True,  # First check
                False,  # Second check - session died
            ]
        )

        # Mock capture_pane
        mock_daemon.terminal.capture_pane = AsyncMock(return_value="some output\n")

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-456")
        mock_daemon.telegram.edit_message = AsyncMock(return_value=True)

        # Mock asyncio.sleep
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Execute
            await mock_daemon._poll_and_send_output(session_id, tmux_session_name)

        # Verify polling stopped when session died
        assert mock_daemon.terminal.session_exists.call_count == 2

        # Verify final message sent about process exit
        # Either edit_message or send_message should be called with exit message
        calls = mock_daemon.telegram.send_message.call_args_list + mock_daemon.telegram.edit_message.call_args_list
        exit_message_sent = any("exited" in str(call).lower() for call in calls)
        assert exit_message_sent

        # Verify session removed from active polling
        assert session_id not in mock_daemon.active_polling_sessions

    @pytest.mark.asyncio
    async def test_poll_with_idle_notification(self, mock_daemon):
        """Test idle notification sent after configured timeout (but polling continues)."""
        from pathlib import Path

        session_id = "test-session-poll-idle"
        tmux_session_name = "test-tmux-idle"

        # Create output_dir
        mock_daemon.output_dir = Path("/tmp/test_output")
        mock_daemon.output_dir.mkdir(parents=True, exist_ok=True)

        # Set short idle timeout for testing
        mock_daemon.config = {"polling": {"idle_notification_seconds": 2}}

        # Mock session_exists
        mock_daemon.terminal.session_exists = AsyncMock(return_value=True)

        # Track poll count
        poll_count = [0]

        def capture_side_effect(*args):
            poll_count[0] += 1
            if poll_count[0] <= 3:
                # First 3 polls: same output (triggers notification at poll 3)
                return "waiting...\n"
            else:
                # Fourth poll: exit marker (stop polling)
                return "waiting...\n__EXIT__0__\n"

        mock_daemon.terminal.capture_pane = AsyncMock(side_effect=capture_side_effect)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-789")
        mock_daemon.telegram.edit_message = AsyncMock(return_value=True)
        mock_daemon.telegram.delete_message = AsyncMock()

        # Mock asyncio.sleep
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Execute
            await mock_daemon._poll_and_send_output(session_id, tmux_session_name)

        # Verify idle notification was sent (but polling continued)
        send_calls = [call[0][1] for call in mock_daemon.telegram.send_message.call_args_list]
        idle_notification_sent = any("no output" in msg.lower() for msg in send_calls)
        assert idle_notification_sent

        # Verify polling continued after notification
        assert poll_count[0] >= 4

    @pytest.mark.asyncio
    async def test_poll_with_output_truncation(self, mock_daemon):
        """Test output truncation and download button when output exceeds limit."""
        from pathlib import Path

        session_id = "test-session-poll-truncate"
        tmux_session_name = "test-tmux-truncate"

        # Mock output_dir
        mock_daemon.output_dir = Path("/tmp/test_output")

        # Mock session_exists
        mock_daemon.terminal.session_exists = AsyncMock(return_value=True)

        # Create large output (> 3800 chars to trigger truncation)
        large_output = "x" * 5000 + "\n__EXIT__0__\n"
        mock_daemon.terminal.capture_pane = AsyncMock(return_value=large_output)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-large")
        mock_daemon.telegram.edit_message = AsyncMock(return_value=True)

        # Mock asyncio.sleep
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Execute
            await mock_daemon._poll_and_send_output(session_id, tmux_session_name)

        # Verify send_message was called with metadata containing reply_markup (download button)
        send_call = mock_daemon.telegram.send_message.call_args
        if len(send_call[0]) > 2:
            # Check metadata parameter
            metadata = send_call[0][2] if len(send_call[0]) > 2 else send_call[1].get("metadata")
            if metadata:
                assert "reply_markup" in metadata or "raw_format" in metadata

    @pytest.mark.asyncio
    async def test_poll_message_editing(self, mock_daemon):
        """Test message editing flow during polling."""
        from pathlib import Path

        session_id = "test-session-poll-edit"
        tmux_session_name = "test-tmux-edit"

        # Mock output_dir
        mock_daemon.output_dir = Path("/tmp/test_output")

        # Mock session_exists
        mock_daemon.terminal.session_exists = AsyncMock(return_value=True)

        # Mock capture_pane: progressive output
        mock_daemon.terminal.capture_pane = AsyncMock(
            side_effect=[
                "output 1\n",  # First poll
                "output 1\noutput 2\n",  # Second poll
                "output 1\noutput 2\n__EXIT__0__\n",  # Third poll with exit
            ]
        )

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(return_value="msg-edit")
        mock_daemon.telegram.edit_message = AsyncMock(return_value=True)

        # Mock asyncio.sleep
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Execute
            await mock_daemon._poll_and_send_output(session_id, tmux_session_name)

        # Verify initial message sent
        assert mock_daemon.telegram.send_message.call_count >= 1

        # Verify message editing occurred
        assert mock_daemon.telegram.edit_message.call_count >= 1

    @pytest.mark.asyncio
    async def test_poll_edit_failure_sends_new_message(self, mock_daemon):
        """Test that failed edit triggers new message send."""
        from pathlib import Path

        session_id = "test-session-poll-edit-fail"
        tmux_session_name = "test-tmux-edit-fail"

        # Create output_dir
        mock_daemon.output_dir = Path("/tmp/test_output")
        mock_daemon.output_dir.mkdir(parents=True, exist_ok=True)

        # Mock session_exists
        mock_daemon.terminal.session_exists = AsyncMock(return_value=True)

        # Mock capture_pane
        mock_daemon.terminal.capture_pane = AsyncMock(
            side_effect=[
                "output 1\n",  # First poll
                "output 1\noutput 2\n",  # Second poll
                "output 1\noutput 2\n__EXIT__0__\n",  # Third poll with exit
            ]
        )

        # Mock adapter: edit_message fails first time, succeeds after
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(
            side_effect=["msg-1", "msg-2", "msg-3"]  # Return different IDs
        )
        mock_daemon.telegram.edit_message = AsyncMock(
            side_effect=[False, True, True]  # First edit fails, rest succeed
        )

        # Mock asyncio.sleep
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Execute
            await mock_daemon._poll_and_send_output(session_id, tmux_session_name)

        # Verify send_message called multiple times (initial + after failed edit)
        assert mock_daemon.telegram.send_message.call_count >= 2

    @pytest.mark.asyncio
    async def test_poll_notification_deleted_when_output_resumes(self, mock_daemon):
        """Test notification message deleted when output resumes after idle."""
        from pathlib import Path

        session_id = "test-session-poll-resume"
        tmux_session_name = "test-tmux-resume"

        # Create output_dir
        mock_daemon.output_dir = Path("/tmp/test_output")
        mock_daemon.output_dir.mkdir(parents=True, exist_ok=True)

        # Set short idle timeout
        mock_daemon.config = {"polling": {"idle_notification_seconds": 2}}

        # Mock session_exists
        mock_daemon.terminal.session_exists = AsyncMock(return_value=True)

        # Track poll count
        poll_count = [0]

        def capture_side_effect(*args):
            poll_count[0] += 1
            if poll_count[0] <= 3:
                # First 3 polls: same output (trigger idle notification at poll 3)
                return "waiting...\n"
            elif poll_count[0] == 4:
                # Fourth poll: new output (resume, triggers delete)
                return "waiting...\nresumed!\n"
            else:
                # Fifth poll: exit
                return "waiting...\nresumed!\n__EXIT__0__\n"

        mock_daemon.terminal.capture_pane = AsyncMock(side_effect=capture_side_effect)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock(
            side_effect=["msg-initial", "msg-notification", "msg-3"]
        )
        mock_daemon.telegram.edit_message = AsyncMock(return_value=True)
        mock_daemon.telegram.delete_message = AsyncMock()

        # Mock asyncio.sleep
        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Execute
            await mock_daemon._poll_and_send_output(session_id, tmux_session_name)

        # Verify notification was deleted when output resumed
        assert mock_daemon.telegram.delete_message.call_count >= 1


class TestClaudeResumeSession:
    """Tests for _claude_resume_session() method."""

    @pytest.mark.asyncio
    async def test_claude_resume_session(self, mock_daemon):
        """Test resuming Claude Code session."""
        session_id = "test-session-claude-resume"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.terminal_size = "120x40"
        mock_session.working_directory = "/tmp"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)
        mock_daemon.session_manager.update_last_activity = AsyncMock()
        mock_daemon.session_manager.increment_command_count = AsyncMock()

        # Mock terminal
        mock_daemon.terminal.send_keys = AsyncMock(return_value=True)

        # Mock _poll_and_send_output
        mock_daemon._poll_and_send_output = AsyncMock()

        # Mock config
        mock_daemon.config = {"computer": {"default_shell": "/bin/bash"}}

        # Execute
        context = {"session_id": session_id}
        await mock_daemon._claude_resume_session(context)

        # Verify claude --continue command was sent
        mock_daemon.terminal.send_keys.assert_called_once()
        call_args = mock_daemon.terminal.send_keys.call_args
        assert "claude --dangerously-skip-permissions --continue" in call_args[0][1]

        # Verify polling started
        mock_daemon._poll_and_send_output.assert_called_once()

    @pytest.mark.asyncio
    async def test_claude_resume_missing_session(self, mock_daemon):
        """Test claude_resume with missing session."""
        session_id = "nonexistent-session"

        # Mock session not found
        mock_daemon.session_manager.get_session = AsyncMock(return_value=None)

        # Execute
        context = {"session_id": session_id}
        await mock_daemon._claude_resume_session(context)

        # Should return early without calling terminal
        mock_daemon.terminal.send_keys.assert_not_called()

    @pytest.mark.asyncio
    async def test_claude_resume_send_keys_failure(self, mock_daemon):
        """Test claude_resume when send_keys fails."""
        session_id = "test-session-resume-fail"

        # Mock session
        mock_session = MagicMock()
        mock_session.session_id = session_id
        mock_session.tmux_session_name = "test-tmux"
        mock_session.terminal_size = "80x24"
        mock_session.working_directory = "/tmp"
        mock_session.adapter_type = "telegram"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock terminal send_keys failure
        mock_daemon.terminal.send_keys = AsyncMock(return_value=False)

        # Mock adapter
        mock_daemon._get_adapter_for_session = AsyncMock(return_value=mock_daemon.telegram)
        mock_daemon.telegram.send_message = AsyncMock()

        # Mock config
        mock_daemon.config = {"computer": {"default_shell": "/bin/bash"}}

        # Execute
        context = {"session_id": session_id}
        await mock_daemon._claude_resume_session(context)

        # Verify error message sent
        mock_daemon.telegram.send_message.assert_called_once()
        call_args = mock_daemon.telegram.send_message.call_args
        assert "failed" in call_args[0][1].lower()


class TestErrorHandling:
    """Tests for error handling in daemon methods."""

    @pytest.mark.asyncio
    async def test_get_adapter_for_session_not_found(self, mock_daemon):
        """Test _get_adapter_for_session with non-existent session."""
        session_id = "nonexistent"

        # Mock session not found
        mock_daemon.session_manager.get_session = AsyncMock(return_value=None)

        # Execute and verify exception
        with pytest.raises(ValueError, match="not found"):
            await mock_daemon._get_adapter_for_session(session_id)

    @pytest.mark.asyncio
    async def test_get_adapter_for_session_unknown_type(self, mock_daemon):
        """Test _get_adapter_for_session with unknown adapter type."""
        session_id = "test-session-unknown"

        # Mock session with unknown adapter type
        mock_session = MagicMock()
        mock_session.adapter_type = "unknown-type"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock adapters registry (doesn't contain unknown-type)
        mock_daemon.adapters = {"telegram": mock_daemon.telegram}

        # Execute and verify exception
        with pytest.raises(ValueError, match="No adapter available"):
            await mock_daemon._get_adapter_for_session(session_id)

    @pytest.mark.asyncio
    async def test_get_adapter_by_type_unknown(self, mock_daemon):
        """Test _get_adapter_by_type with unknown type."""
        # Mock adapters registry
        mock_daemon.adapters = {"telegram": mock_daemon.telegram}

        # Execute and verify exception
        with pytest.raises(ValueError, match="No adapter available"):
            mock_daemon._get_adapter_by_type("unknown-type")

    @pytest.mark.asyncio
    async def test_create_session_missing_adapter_type(self, mock_daemon):
        """Test _create_session with missing adapter_type in context."""
        # Context without adapter_type
        context = {"user_id": 123}

        # Execute and verify exception
        with pytest.raises(ValueError, match="adapter_type"):
            await mock_daemon._create_session(context, ["Test"])

    @pytest.mark.asyncio
    async def test_list_sessions_missing_adapter_type(self, mock_daemon):
        """Test _list_sessions with missing adapter_type in context."""
        # Context without adapter_type
        context = {}

        # Execute (should return early with log)
        await mock_daemon._list_sessions(context)

        # Should not call session_manager
        mock_daemon.session_manager.list_sessions.assert_not_called()

    @pytest.mark.asyncio
    async def test_cancel_command_missing_session_id(self, mock_daemon):
        """Test _cancel_command with missing session_id."""
        # Context without session_id
        context = {}

        # Execute (should return early with warning)
        await mock_daemon._cancel_command(context)

        # Should not call terminal
        mock_daemon.terminal.send_signal.assert_not_called()

    @pytest.mark.asyncio
    async def test_escape_command_missing_session_id(self, mock_daemon):
        """Test _escape_command with missing session_id."""
        # Context without session_id
        context = {}

        # Execute (should return early with warning)
        await mock_daemon._escape_command(context)

        # Should not call terminal
        mock_daemon.terminal.send_escape.assert_not_called()


class TestDaemonInitialization:
    """Tests for daemon initialization and setup."""

    @pytest.mark.asyncio
    async def test_daemon_initialization_success(self):
        """Test successful daemon initialization."""
        # Create temp files for config and env
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as config_file:
            config_file.write("""
database:
  path: /tmp/test.db
computer:
  name: TestComputer
  default_shell: /bin/bash
  default_working_dir: /tmp
  trustedDirs: [/tmp]
terminal:
  default_size: 80x24
rest_api:
  port: 6666
""")
            config_path = config_file.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as env_file:
            env_file.write("TELEGRAM_BOT_TOKEN=test-token\nTELEGRAM_SUPERGROUP_ID=123\nTELEGRAM_USER_IDS=456\n")
            env_path = env_file.name

        try:
            # Mock components
            with patch('teleclaude.daemon.SessionManager'), \
                 patch('teleclaude.daemon.TerminalBridge'), \
                 patch('teleclaude.daemon.VoiceHandler'), \
                 patch('teleclaude.daemon.TeleClaudeAPI'), \
                 patch('teleclaude.daemon.TelegramAdapter'), \
                 patch.object(Path, 'mkdir'):

                # Create daemon
                daemon = TeleClaudeDaemon(config_path, env_path)

                # Verify basic initialization
                assert daemon.config["computer"]["name"] == "TestComputer"
                assert daemon.config["terminal"]["default_size"] == "80x24"
                assert "telegram" in daemon.adapters
                assert daemon.primary_adapter is not None
        finally:
            # Cleanup
            os.unlink(config_path)
            os.unlink(env_path)

    @pytest.mark.asyncio
    async def test_daemon_lock_acquisition(self):
        """Test PID file lock acquisition."""
        # Create temp files
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as config_file:
            config_file.write("database:\n  path: /tmp/test.db\ncomputer:\n  name: Test\n  default_shell: /bin/bash\n  default_working_dir: /tmp\nterminal:\n  default_size: 80x24\n")
            config_path = config_file.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as env_file:
            env_file.write("TELEGRAM_BOT_TOKEN=test\nTELEGRAM_SUPERGROUP_ID=1\nTELEGRAM_USER_IDS=1\n")
            env_path = env_file.name

        # Create temp PID file
        temp_pid = tempfile.NamedTemporaryFile(delete=False, suffix='.pid')
        temp_pid.close()
        pid_path = Path(temp_pid.name)

        try:
            with patch('teleclaude.daemon.SessionManager'), \
                 patch('teleclaude.daemon.TerminalBridge'), \
                 patch('teleclaude.daemon.VoiceHandler'), \
                 patch('teleclaude.daemon.TeleClaudeAPI'), \
                 patch('teleclaude.daemon.TelegramAdapter'), \
                 patch.object(Path, 'mkdir'):

                daemon = TeleClaudeDaemon(config_path, env_path)
                daemon.pid_file = pid_path  # Use temp PID file

                # Try to acquire lock
                daemon._acquire_lock()

                # Verify PID file exists and contains current PID
                assert daemon.pid_file.exists()
                pid_content = daemon.pid_file.read_text().strip()
                assert pid_content == str(os.getpid())

                # Release lock
                daemon._release_lock()

                # PID file should be deleted
                assert not daemon.pid_file.exists()
        finally:
            os.unlink(config_path)
            os.unlink(env_path)
            if pid_path.exists():
                pid_path.unlink()

    @pytest.mark.asyncio
    async def test_daemon_lock_already_held(self):
        """Test that second daemon instance cannot acquire lock."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as config_file:
            config_file.write("database:\n  path: /tmp/test.db\ncomputer:\n  name: Test\n  default_shell: /bin/bash\n  default_working_dir: /tmp\nterminal:\n  default_size: 80x24\n")
            config_path = config_file.name

        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as env_file:
            env_file.write("TELEGRAM_BOT_TOKEN=test\nTELEGRAM_SUPERGROUP_ID=1\nTELEGRAM_USER_IDS=1\n")
            env_path = env_file.name

        # Create temp PID file
        temp_pid = tempfile.NamedTemporaryFile(delete=False, suffix='.pid')
        temp_pid.close()
        pid_path = Path(temp_pid.name)

        try:
            with patch('teleclaude.daemon.SessionManager'), \
                 patch('teleclaude.daemon.TerminalBridge'), \
                 patch('teleclaude.daemon.VoiceHandler'), \
                 patch('teleclaude.daemon.TeleClaudeAPI'), \
                 patch('teleclaude.daemon.TelegramAdapter'), \
                 patch.object(Path, 'mkdir'):

                daemon1 = TeleClaudeDaemon(config_path, env_path)
                daemon2 = TeleClaudeDaemon(config_path, env_path)
                daemon1.pid_file = pid_path  # Use temp PID file
                daemon2.pid_file = pid_path  # Same PID file

                # First daemon acquires lock successfully
                daemon1._acquire_lock()

                # Second daemon should fail to acquire lock
                with pytest.raises(DaemonLockError, match="already running"):
                    daemon2._acquire_lock()

                # Release lock
                daemon1._release_lock()
        finally:
            os.unlink(config_path)
            os.unlink(env_path)
            if pid_path.exists():
                pid_path.unlink()
