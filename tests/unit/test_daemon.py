"""Unit tests for daemon.py core logic."""

import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from teleclaude.daemon import TeleClaudeDaemon, DaemonLockError
from teleclaude import config as config_module


@pytest.fixture
def mock_daemon():
    """Create a mocked daemon for testing."""
    with patch('teleclaude.daemon.SessionManager') as mock_sm, \
         patch('teleclaude.core.terminal_bridge') as mock_tb, \
         patch('teleclaude.core.message_handler.terminal_bridge', mock_tb), \
         patch('teleclaude.core.voice_message_handler.terminal_bridge', mock_tb), \
         patch('teleclaude.daemon.TelegramAdapter') as mock_ta, \
         patch('teleclaude.core.state_manager.is_polling', return_value=False) as mock_is_polling, \
         patch('teleclaude.core.state_manager.has_idle_notification', return_value=False), \
         patch.object(config_module, '_config', None):  # Reset config before each test

        # Create daemon instance
        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        # Mock config
        daemon.config = {
            "computer": {
                "name": "TestComputer",
                "default_shell": "/bin/zsh",
                "default_working_dir": "/tmp"
            },
            "terminal": {"default_size": "80x24"},
            "polling": {"idle_notification_seconds": 60}
        }

        # Initialize global config (critical for terminal_bridge and other modules)
        config_module.init_config(daemon.config)

        # Mock essential attributes
        daemon.session_manager = mock_sm.return_value
        # Set up async methods on session_manager
        daemon.session_manager.get_session = AsyncMock(return_value=None)
        daemon.session_manager.get_output_message_id = AsyncMock(return_value=None)
        daemon.session_manager.set_idle_notification_message_id = AsyncMock()
        daemon.session_manager.update_output_message_id = AsyncMock()
        daemon.session_manager.update_last_activity = AsyncMock()
        daemon.session_manager.increment_command_count = AsyncMock()
        daemon.session_manager.list_sessions = AsyncMock(return_value=[])
        daemon.session_manager.create_session = AsyncMock()
        daemon.session_manager.update_session = AsyncMock()
        daemon.session_manager.delete_session = AsyncMock()
        daemon.session_manager.set_output_message_id = AsyncMock()
        daemon.session_manager.get_idle_notification_message_id = AsyncMock(return_value=None)

        # Mock terminal_bridge (patched at core level for all modules)
        mock_tb.send_keys = AsyncMock(return_value=True)
        mock_tb.send_signal = AsyncMock(return_value=True)
        mock_tb.send_escape = AsyncMock(return_value=True)
        mock_tb.capture_pane = AsyncMock(return_value="")
        mock_tb.kill_session = AsyncMock(return_value=True)
        mock_tb.list_sessions = AsyncMock(return_value=[])
        mock_tb.resize_session = AsyncMock(return_value=True)

        # Make terminal_bridge accessible as daemon.terminal for tests
        daemon.terminal = mock_tb

        # Mock telegram adapter with ASYNC methods
        daemon.telegram = mock_ta.return_value
        daemon.telegram.send_message = AsyncMock(return_value="msg-123")
        daemon.telegram.edit_message = AsyncMock(return_value=True)
        daemon.telegram.delete_message = AsyncMock()
        daemon.telegram.send_general_message = AsyncMock(return_value="msg-123")
        daemon.telegram.create_channel = AsyncMock(return_value="456")
        daemon.telegram.update_channel_title = AsyncMock(return_value=True)
        daemon.telegram.delete_channel = AsyncMock(return_value=True)
        daemon.telegram.send_file = AsyncMock(return_value="file-msg-123")

        daemon.session_output_buffers = {}
        daemon.output_dir = "/tmp/test_output"

        # Mock voice_handler (still used as instance in daemon)
        daemon.voice_handler = MagicMock()

        # Mock output_poller (used in _poll_and_send_output)
        daemon.output_poller = MagicMock()

        # Mock adapter registry
        daemon.adapters = {"telegram": daemon.telegram}

        # Mock helper methods
        daemon._get_adapter_by_type = MagicMock(return_value=daemon.telegram)
        daemon._get_adapter_for_session = AsyncMock(return_value=daemon.telegram)
        daemon._get_output_file = lambda session_id: Path(f"/tmp/test_output/{session_id[:8]}.txt")
        daemon._poll_and_send_output = AsyncMock()
        daemon._execute_terminal_command = AsyncMock(return_value=True)

        # Store mock for tests that need to change is_polling behavior
        daemon.mock_is_polling = mock_is_polling

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
        mock_session.adapter_type = "telegram"
        mock_session.terminal_size = "80x24"  # Required by message_handler
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock state_manager (not polling) - already mocked in fixture with return_value=False

        # Execute
        await mock_daemon.handle_message(session_id, text, {"adapter_type": "telegram", "message_id": "msg-123"})

        # Verify send_keys was called with stripped text (patched in fixture)
        mock_daemon.terminal.send_keys.assert_called_once()
        call_args = mock_daemon.terminal.send_keys.call_args
        # Check positional arg [1] for text
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
        mock_session.adapter_type = "telegram"
        mock_session.terminal_size = "80x24"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock state_manager (not polling) - already mocked in fixture with return_value=False

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
        mock_session.adapter_type = "telegram"
        mock_session.terminal_size = "80x24"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock state_manager (NOT polling - new command) - already mocked in fixture with return_value=False

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
        mock_session.adapter_type = "telegram"
        mock_session.terminal_size = "80x24"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock state_manager (IS polling - running process)
        mock_daemon.mock_is_polling.return_value = True

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
        mock_session.adapter_type = "telegram"
        mock_session.terminal_size = "80x24"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock state_manager (IS polling - running process)
        mock_daemon.mock_is_polling.return_value = True

        # Execute
        await mock_daemon.handle_message(session_id, text, {
            "adapter_type": "telegram",
            "message_id": "msg-456"
        })

        # Verify both behaviors: stripped text AND no exit marker
        call_args = mock_daemon.terminal.send_keys.call_args
        assert call_args[0][1] == "/clear", "Should strip // to /"
        assert call_args[1]["append_exit_marker"] is False, "Should NOT append exit marker"












