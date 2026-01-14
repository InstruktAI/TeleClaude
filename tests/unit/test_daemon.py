"""Unit tests for daemon.py core logic."""

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude import config as config_module
from teleclaude.core.events import CommandEventContext, TeleClaudeEvents, VoiceEventContext
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
        patch("teleclaude.core.terminal_io.terminal_bridge", mock_tb),
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
    captured: dict[str, object] = {}  # guard: loose-dict - capture args for assertions

    async def fake_handler(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return {"status": "success"}

    with patch("teleclaude.daemon.command_handlers.handle_get_session_data", new=fake_handler):
        await daemon.handle_command(
            TeleClaudeEvents.GET_SESSION_DATA,
            ["2000"],
            context,
            MessageMetadata(adapter_type="redis"),
        )

    assert captured["kwargs"] == {}
    call_args = captured["args"]
    assert call_args[0] is context
    assert call_args[1] is None
    assert call_args[2] is None
    assert call_args[3] == 2000


@pytest.mark.asyncio
async def test_handle_voice_forwards_message_without_message_id() -> None:
    """Voice transcription should forward message without triggering pre-handler cleanup."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.handle_event = AsyncMock()
    daemon.client.delete_message = AsyncMock()
    daemon._send_status_callback = AsyncMock()

    with (
        patch("teleclaude.daemon.voice_message_handler.handle_voice", new_callable=AsyncMock) as mock_handle,
        patch("teleclaude.daemon.db") as mock_db,
    ):
        mock_handle.return_value = "hello world"
        session = MagicMock()
        mock_db.get_session = AsyncMock(return_value=session)

        context = VoiceEventContext(
            session_id="sess-123",
            file_path="/tmp/voice.ogg",
            duration=None,
            message_id="321",
            message_thread_id=123,
            adapter_type="telegram",
        )

        await daemon._handle_voice("voice", context)

        daemon.client.handle_event.assert_called_once()
        daemon.client.delete_message.assert_called_once_with(session, "321")
        call_kwargs = daemon.client.handle_event.call_args.kwargs
        assert call_kwargs["event"] == TeleClaudeEvents.MESSAGE
        assert call_kwargs["payload"].get("message_id") is None


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


@pytest.mark.asyncio
async def test_agent_then_message_waits_for_stabilization():
    """agent_then_message should wait for TUI to stabilize before injecting message."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()

    call_order: list[str] = []

    async def mock_wait_stable(*_args: object, **_kwargs: object) -> tuple[bool, str]:
        call_order.append("wait_for_stable")
        return True, "stable output"

    async def mock_send_text(*_args: object, **_kwargs: object) -> bool:
        call_order.append("inject_message")
        return True

    async def mock_confirm(*_args: object, **_kwargs: object) -> bool:
        call_order.append("confirm_acceptance")
        return True

    with (
        patch("teleclaude.daemon.command_handlers.handle_agent_start", new_callable=AsyncMock),
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.terminal_io.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.terminal_io.send_text", new_callable=AsyncMock) as mock_send,
        patch.object(TeleClaudeDaemon, "_wait_for_output_stable", mock_wait_stable),
        patch.object(TeleClaudeDaemon, "_confirm_command_acceptance", mock_confirm),
        # Patch delays to make test fast
        patch("teleclaude.daemon.AGENT_START_SETTLE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_STABILIZE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_INJECT_DELAY_S", 0),
        patch("teleclaude.daemon.GEMINI_START_EXTRA_DELAY_S", 0),
    ):
        mock_running.return_value = True
        mock_send.side_effect = mock_send_text
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", working_directory=".", active_agent="gemini")
        )
        mock_db.update_session = AsyncMock()
        mock_db.update_last_activity = AsyncMock()

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["gemini", "slow", "/prime-architect"],
        )

        assert result["status"] == "success"
        # Verify order: stabilize -> inject -> confirm
        assert call_order == ["wait_for_stable", "inject_message", "confirm_acceptance"]
        mock_db.update_session.assert_called_with("sess-123", last_message_sent="/prime-architect")


