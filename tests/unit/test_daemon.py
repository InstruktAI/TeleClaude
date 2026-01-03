"""Unit tests for daemon.py core logic."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from teleclaude import config as config_module
from teleclaude.core.events import CommandEventContext, TeleClaudeEvents
from teleclaude.core.models import MessageMetadata
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
            "polling": {"directory_check_interval": 5},
        }

        # Initialize global config (critical for terminal_bridge and other modules)
        # Config no longer needs initialization

        # Mock essential attributes
        daemon.session_manager = mock_sm.return_value
        # Set up async methods on session_manager
        daemon.db.get_session = AsyncMock(return_value=None)
        daemon.db.update_last_activity = AsyncMock()
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
async def test_get_session_data_parses_tail_chars_without_placeholders():
    """GET_SESSION_DATA should accept '/get_session_data <tail_chars>' form.

    Redis/MCP transport collapses empty placeholders, so callers can't reliably send
    '/get_session_data <since> <until> <tail_chars>' with empty since/until values.
    """
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    context = CommandEventContext(session_id="sess-123", args=[])

    with patch("teleclaude.daemon.command_handlers.handle_get_session_data", new_callable=AsyncMock) as mock_handler:
        mock_handler.return_value = {"status": "success"}
        await daemon.handle_command(
            TeleClaudeEvents.GET_SESSION_DATA,
            ["2000"],
            context,
            MessageMetadata(adapter_type="redis"),
        )

        mock_handler.assert_awaited_once()
        _, call_kwargs = mock_handler.call_args
        assert call_kwargs == {}
        call_args = mock_handler.call_args.args
        assert call_args[0] is context
        assert call_args[1] is None
        assert call_args[2] is None
    assert call_args[3] == 2000


@pytest.mark.asyncio
async def test_new_session_auto_command_agent_then_message():
    """Auto-command agent_then_message starts agent then injects message."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()
    daemon._execute_auto_command = AsyncMock(return_value={"status": "success"})
    daemon._queue_background_task = MagicMock(side_effect=lambda coro, _label: coro.close())

    with patch("teleclaude.daemon.command_handlers.handle_create_session", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"session_id": "sess-123"}

        context = CommandEventContext(session_id="sess-ctx", args=[])
        metadata = MessageMetadata(
            adapter_type="redis",
            auto_command="agent_then_message codex slow /prompts:next-review next-machine",
        )

        result = await daemon.handle_command(
            TeleClaudeEvents.NEW_SESSION,
            [],
            context,
            metadata,
        )

        assert result["session_id"] == "sess-123"
        assert result["auto_command_status"] == "queued"
        daemon._queue_background_task.assert_called_once()


