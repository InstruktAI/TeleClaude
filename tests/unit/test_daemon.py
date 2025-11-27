"""Unit tests for daemon.py core logic."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from teleclaude import config as config_module
from teleclaude.daemon import TeleClaudeDaemon


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
        daemon._get_output_file_path = lambda session_id: Path(f"/tmp/test_output/{session_id[:8]}.txt")
        daemon._poll_and_send_output = AsyncMock()
        daemon._execute_terminal_command = AsyncMock(return_value=True)

        yield daemon


@pytest.mark.asyncio
class TestSessionCloseReopen:
    """Test session close and reopen functionality."""

    async def test_reopen_session_creates_tmux_at_saved_working_dir(self):
        """Test that _reopen_session creates tmux at saved working_dir."""
        from unittest.mock import AsyncMock, Mock, patch

        from teleclaude import config as config_module
        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        # Create daemon instance without full initialization
        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        # Setup mocks (must patch at daemon module namespace, not config_module)
        with (
            patch("teleclaude.daemon.terminal_bridge") as mock_tb,
            patch("teleclaude.daemon.db") as mock_db,
            patch("teleclaude.daemon.config") as mock_config,  # Patch where it's imported
        ):
            mock_tb.create_tmux_session = AsyncMock()
            mock_db.update_session = AsyncMock()

            # Mock config.computer.default_shell (must set up the mock chain properly)
            mock_computer = Mock()
            mock_computer.default_shell = "/bin/zsh"
            mock_config.computer = mock_computer

            # Test session
            session = Session(
                session_id="test-123",
                computer_name="TestMac",
                tmux_session_name="test-tmux-123",
                origin_adapter="telegram",
                title="Test",
                working_directory="/home/user/project",
                terminal_size="120x40",
                closed=True,
            )

            # Execute
            await daemon._reopen_session(session)

            # Verify: tmux created at saved directory
            mock_tb.create_tmux_session.assert_called_once_with(
                name="test-tmux-123",
                working_dir="/home/user/project",
                shell="/bin/zsh",
                cols=120,
                rows=40,
                session_id="test-123",
            )

            # Verify: marked active
            mock_db.update_session.assert_called_once_with("test-123", closed=False)


@pytest.mark.asyncio
class TestSessionCleanup:
    """Test session cleanup functionality."""

    async def test_cleanup_inactive_sessions_cleans_old_sessions(self):
        """Test cleanup of sessions inactive for 72+ hours."""
        from datetime import datetime, timedelta
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        # Create daemon instance
        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        # Create session inactive for 73 hours
        old_time = datetime.now() - timedelta(hours=73)
        inactive_session = Session(
            session_id="inactive-123",
            computer_name="TestMac",
            tmux_session_name="inactive-tmux",
            origin_adapter="telegram",
            title="Inactive",
            closed=False,
            last_activity=old_time,
        )

        with patch("teleclaude.daemon.db") as mock_db, patch("teleclaude.daemon.terminal_bridge") as mock_tb:
            mock_db.list_sessions = AsyncMock(return_value=[inactive_session])
            mock_db.update_session = AsyncMock()
            mock_tb.kill_session = AsyncMock()

            # Execute cleanup
            await daemon._cleanup_inactive_sessions()

            # Verify tmux killed
            mock_tb.kill_session.assert_called_once_with("inactive-tmux")

            # Verify session marked closed
            mock_db.update_session.assert_called_once_with("inactive-123", closed=True)

    async def test_cleanup_skips_recently_active_sessions(self):
        """Test that recently active sessions are not cleaned up."""
        from datetime import datetime, timedelta
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        # Session active 1 hour ago
        recent_time = datetime.now() - timedelta(hours=1)
        active_session = Session(
            session_id="active-456",
            computer_name="TestMac",
            tmux_session_name="active-tmux",
            origin_adapter="telegram",
            title="Active",
            closed=False,
            last_activity=recent_time,
        )

        with patch("teleclaude.daemon.db") as mock_db, patch("teleclaude.daemon.terminal_bridge") as mock_tb:
            mock_db.list_sessions = AsyncMock(return_value=[active_session])
            mock_db.update_session = AsyncMock()
            mock_tb.kill_session = AsyncMock()

            # Execute cleanup
            await daemon._cleanup_inactive_sessions()

            # Verify NO cleanup
            mock_tb.kill_session.assert_not_called()
            mock_db.update_session.assert_not_called()

    async def test_cleanup_skips_closed_sessions(self):
        """Test that closed sessions are skipped."""
        from datetime import datetime, timedelta
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        old_time = datetime.now() - timedelta(hours=100)
        closed_session = Session(
            session_id="closed-789",
            computer_name="TestMac",
            tmux_session_name="closed-tmux",
            origin_adapter="telegram",
            title="Closed",
            closed=True,
            last_activity=old_time,
        )

        with patch("teleclaude.daemon.db") as mock_db, patch("teleclaude.daemon.terminal_bridge") as mock_tb:
            mock_db.list_sessions = AsyncMock(return_value=[closed_session])
            mock_db.update_session = AsyncMock()
            mock_tb.kill_session = AsyncMock()

            # Execute cleanup
            await daemon._cleanup_inactive_sessions()

            # Verify NO cleanup
            mock_tb.kill_session.assert_not_called()
            mock_db.update_session.assert_not_called()


def test_all_events_have_handlers():
    """Test that every event in TeleClaudeEvents has a registered handler.

    This prevents bugs where new events are added but not registered in COMMAND_EVENTS
    or don't have a specific handler method.
    """
    from teleclaude.core.events import TeleClaudeEvents
    from teleclaude.daemon import COMMAND_EVENTS, TeleClaudeDaemon

    # Get all events from TeleClaudeEvents
    all_events = []
    for attr_name in dir(TeleClaudeEvents):
        if attr_name.startswith("_"):
            continue
        event_value = getattr(TeleClaudeEvents, attr_name)
        if isinstance(event_value, str):
            all_events.append(event_value)

    # Check each event has a handler
    # Redis-only events (handled in Redis adapter, not daemon)
    REDIS_ONLY_EVENTS = {"create_session"}

    missing_handlers = []
    for event in all_events:
        # Command events have generic handler
        if event in COMMAND_EVENTS:
            continue

        # Redis-only events handled in Redis adapter
        if event in REDIS_ONLY_EVENTS:
            continue

        # Non-command events need specific handler method
        handler_name = f"_handle_{event}"
        if not hasattr(TeleClaudeDaemon, handler_name):
            missing_handlers.append(f"{event} (expected {handler_name})")

    # Report missing handlers
    assert not missing_handlers, (
        f"Events missing handlers: {missing_handlers}\n" f"Add to COMMAND_EVENTS in daemon.py or create handler method"
    )
