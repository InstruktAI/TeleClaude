"""Unit tests for daemon.py core logic."""

import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from teleclaude import config as config_module
from teleclaude.daemon import DaemonLockError, TeleClaudeDaemon

@pytest.fixture
def mock_daemon():
    """Create a mocked daemon for testing."""
    with (
        patch("teleclaude.daemon.Db") as mock_sm,
        patch("teleclaude.core.terminal_bridge") as mock_tb,
        patch("teleclaude.core.message_handler.terminal_bridge", mock_tb),
        patch("teleclaude.core.voice_message_handler.terminal_bridge", mock_tb),
        patch("teleclaude.daemon.TelegramAdapter") as mock_ta,
        patch("teleclaude.daemon.ComputerRegistry") as mock_cr,
        patch("teleclaude.daemon.TeleClaudeMCPServer") as mock_mcp,
        patch.object(config_module, "_config", None),
    ):  # Reset config before each test

        # Create daemon instance
        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        # Mock config
        daemon.config = {
            "computer": {"name": "TestComputer", "default_shell": "/bin/zsh", "default_working_dir": "/tmp"},
            "terminal": {"default_size": "80x24"},
            "polling": {"idle_notification_seconds": 60},
        }

        # Initialize global config (critical for terminal_bridge and other modules)
        # Config no longer needs initialization

        # Mock essential attributes
        daemon.session_manager = mock_sm.return_value
        # Set up async methods on session_manager
        daemon.db.get_session = AsyncMock(return_value=None)
        daemon.db.update_last_activity = AsyncMock()
        daemon.db.is_polling = AsyncMock(return_value=False)
        daemon.db.has_idle_notification = AsyncMock(return_value=False)
        daemon.db.cleanup_messages_after_success = AsyncMock()
        daemon.db.list_sessions = AsyncMock(return_value=[])
        daemon.db.create_session = AsyncMock()
        daemon.db.update_session = AsyncMock()
        daemon.db.delete_session = AsyncMock()

        # Mock terminal_bridge (patched at core level for all modules)
        mock_tb.send_keys = AsyncMock(return_value=True)
        mock_tb.send_signal = AsyncMock(return_value=True)
        mock_tb.send_escape = AsyncMock(return_value=True)
        mock_tb.capture_pane = AsyncMock(return_value="")
        mock_tb.kill_session = AsyncMock(return_value=True)
        mock_tb.list_sessions = AsyncMock(return_value=[])
        mock_tb.resize_session = AsyncMock(return_value=True)
        mock_tb.clear_history = AsyncMock(return_value=True)

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

        daemon.session_output_buffers = {}
        daemon.output_dir = "/tmp/test_output"

        # Mock voice_handler (still used as instance in daemon)
        daemon.voice_handler = MagicMock()

        # Mock output_poller (used in _poll_and_send_output)
        daemon.output_poller = MagicMock()

        # Mock adapter registry
        daemon.adapters = {"telegram": daemon.telegram}

        # Mock computer_registry and mcp_server (Phase 1 MCP support)
        daemon.computer_registry = mock_cr.return_value
        daemon.computer_registry.start = AsyncMock()
        daemon.computer_registry.get_online_computers = Mock(return_value=[])
        daemon.computer_registry.is_computer_online = Mock(return_value=False)

        daemon.mcp_server = mock_mcp.return_value
        daemon.mcp_server.start = AsyncMock()

        # Mock helper methods
        daemon._get_adapter_by_type = MagicMock(return_value=daemon.telegram)
        daemon._get_adapter_for_session = AsyncMock(return_value=daemon.telegram)
        daemon._get_output_file = lambda session_id: Path(f"/tmp/test_output/{session_id[:8]}.txt")
        daemon._poll_and_send_output = AsyncMock()
        daemon._execute_terminal_command = AsyncMock(return_value=True)

        yield daemon