@pytest.mark.asyncio
async def test_agent_then_message_waits_settle_delay():
    """agent_then_message should pause before injecting message."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()

    with (
        patch("teleclaude.daemon.command_handlers.handle_agent_start", new_callable=AsyncMock),
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.terminal_bridge.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.terminal_bridge.send_keys", new_callable=AsyncMock) as mock_send_keys,
        patch("teleclaude.daemon.terminal_bridge.capture_pane", new_callable=AsyncMock) as mock_capture,
        patch("teleclaude.daemon.terminal_bridge.send_enter", new_callable=AsyncMock),
        patch("teleclaude.daemon.AGENT_START_POLL_INTERVAL_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_SETTLE_DELAY_S", 2.5),
        patch("teleclaude.daemon.AGENT_START_CONFIRM_ENTER_ATTEMPTS", 1),
        patch("teleclaude.daemon.AGENT_START_CONFIRM_ENTER_DELAY_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_ENTER_INTER_DELAY_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_OUTPUT_POLL_INTERVAL_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_POST_INJECT_DELAY_S", 0.0),
        patch("teleclaude.daemon.asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", working_directory=".", terminal_size="80x24")
        )
        mock_db.get_ux_state = AsyncMock(return_value=MagicMock(active_agent="gemini"))
        mock_db.update_last_activity = AsyncMock()
        mock_running.return_value = True
        mock_send_keys.return_value = True
        mock_capture.side_effect = ["baseline", "changed"]

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["gemini", "slow", "/prime-architect"],
        )

        assert result["status"] == "success"
        mock_sleep.assert_any_await(2.5)


@pytest.mark.asyncio
async def test_agent_then_message_times_out_on_no_output_change():
    """agent_then_message should fail if output never changes after enter."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()

    with (
        patch("teleclaude.daemon.command_handlers.handle_agent_start", new_callable=AsyncMock),
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.terminal_bridge.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.terminal_bridge.send_keys", new_callable=AsyncMock) as mock_send_keys,
        patch("teleclaude.daemon.terminal_bridge.capture_pane", new_callable=AsyncMock) as mock_capture,
        patch("teleclaude.daemon.terminal_bridge.send_enter", new_callable=AsyncMock),
        patch("teleclaude.daemon.AGENT_START_POLL_INTERVAL_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_SETTLE_DELAY_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_CONFIRM_ENTER_ATTEMPTS", 1),
        patch("teleclaude.daemon.AGENT_START_CONFIRM_ENTER_DELAY_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_ENTER_INTER_DELAY_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_OUTPUT_POLL_INTERVAL_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_OUTPUT_CHANGE_TIMEOUT_S", 0.0),
        patch("teleclaude.daemon.AGENT_START_POST_INJECT_DELAY_S", 0.0),
    ):
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", working_directory=".", terminal_size="80x24")
        )
        mock_db.get_ux_state = AsyncMock(return_value=MagicMock(active_agent="claude"))
        mock_db.update_last_activity = AsyncMock()
        mock_running.return_value = True
        mock_send_keys.return_value = True
        mock_capture.return_value = "baseline"

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["claude", "slow", "/next-work"],
        )


@pytest.mark.asyncio
async def test_restart_mcp_server_replaces_task():
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.mcp_server = MagicMock()
    daemon.mcp_server.start = AsyncMock()
    daemon.mcp_server.stop = AsyncMock()
    daemon.shutdown_event = asyncio.Event()
    daemon._mcp_restart_lock = asyncio.Lock()
    daemon._mcp_restart_attempts = 0
    daemon._mcp_restart_window_start = 0.0
    daemon._log_background_task_exception = MagicMock(return_value=lambda _task: None)
    daemon._handle_mcp_task_done = MagicMock()

    daemon.mcp_task = asyncio.create_task(asyncio.sleep(10))

    ok = await daemon._restart_mcp_server("test")

    assert ok is True
    assert daemon.mcp_task is not None
    assert daemon.mcp_task.done() is False

    daemon.mcp_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await daemon.mcp_task

        assert result["status"] == "error"
        assert "Timeout waiting for command acceptance" in result["message"]