@pytest.mark.asyncio
async def test_agent_then_message_applies_gemini_delay():
    """Gemini sessions wait for extra delay before injection."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()

    async def mock_wait_stable(*_args: object, **_kwargs: object) -> tuple[bool, str]:
        return True, "stable output"

    async def mock_confirm(*_args: object, **_kwargs: object) -> bool:
        return True

    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    with (
        patch("teleclaude.daemon.command_handlers.handle_agent_start", new_callable=AsyncMock),
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.terminal_io.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.terminal_io.send_text", new_callable=AsyncMock, return_value=True),
        patch.object(TeleClaudeDaemon, "_wait_for_output_stable", mock_wait_stable),
        patch.object(TeleClaudeDaemon, "_confirm_command_acceptance", mock_confirm),
        patch("teleclaude.daemon.asyncio.sleep", new=mock_sleep),
        patch("teleclaude.daemon.AGENT_START_SETTLE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_STABILIZE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_INJECT_DELAY_S", 0),
        patch("teleclaude.daemon.GEMINI_START_EXTRA_DELAY_S", 3.0),
    ):
        mock_running.return_value = True
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", working_directory=".", active_agent="gemini")
        )
        mock_db.update_session = AsyncMock()
        mock_db.update_last_activity = AsyncMock()

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["gemini", "slow", "/prime-architect"],
        )

        assert result["status"] == "success"
        assert 3.0 in sleep_calls, "Expected gemini extra delay to be applied"


@pytest.mark.asyncio
async def test_execute_auto_command_updates_last_message_sent():
    """Auto-command should update last_message_sent in session."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()

    with (
        patch("teleclaude.daemon.command_handlers.handle_agent_start", new_callable=AsyncMock),
        patch("teleclaude.daemon.db") as mock_db,
    ):
        mock_db.update_session = AsyncMock()

        await daemon._execute_auto_command("sess-456", "agent codex fast")

        mock_db.update_session.assert_called_with("sess-456", last_message_sent="agent codex fast")


@pytest.mark.asyncio
async def test_agent_then_message_proceeds_after_stabilization_timeout():
    """agent_then_message should proceed even if stabilization times out."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()

    async def mock_wait_stable(*_args: object, **_kwargs: object) -> tuple[bool, str]:
        # Simulate stabilization timeout
        return False, "still changing"

    async def mock_confirm(*_args: object, **_kwargs: object) -> bool:
        return True

    with (
        patch("teleclaude.daemon.command_handlers.handle_agent_start", new_callable=AsyncMock),
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.terminal_io.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.terminal_io.send_text", new_callable=AsyncMock) as mock_send,
        patch.object(TeleClaudeDaemon, "_wait_for_output_stable", mock_wait_stable),
        patch.object(TeleClaudeDaemon, "_confirm_command_acceptance", mock_confirm),
        # Patch delays to make test fast
        patch("teleclaude.daemon.AGENT_START_SETTLE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_STABILIZE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_INJECT_DELAY_S", 0),
    ):
        mock_running.return_value = True
        mock_send.return_value = True
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", working_directory=".", active_agent="claude")
        )
        mock_db.update_session = AsyncMock()
        mock_db.update_last_activity = AsyncMock()

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["claude", "slow", "/next-work"],
        )

        # Should still succeed - stabilization timeout is not fatal
        assert result["status"] == "success"


@pytest.mark.asyncio
async def test_agent_then_message_fails_on_command_acceptance_timeout():
    """agent_then_message should fail if command acceptance times out."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()

    async def mock_wait_stable(*_args: object, **_kwargs: object) -> tuple[bool, str]:
        return True, "stable output"

    async def mock_confirm(*_args: object, **_kwargs: object) -> bool:
        return False  # Simulate timeout

    with (
        patch("teleclaude.daemon.command_handlers.handle_agent_start", new_callable=AsyncMock),
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.terminal_io.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.terminal_io.send_text", new_callable=AsyncMock) as mock_send,
        patch.object(TeleClaudeDaemon, "_wait_for_output_stable", mock_wait_stable),
        patch.object(TeleClaudeDaemon, "_confirm_command_acceptance", mock_confirm),
        # Patch delays to make test fast
        patch("teleclaude.daemon.AGENT_START_SETTLE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_STABILIZE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_INJECT_DELAY_S", 0),
    ):
        mock_running.return_value = True
        mock_send.return_value = True
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", working_directory=".", active_agent="claude")
        )
        mock_db.update_session = AsyncMock()
        mock_db.update_last_activity = AsyncMock()

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["claude", "slow", "/next-work"],
        )

        assert result["status"] == "error"
        assert "Timeout waiting for command acceptance" in result["message"]