class TestErrorHandling:
    """Tests for error handling in daemon methods."""

    @pytest.mark.asyncio
    async def test_get_adapter_for_session_not_found(self, mock_daemon):
        """Test _get_adapter_for_session with non-existent session."""
        from teleclaude.daemon import TeleClaudeDaemon
        session_id = "nonexistent"

        # Mock session not found
        mock_daemon.session_manager.get_session = AsyncMock(return_value=None)

        # Use real method instead of mock
        mock_daemon._get_adapter_for_session = TeleClaudeDaemon._get_adapter_for_session.__get__(mock_daemon)

        # Execute and verify exception
        with pytest.raises(ValueError, match="not found"):
            await mock_daemon._get_adapter_for_session(session_id)

    @pytest.mark.asyncio
    async def test_get_adapter_for_session_unknown_type(self, mock_daemon):
        """Test _get_adapter_for_session with unknown adapter type."""
        from teleclaude.daemon import TeleClaudeDaemon
        session_id = "test-session-unknown"

        # Mock session with unknown adapter type
        mock_session = MagicMock()
        mock_session.adapter_type = "unknown-type"
        mock_daemon.session_manager.get_session = AsyncMock(return_value=mock_session)

        # Mock adapters registry (doesn't contain unknown-type)
        mock_daemon.adapters = {"telegram": mock_daemon.telegram}

        # Use real method instead of mock
        mock_daemon._get_adapter_for_session = TeleClaudeDaemon._get_adapter_for_session.__get__(mock_daemon)

        # Execute and verify exception
        with pytest.raises(ValueError, match="No adapter available"):
            await mock_daemon._get_adapter_for_session(session_id)

    @pytest.mark.asyncio
    async def test_get_adapter_by_type_unknown(self, mock_daemon):
        """Test _get_adapter_by_type with unknown type."""
        from teleclaude.daemon import TeleClaudeDaemon

        # Mock adapters registry
        mock_daemon.adapters = {"telegram": mock_daemon.telegram}

        # Use real method instead of mock
        mock_daemon._get_adapter_by_type = TeleClaudeDaemon._get_adapter_by_type.__get__(mock_daemon)

        # Execute and verify exception
        with pytest.raises(ValueError, match="No adapter available"):
            mock_daemon._get_adapter_by_type("unknown-type")


class TestDaemonInitialization:
    """Tests for daemon initialization and setup."""

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
                 patch('teleclaude.daemon.TeleClaudeAPI'), \
                 patch('teleclaude.daemon.TelegramAdapter'), \
                 patch('teleclaude.daemon.terminal_bridge'), \
                 patch('teleclaude.daemon.init_config'), \
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
                 patch('teleclaude.daemon.TeleClaudeAPI'), \
                 patch('teleclaude.daemon.TelegramAdapter'), \
                 patch('teleclaude.daemon.terminal_bridge'), \
                 patch('teleclaude.daemon.init_config'), \
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