def test_summarize_output_change_reports_diff():
    """_summarize_output_change should report a diff index and snippets."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    summary = daemon._summarize_output_change("hello", "hEllo")
    assert summary["changed"] is True
    assert summary["diff_index"] == 1
    assert "before_snippet" in summary
    assert "after_snippet" in summary


@pytest.mark.asyncio
async def test_process_agent_stop_uses_registered_transcript_when_payload_missing():
    """Agent STOP should use stored transcript path when payload omits it."""
    from teleclaude.core.agents import AgentName
    from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload
    from teleclaude.core.ux_state import SessionUXState

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.send_feedback = AsyncMock()
    daemon.agent_coordinator = MagicMock()
    daemon.agent_coordinator.handle_stop = AsyncMock()
    daemon._update_session_title = AsyncMock()
    daemon._last_stop_time = {}
    daemon._stop_debounce_seconds = 5.0

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="",
        raw={},
    )
    context = AgentEventContext(session_id="tele-123", event_type=AgentHookEvents.AGENT_STOP, data=payload)

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.summarize", new_callable=AsyncMock) as mock_summarize,
    ):
        mock_db.get_ux_state = AsyncMock(
            return_value=SessionUXState(active_agent="gemini", native_log_file="/tmp/native.json")
        )
        mock_db.get_session = AsyncMock(return_value=MagicMock())
        mock_summarize.return_value = ("title", "summary")

        await daemon._process_agent_stop(context)

        mock_summarize.assert_awaited_once_with(AgentName.GEMINI, "/tmp/native.json")


@pytest.mark.asyncio
class TestSessionCloseReopen:
    """Test session close and reopen functionality."""

    async def test_reopen_session_creates_tmux_at_saved_working_dir(self):
        """Test that _reopen_session creates tmux at saved working_dir."""
        from unittest.mock import AsyncMock, Mock, patch

        from teleclaude.core.models import Session
        from teleclaude.core.ux_state import SessionUXState
        from teleclaude.daemon import TeleClaudeDaemon

        # Create daemon instance without full initialization
        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        # Setup mocks (must patch at daemon module namespace, not config_module)
        with (
            patch("teleclaude.daemon.terminal_bridge") as mock_tb,
            patch("teleclaude.daemon.db") as mock_db,
            patch("teleclaude.daemon.config") as mock_config,
        ):
            mock_tb.create_tmux_session = AsyncMock()
            mock_db.update_session = AsyncMock()
            mock_db.get_ux_state = AsyncMock(return_value=SessionUXState())  # No claude_session_id
            mock_db.get_voice = AsyncMock(return_value=None)  # No voice stored

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

            # Verify: tmux created at saved directory (env_vars=None when no voice found)
            mock_tb.create_tmux_session.assert_called_once_with(
                name="test-tmux-123",
                working_dir="/home/user/project",
                cols=120,
                rows=40,
                session_id="test-123",
                env_vars=None,
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
    # UI adapter events (handled in UI adapters like TelegramAdapter, not daemon)
    UI_ADAPTER_EVENTS = {"session_updated", "claude_event"}

    missing_handlers = []
    for event in all_events:
        # Command events have generic handler
        if event in COMMAND_EVENTS:
            continue

        # Redis-only events handled in Redis adapter
        if event in REDIS_ONLY_EVENTS:
            continue

        # UI adapter events handled in UI adapters
        if event in UI_ADAPTER_EVENTS:
            continue

        # Non-command events need specific handler method
        handler_name = f"_handle_{event}"
        if not hasattr(TeleClaudeDaemon, handler_name):
            missing_handlers.append(f"{event} (expected {handler_name})")

    # Report missing handlers
    assert not missing_handlers, (
        f"Events missing handlers: {missing_handlers}\nAdd to COMMAND_EVENTS in daemon.py or create handler method"
    )


@pytest.mark.asyncio
class TestTitleUpdate:
    """Test session title updates."""

    async def test_update_session_title_updates_new_session(self):
        """Title should update when description is 'New session'."""
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        session = Session(
            session_id="sess-1",
            computer_name="TestMac",
            tmux_session_name="tmux-1",
            origin_adapter="telegram",
            title="TeleClaude: $TestMac - New session",
            closed=False,
        )

        with patch("teleclaude.daemon.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()

            await daemon._update_session_title("sess-1", "Fix login bug")

            mock_db.update_session.assert_called_once_with("sess-1", title="TeleClaude: $TestMac - Fix login bug")

    async def test_update_session_title_updates_new_session_with_counter(self):
        """Title should update when description is 'New session (N)'."""
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        session = Session(
            session_id="sess-1",
            computer_name="TestMac",
            tmux_session_name="tmux-1",
            origin_adapter="telegram",
            title="TeleClaude: $TestMac - New session (2)",
            closed=False,
        )

        with patch("teleclaude.daemon.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()

            await daemon._update_session_title("sess-1", "Add dark mode")

            mock_db.update_session.assert_called_once_with("sess-1", title="TeleClaude: $TestMac - Add dark mode")

    async def test_update_session_title_skips_already_updated(self):
        """Title should NOT update when already has LLM-generated title."""
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        session = Session(
            session_id="sess-1",
            computer_name="TestMac",
            tmux_session_name="tmux-1",
            origin_adapter="telegram",
            title="TeleClaude: $TestMac - Fix login bug",  # Already updated
            closed=False,
        )

        with patch("teleclaude.daemon.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()

            await daemon._update_session_title("sess-1", "Different Title")

            # Should NOT update - title was already set
            mock_db.update_session.assert_not_called()