@pytest.mark.asyncio
async def test_restart_mcp_server_replaces_task():
    """Test that restarting MCP server replaces the running task."""
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


@pytest.mark.asyncio
async def test_check_mcp_socket_health_uses_snapshot():
    """Test that MCP socket health uses snapshot without probing when fresh."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.mcp_server = MagicMock()
    daemon.mcp_server.health_snapshot = AsyncMock(
        return_value={
            "is_serving": True,
            "socket_exists": True,
            "active_connections": 0,
            "last_accept_age_s": 1.0,
        }
    )
    daemon._mcp_restart_lock = asyncio.Lock()
    daemon._last_mcp_restart_at = 0.0
    daemon._last_mcp_probe_at = 0.0

    with patch("teleclaude.daemon.asyncio.open_unix_connection", new_callable=AsyncMock) as mock_open:
        healthy = await TeleClaudeDaemon._check_mcp_socket_health(daemon)

    assert healthy is True
    mock_open.assert_not_called()


@pytest.mark.asyncio
async def test_check_mcp_socket_health_probes_when_accept_stale_with_active_connections():
    """Test that MCP socket health probes when accepts are stale with connections."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.mcp_server = MagicMock()
    daemon.mcp_server.health_snapshot = AsyncMock(
        return_value={
            "is_serving": True,
            "socket_exists": True,
            "active_connections": 2,
            "last_accept_age_s": 999.0,
        }
    )
    daemon._mcp_restart_lock = asyncio.Lock()
    daemon._last_mcp_restart_at = 0.0
    daemon._last_mcp_probe_at = 0.0

    dummy_writer = MagicMock()
    dummy_writer.close = MagicMock()
    dummy_writer.wait_closed = AsyncMock()

    with patch(
        "teleclaude.daemon.asyncio.open_unix_connection",
        new_callable=AsyncMock,
        return_value=(AsyncMock(), dummy_writer),
    ) as mock_open:
        healthy = await TeleClaudeDaemon._check_mcp_socket_health(daemon)

    assert healthy is True
    mock_open.assert_called_once()
    dummy_writer.close.assert_called_once()
    dummy_writer.wait_closed.assert_called_once()


@pytest.mark.asyncio
async def test_check_mcp_socket_health_returns_unhealthy_within_probe_interval_after_failure():
    """Test that recent probe failure suppresses immediate re-probe."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.mcp_server = MagicMock()
    daemon.mcp_server.health_snapshot = AsyncMock(
        return_value={
            "is_serving": True,
            "socket_exists": True,
            "active_connections": 1,
            "last_accept_age_s": 999.0,
        }
    )
    daemon._mcp_restart_lock = asyncio.Lock()
    daemon._last_mcp_restart_at = 0.0
    daemon._last_mcp_probe_at = 123.0
    daemon._last_mcp_probe_ok = False

    with (
        patch("teleclaude.daemon.asyncio.get_running_loop") as mock_loop,
        patch("teleclaude.daemon.asyncio.open_unix_connection", new_callable=AsyncMock) as mock_open,
    ):
        mock_loop.return_value.time.return_value = 123.5
        healthy = await TeleClaudeDaemon._check_mcp_socket_health(daemon)

    assert healthy is False
    mock_open.assert_not_called()


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

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.send_feedback = AsyncMock()
    daemon.client.send_output_update = AsyncMock()
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

    mock_session = MagicMock()
    mock_session.active_agent = "gemini"
    mock_session.native_log_file = "/tmp/native.json"

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.summarize", new_callable=AsyncMock) as mock_summarize,
    ):
        mock_db.update_session = AsyncMock()
        mock_db.get_session = AsyncMock(return_value=mock_session)
        mock_summarize.return_value = ("title", "summary")

        await daemon._process_agent_stop(context)

        mock_summarize.assert_awaited_once_with(AgentName.GEMINI, "/tmp/native.json")


@pytest.mark.asyncio
async def test_process_agent_stop_sets_native_session_id_from_payload():
    """Agent STOP should persist native_session_id when provided."""
    from teleclaude.core.agents import AgentName
    from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.send_feedback = AsyncMock()
    daemon.client.send_output_update = AsyncMock()
    daemon.agent_coordinator = MagicMock()
    daemon.agent_coordinator.handle_stop = AsyncMock()
    daemon._update_session_title = AsyncMock()
    daemon._last_stop_time = {}
    daemon._stop_debounce_seconds = 5.0

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/tmp/native.json",
        raw={},
    )
    context = AgentEventContext(session_id="tele-123", event_type=AgentHookEvents.AGENT_STOP, data=payload)

    mock_session = MagicMock()
    mock_session.active_agent = "gemini"
    mock_session.native_log_file = "/tmp/native.json"

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.summarize", new_callable=AsyncMock) as mock_summarize,
    ):
        updates: list[tuple[str, dict[str, object]]] = []  # guard: loose-dict - capture update payloads

        async def record_update(session_id: str, **kwargs):
            updates.append((session_id, kwargs))

        mock_db.update_session = AsyncMock(side_effect=record_update)
        mock_db.get_session = AsyncMock(return_value=mock_session)
        mock_summarize.return_value = ("title", "summary")

        await daemon._process_agent_stop(context)

        native_call_found = any(
            session_id == "tele-123" and kwargs.get("native_session_id") == "native-123"
            for session_id, kwargs in updates
        )
        assert native_call_found, f"Expected native_session_id call, got: {updates}"
        mock_summarize.assert_awaited_once_with(AgentName.GEMINI, "/tmp/native.json")


@pytest.mark.asyncio
async def test_process_agent_stop_sets_active_agent_from_payload():
    """Agent STOP should set active_agent from hook payload when missing."""
    from teleclaude.core.agents import AgentName
    from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.send_message = AsyncMock()
    daemon.agent_coordinator = MagicMock()
    daemon.agent_coordinator.handle_stop = AsyncMock()
    daemon._update_session_title = AsyncMock()
    daemon._last_stop_time = {}
    daemon._stop_debounce_seconds = 0.0

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/tmp/native.json",
        raw={"agent_name": "claude"},
    )
    context = AgentEventContext(session_id="tele-123", event_type=AgentHookEvents.AGENT_STOP, data=payload)

    session_missing_agent = MagicMock()
    session_missing_agent.active_agent = None
    session_missing_agent.native_log_file = "/tmp/native.json"

    session_with_agent = MagicMock()
    session_with_agent.active_agent = "claude"
    session_with_agent.native_log_file = "/tmp/native.json"

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.summarize", new_callable=AsyncMock) as mock_summarize,
    ):
        mock_db.update_session = AsyncMock()
        mock_db.get_session = AsyncMock(side_effect=[session_missing_agent, session_with_agent, session_with_agent])
        mock_summarize.return_value = ("title", "summary")

        await daemon._process_agent_stop(context)

        call_args_list = mock_db.update_session.await_args_list
        active_call_found = any(
            c.args == ("tele-123",) and c.kwargs.get("active_agent") == "claude" for c in call_args_list
        )
        assert active_call_found, f"Expected active_agent call, got: {call_args_list}"
        mock_summarize.assert_awaited_once_with(AgentName.CLAUDE, "/tmp/native.json")


@pytest.mark.asyncio
async def test_process_agent_stop_skips_without_agent_metadata():
    """Agent STOP should skip gracefully when active_agent and payload agent are missing."""
    from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.send_message = AsyncMock()
    daemon.agent_coordinator = MagicMock()
    daemon.agent_coordinator.handle_stop = AsyncMock()
    daemon._update_session_title = AsyncMock()
    daemon._last_stop_time = {}
    daemon._stop_debounce_seconds = 0.0

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/tmp/native.json",
        raw={},
    )
    context = AgentEventContext(session_id="tele-123", event_type=AgentHookEvents.AGENT_STOP, data=payload)

    session_missing_agent = MagicMock()
    session_missing_agent.active_agent = None
    session_missing_agent.native_log_file = "/tmp/native.json"

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.summarize", new_callable=AsyncMock) as mock_summarize,
    ):
        mock_db.update_session = AsyncMock()
        mock_db.get_session = AsyncMock(return_value=session_missing_agent)

        await daemon._process_agent_stop(context)

        mock_db.update_session.assert_not_awaited()
        mock_summarize.assert_not_awaited()
        daemon.agent_coordinator.handle_stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_process_agent_stop_does_not_seed_transcript_output():
    """Agent STOP should not seed transcript output in tmux-only mode."""
    from teleclaude.core.agents import AgentName
    from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload
    from teleclaude.core.models import Session, SessionAdapterMetadata, TelegramAdapterMetadata

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.send_feedback = AsyncMock()
    daemon.client.send_output_update = AsyncMock()
    daemon.agent_coordinator = MagicMock()
    daemon.agent_coordinator.handle_stop = AsyncMock()
    daemon._update_session_title = AsyncMock()
    daemon._last_stop_time = {}
    daemon._stop_debounce_seconds = 0.0

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/tmp/native.json",
        raw={},
    )
    context = AgentEventContext(session_id="tele-123", event_type=AgentHookEvents.AGENT_STOP, data=payload)

    session = Session(
        session_id="tele-123",
        computer_name="TestMac",
        tmux_session_name="terminal:abc",
        origin_adapter="rest",
        title="Test session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=123, output_message_id="24419")
        ),
        active_agent="gemini",
        native_log_file="/tmp/native.json",
        tui_capture_started=False,
    )

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.summarize", new_callable=AsyncMock) as mock_summarize,
    ):
        mock_db.update_session = AsyncMock()
        mock_db.get_session = AsyncMock(return_value=session)
        mock_summarize.return_value = ("title", "summary")

        await daemon._process_agent_stop(context)

        mock_summarize.assert_awaited_once_with(AgentName.GEMINI, "/tmp/native.json")
        assert daemon.client.send_output_update.await_count == 0


@pytest.mark.asyncio
class TestSessionCleanup:
    """Test session cleanup functionality."""

    async def test_cleanup_inactive_sessions_cleans_old_sessions(self):
        """Test cleanup of sessions inactive for 72+ hours."""
        from datetime import datetime, timedelta, timezone
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        # Create daemon instance
        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
        daemon.client = MagicMock()

        # Create session inactive for 73 hours
        old_time = datetime.now(timezone.utc) - timedelta(hours=73)
        inactive_session = Session(
            session_id="inactive-123",
            computer_name="TestMac",
            tmux_session_name="inactive-tmux",
            origin_adapter="telegram",
            title="Inactive",
            last_activity=old_time,
        )

        with (
            patch("teleclaude.daemon.db") as mock_db,
            patch("teleclaude.daemon.session_cleanup.terminate_session", new_callable=AsyncMock) as terminate_session,
        ):
            mock_db.list_sessions = AsyncMock(return_value=[inactive_session])

            # Execute cleanup
            await daemon._cleanup_inactive_sessions()

            terminate_session.assert_called_once_with(
                "inactive-123",
                daemon.client,
                reason="inactive_72h",
                session=inactive_session,
            )

    async def test_cleanup_skips_recently_active_sessions(self):
        """Test that recently active sessions are not cleaned up."""
        from datetime import datetime, timedelta
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
        daemon.client = MagicMock()

        # Session active 1 hour ago
        recent_time = datetime.now() - timedelta(hours=1)
        active_session = Session(
            session_id="active-456",
            computer_name="TestMac",
            tmux_session_name="active-tmux",
            origin_adapter="telegram",
            title="Active",
            last_activity=recent_time,
        )

        with (
            patch("teleclaude.daemon.db") as mock_db,
            patch("teleclaude.daemon.session_cleanup.terminate_session", new_callable=AsyncMock) as terminate_session,
        ):
            mock_db.list_sessions = AsyncMock(return_value=[active_session])

            # Execute cleanup
            await daemon._cleanup_inactive_sessions()

            # Verify NO cleanup
            terminate_session.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_hook_event_updates_tty_before_polling():
    """TTY metadata should be stored before terminal polling starts."""
    from unittest.mock import AsyncMock, patch

    from teleclaude.core.models import Session
    from teleclaude.daemon import TeleClaudeDaemon

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.create_channel = AsyncMock()
    daemon.client.handle_event = AsyncMock(return_value=None)
    daemon._ensure_output_polling = AsyncMock()

    session = Session(
        session_id="sess-tty",
        computer_name="TestMac",
        tmux_session_name="terminal:deadbeef",
        origin_adapter="rest",
        title="TeleClaude: $TestMac - Terminal",
    )

    call_order: list[str] = []

    async def record_update(*_args, **_kwargs):
        call_order.append("update")

    async def record_poll(*_args, **_kwargs):
        call_order.append("poll")

    daemon._ensure_output_polling = AsyncMock(side_effect=record_poll)

    with patch("teleclaude.daemon.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock(side_effect=record_update)

        await daemon._dispatch_hook_event(
            session_id="sess-tty",
            event_type="stop",
            data={"teleclaude_pid": 123, "teleclaude_tty": "/dev/ttys001", "transcript_path": "/tmp/x.json"},
        )

    assert "poll" in call_order
    assert call_order.index("poll") > max(i for i, v in enumerate(call_order) if v == "update")


@pytest.mark.asyncio
async def test_ensure_output_polling_uses_tmux():
    """Sessions should use tmux polling when tmux exists."""
    from unittest.mock import AsyncMock, patch

    from teleclaude.core.models import Session
    from teleclaude.daemon import TeleClaudeDaemon

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon._poll_and_send_output = AsyncMock()
    daemon.client = MagicMock()
    daemon.client.create_channel = AsyncMock()

    session = Session(
        session_id="sess-term",
        computer_name="TestMac",
        tmux_session_name="telec_1234",
        origin_adapter="rest",
        title="TeleClaude: $TestMac - Terminal",
    )

    with (
        patch("teleclaude.daemon.polling_coordinator.is_polling", new=AsyncMock(return_value=False)),
        patch("teleclaude.daemon.terminal_bridge.session_exists", new=AsyncMock(return_value=True)),
    ):
        await daemon._ensure_output_polling(session)

    daemon._poll_and_send_output.assert_called_once_with(session.session_id, session.tmux_session_name)


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
        """Title should update when description is 'Untitled'."""
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        session = Session(
            session_id="sess-1",
            computer_name="TestMac",
            tmux_session_name="tmux-1",
            origin_adapter="telegram",
            title="TeleClaude: $TestMac - Untitled",
        )

        with patch("teleclaude.daemon.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            updates: list[tuple[str, dict[str, object]]] = []  # guard: loose-dict - capture update payloads

            async def record_update(session_id: str, **kwargs):
                updates.append((session_id, kwargs))

            mock_db.update_session = AsyncMock(side_effect=record_update)

            await daemon._update_session_title("sess-1", "Fix login bug")

            assert updates == [("sess-1", {"title": "TeleClaude: $TestMac - Fix login bug"})]

    async def test_update_session_title_updates_new_session_with_counter(self):
        """Title should update when title is 'Untitled (N)'."""
        from unittest.mock import AsyncMock, patch

        from teleclaude.core.models import Session
        from teleclaude.daemon import TeleClaudeDaemon

        daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)

        session = Session(
            session_id="sess-1",
            computer_name="TestMac",
            tmux_session_name="tmux-1",
            origin_adapter="telegram",
            title="TeleClaude: $TestMac - Untitled (2)",
        )

        with patch("teleclaude.daemon.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            updates: list[tuple[str, dict[str, object]]] = []  # guard: loose-dict - capture update payloads

            async def record_update(session_id: str, **kwargs):
                updates.append((session_id, kwargs))

            mock_db.update_session = AsyncMock(side_effect=record_update)

            await daemon._update_session_title("sess-1", "Add dark mode")

            assert updates == [("sess-1", {"title": "TeleClaude: $TestMac - Add dark mode"})]

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
        )

        with patch("teleclaude.daemon.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()

            await daemon._update_session_title("sess-1", "Different Title")

            # Should NOT update - title was already set
            assert mock_db.update_session.await_count == 0
