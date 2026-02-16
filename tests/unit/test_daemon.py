"""Unit tests for daemon.py core logic."""

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
from typing_extensions import TypedDict

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude import config as config_module
from teleclaude.core.agent_coordinator import AgentCoordinator
from teleclaude.core.command_mapper import CommandMapper
from teleclaude.core.command_service import CommandService
from teleclaude.core.events import (
    AgentEventContext,
    AgentHookEvents,
    AgentStopPayload,
    TeleClaudeEvents,
    UserPromptSubmitPayload,
)
from teleclaude.core.models import (
    Session,
    SessionAdapterMetadata,
    TelegramAdapterMetadata,
)
from teleclaude.daemon import TeleClaudeDaemon
from teleclaude.services.maintenance_service import MaintenanceService
from teleclaude.types.commands import CreateSessionCommand, GetSessionDataCommand


class SessionUpdate(TypedDict, total=False):
    last_message_sent: str
    last_input_origin: str


@pytest.fixture
def mock_daemon():
    """Create a mocked daemon for testing."""
    with (
        patch("teleclaude.daemon.Db") as mock_sm,
        patch("teleclaude.core.tmux_bridge") as mock_tb,
        patch("teleclaude.core.message_handler.tmux_bridge", mock_tb),
        patch("teleclaude.core.voice_message_handler.tmux_bridge", mock_tb),
        patch("teleclaude.core.tmux_io.tmux_bridge", mock_tb),
        patch("teleclaude.daemon.TelegramAdapter") as mock_ta,
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

        # Initialize global config (critical for tmux_bridge and other modules)
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

        # Mock tmux_bridge (patched at core level for all modules)
        mock_tb.send_keys = AsyncMock(return_value=True)
        mock_tb.send_signal = AsyncMock(return_value=True)
        mock_tb.send_escape = AsyncMock(return_value=True)
        mock_tb.capture_pane = AsyncMock(return_value="")
        mock_tb.kill_session = AsyncMock(return_value=True)
        mock_tb.list_sessions = AsyncMock(return_value=[])

        # Make tmux_bridge accessible as daemon.terminal for tests
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

        # Mock mcp_server (Phase 1 MCP support)
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
    """get_session_data should parse numeric tail_chars directly."""
    cmd = CommandMapper.map_redis_input("get_session_data 2000", session_id="sess-123", origin=InputOrigin.REDIS.value)
    assert isinstance(cmd, GetSessionDataCommand)
    assert cmd.session_id == "sess-123"
    assert cmd.since_timestamp is None
    assert cmd.until_timestamp is None
    assert cmd.tail_chars == 2000


@pytest.mark.asyncio
async def test_get_session_data_supports_dash_placeholders():
    """GET_SESSION_DATA should treat '-' as an explicit empty placeholder."""
    cmd = CommandMapper.map_redis_input(
        "get_session_data - 2026-01-01T00:00:00Z 2000",
        session_id="sess-123",
        origin=InputOrigin.REDIS.value,
    )
    assert isinstance(cmd, GetSessionDataCommand)
    assert cmd.session_id == "sess-123"
    assert cmd.since_timestamp is None
    assert cmd.until_timestamp == "2026-01-01T00:00:00Z"
    assert cmd.tail_chars == 2000


def test_hook_outbox_extra_data_decode_error_is_not_retryable() -> None:
    """Deterministic parser-format mismatches must not be retried forever."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    exc = json.JSONDecodeError("Extra data", '{"a":1}\n{"b":2}', 7)
    assert daemon._is_retryable_hook_error(exc) is False


def test_hook_outbox_other_decode_errors_remain_retryable() -> None:
    """Non-deterministic JSON parse failures may be transient and should retry."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    exc = json.JSONDecodeError("Expecting value", "", 0)
    assert daemon._is_retryable_hook_error(exc) is True


@pytest.mark.asyncio
async def test_dispatch_hook_event_updates_active_agent_from_payload() -> None:
    """Hook payload agent identity should refresh stale session active_agent metadata."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon._ensure_output_polling = AsyncMock()
    daemon._handle_agent_event = AsyncMock()

    session = Session(
        session_id="sess-123",
        computer_name="macbook",
        tmux_session_name="",
        title="Untitled",
        active_agent="gemini",
    )

    payload = {
        "agent_name": "claude",
        "session_id": "native-123",
        "native_session_id": "native-123",
        "transcript_path": "/tmp/transcript.jsonl",
    }

    with (
        patch("teleclaude.daemon.db.get_session", new=AsyncMock(return_value=session)),
        patch("teleclaude.daemon.db.update_session", new_callable=AsyncMock) as mock_update,
    ):
        await daemon._dispatch_hook_event("sess-123", AgentHookEvents.TOOL_DONE, payload)

    assert mock_update.await_count >= 1
    first_kwargs = mock_update.await_args_list[0].kwargs
    assert first_kwargs.get("active_agent") == "claude"


@pytest.mark.asyncio
async def test_enrich_with_summary_dedupes_transcript() -> None:
    """AgentCoordinator should extract and summarize agent output from payload transcript."""
    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )
    session = MagicMock()
    session.native_log_file = None
    session.active_agent = "codex"

    payload = AgentStopPayload(
        transcript_path="/tmp/transcript.jsonl",
        raw={"agent_name": "codex"},
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new=AsyncMock(return_value=session)),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message", return_value="raw output"),
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock) as mock_sum,
    ):
        raw = await coordinator._extract_agent_output("sess-123", payload)

    assert raw == "raw output"


@pytest.mark.asyncio
async def test_extract_agent_output_falls_back_to_native_session() -> None:
    """AgentCoordinator should fall back to session transcript when payload omits it."""
    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )
    session = MagicMock()
    session.native_log_file = "/tmp/transcript.jsonl"
    session.active_agent = "codex"

    payload = AgentStopPayload(transcript_path=None, raw={"agent_name": "codex"})

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new=AsyncMock(return_value=session)),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message", return_value="raw output"),
    ):
        raw = await coordinator._extract_agent_output("sess-123", payload)

    assert raw == "raw output"


@pytest.mark.asyncio
async def test_extract_agent_output_returns_none_for_whitespace_only_message() -> None:
    """AgentCoordinator should reject whitespace-only extracted assistant output."""
    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )
    session = MagicMock()
    session.native_log_file = "/tmp/transcript.jsonl"
    session.active_agent = "codex"

    payload = AgentStopPayload(transcript_path=None, raw={"agent_name": "codex"})

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new=AsyncMock(return_value=session)),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message", return_value=" \n\t "),
    ):
        raw = await coordinator._extract_agent_output("sess-123", payload)

    assert raw is None


@pytest.mark.asyncio
async def test_new_session_auto_command_agent_then_message():
    """Auto-command agent_then_message starts agent then injects message."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()
    daemon.command_service = MagicMock()
    daemon.command_service.start_agent = AsyncMock()
    daemon.command_service = MagicMock()
    daemon.command_service.start_agent = AsyncMock()
    daemon._execute_auto_command = AsyncMock(return_value={"status": "success"})
    daemon._queue_background_task = MagicMock(side_effect=lambda coro, _label: coro.close())
    daemon.command_service = CommandService(
        client=daemon.client,
        start_polling=AsyncMock(),
        execute_terminal_command=daemon._execute_terminal_command,
        execute_auto_command=daemon._execute_auto_command,
        queue_background_task=daemon._queue_background_task,
        bootstrap_session=AsyncMock(),
    )

    with patch("teleclaude.core.command_service.create_session", new_callable=AsyncMock) as mock_create:
        mock_create.return_value = {"session_id": "sess-123", "auto_command_status": "queued"}

        create_cmd = CreateSessionCommand(
            project_path="/tmp",
            origin=InputOrigin.API.value,
            auto_command="agent_then_message codex slow /next-review next-machine",
        )

        result = await daemon.command_service.create_session(create_cmd)

        assert result["session_id"] == "sess-123"
        assert result["auto_command_status"] == "queued"


@pytest.mark.asyncio
async def test_agent_then_message_waits_for_stabilization():
    """agent_then_message should wait for TUI to stabilize before injecting message."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()
    daemon.command_service = MagicMock()
    daemon.command_service.start_agent = AsyncMock()

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
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.tmux_io.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.tmux_io.process_text", new_callable=AsyncMock) as mock_send,
        patch.object(TeleClaudeDaemon, "_wait_for_output_stable", mock_wait_stable),
        patch.object(TeleClaudeDaemon, "_confirm_command_acceptance", mock_confirm),
        # Patch delays to make test fast
        patch("teleclaude.daemon.AGENT_START_SETTLE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_STABILIZE_DELAY_S", 0),
        patch("teleclaude.daemon.AGENT_START_POST_INJECT_DELAY_S", 0),
        patch("teleclaude.daemon.GEMINI_START_EXTRA_DELAY_S", 0),
    ):
        updates: list[tuple[str, SessionUpdate]] = []

        async def record_update(session_id: str, **kwargs: object) -> None:
            updates.append((session_id, cast(SessionUpdate, kwargs)))

        mock_running.return_value = True
        mock_send.side_effect = mock_send_text
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", project_path=".", active_agent="gemini")
        )
        mock_db.update_session = AsyncMock(side_effect=record_update)
        mock_db.update_last_activity = AsyncMock()

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["gemini", "slow", "/prime-orchestrator"],
        )

        assert result["status"] == "success"
        # Verify order: stabilize -> inject -> confirm
        assert call_order == ["wait_for_stable", "inject_message", "confirm_acceptance"]
        assert any(
            session_id == "sess-123" and kwargs.get("last_message_sent") == "/prime-orchestrator"
            for session_id, kwargs in updates
        )


@pytest.mark.asyncio
async def test_agent_then_message_applies_gemini_delay():
    """Gemini sessions wait for extra delay before injection via quiet window."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()
    daemon.command_service = MagicMock()
    daemon.command_service.start_agent = AsyncMock()

    captured_args = {}

    async def mock_wait_stable(self, session, timeout_s, quiet_s) -> tuple[bool, str]:
        captured_args["quiet_s"] = quiet_s
        return True, "stable output"

    async def mock_confirm(*_args: object, **_kwargs: object) -> bool:
        return True

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.tmux_io.process_text", new_callable=AsyncMock, return_value=True),
        patch("teleclaude.daemon.tmux_io.is_process_running", new_callable=AsyncMock, return_value=True),
        patch.object(TeleClaudeDaemon, "_wait_for_output_stable", mock_wait_stable),
        patch.object(TeleClaudeDaemon, "_confirm_command_acceptance", mock_confirm),
        patch("teleclaude.daemon.AGENT_START_STABILIZE_QUIET_S", 1.0),
        patch("teleclaude.daemon.GEMINI_START_EXTRA_DELAY_S", 3.0),
    ):
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", project_path=".", active_agent="gemini")
        )
        mock_db.update_session = AsyncMock()
        mock_db.update_last_activity = AsyncMock()

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["gemini", "slow", "/prime-orchestrator"],
        )

        assert result["status"] == "success"
        # Should be STABILIZE_QUIET_S (1.0) + EXTRA_DELAY_S (3.0)
        assert captured_args["quiet_s"] == 4.0, f"Expected quiet_s to be 4.0, got {captured_args.get('quiet_s')}"


@pytest.mark.asyncio
async def test_agent_then_message_normalizes_codex_next_commands() -> None:
    """agent_then_message should normalize Codex /next-* commands before injection."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()
    daemon.command_service = MagicMock()
    daemon.command_service.start_agent = AsyncMock()

    async def mock_wait_stable(*_args: object, **_kwargs: object) -> tuple[bool, str]:
        return True, "stable output"

    async def mock_confirm(*_args: object, **_kwargs: object) -> bool:
        return True

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.tmux_io.process_text", new_callable=AsyncMock, return_value=True) as mock_send,
        patch("teleclaude.daemon.tmux_io.is_process_running", new_callable=AsyncMock, return_value=True),
        patch.object(TeleClaudeDaemon, "_wait_for_output_stable", mock_wait_stable),
        patch.object(TeleClaudeDaemon, "_confirm_command_acceptance", mock_confirm),
    ):
        mock_db.get_session = AsyncMock(
            return_value=MagicMock(tmux_session_name="tc_123", project_path=".", active_agent="codex")
        )
        mock_db.update_session = AsyncMock()
        mock_db.update_last_activity = AsyncMock()

        result = await daemon._handle_agent_then_message(
            "sess-123",
            ["codex", "slow", "/next-work test-todo"],
        )

        assert result["status"] == "success"
        sent_text = mock_send.await_args.args[1]
        assert sent_text == "/prompts:next-work test-todo"


@pytest.mark.asyncio
async def test_execute_auto_command_updates_last_message_sent():
    """Auto-command should update last_message_sent in session."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon.command_service = MagicMock()
    daemon.command_service.start_agent = AsyncMock()
    daemon.command_service.resume_agent = AsyncMock()

    with (
        patch("teleclaude.daemon.db") as mock_db,
    ):
        updates: list[tuple[str, SessionUpdate]] = []

        async def record_update(session_id: str, **kwargs: object) -> None:
            updates.append((session_id, cast(SessionUpdate, kwargs)))

        mock_db.get_session = AsyncMock(
            return_value=MagicMock(active_agent="codex", last_input_origin=InputOrigin.TELEGRAM.value)
        )
        mock_db.update_session = AsyncMock(side_effect=record_update)

        await daemon._execute_auto_command("sess-456", "agent codex fast")

        assert any(
            session_id == "sess-456"
            and kwargs.get("last_message_sent") == "agent codex fast"
            and kwargs.get("last_input_origin") == InputOrigin.TELEGRAM.value
            for session_id, kwargs in updates
        )


@pytest.mark.asyncio
async def test_agent_then_message_proceeds_after_stabilization_timeout():
    """agent_then_message should proceed even if stabilization times out."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._execute_terminal_command = AsyncMock()
    daemon._poll_and_send_output = AsyncMock()
    daemon.command_service = MagicMock()
    daemon.command_service.start_agent = AsyncMock()

    async def mock_wait_stable(*_args: object, **_kwargs: object) -> tuple[bool, str]:
        # Simulate stabilization timeout
        return False, "still changing"

    async def mock_confirm(*_args: object, **_kwargs: object) -> bool:
        return True

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.tmux_io.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.tmux_io.process_text", new_callable=AsyncMock) as mock_send,
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
            return_value=MagicMock(tmux_session_name="tc_123", project_path=".", active_agent="claude")
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
    daemon.command_service = MagicMock()
    daemon.command_service.start_agent = AsyncMock()

    async def mock_wait_stable(*_args: object, **_kwargs: object) -> tuple[bool, str]:
        return True, "stable output"

    async def mock_confirm(*_args: object, **_kwargs: object) -> bool:
        return False  # Simulate timeout

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.tmux_io.is_process_running", new_callable=AsyncMock) as mock_running,
        patch("teleclaude.daemon.tmux_io.process_text", new_callable=AsyncMock) as mock_send,
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
            return_value=MagicMock(tmux_session_name="tc_123", project_path=".", active_agent="claude")
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
    daemon._last_mcp_probe_at = 10.0
    daemon._last_mcp_probe_ok = False

    with patch("teleclaude.daemon.asyncio.open_unix_connection", new_callable=AsyncMock) as mock_open:
        healthy = await TeleClaudeDaemon._check_mcp_socket_health(daemon)

    assert healthy is True
    assert daemon._last_mcp_probe_at == 10.0
    assert daemon._last_mcp_probe_ok is False


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
    closed = {"close": False, "wait": False}

    def _close():
        closed["close"] = True

    async def _wait_closed():
        closed["wait"] = True

    with patch(
        "teleclaude.daemon.asyncio.open_unix_connection",
        new_callable=AsyncMock,
        return_value=(AsyncMock(), dummy_writer),
    ) as mock_open:
        dummy_writer.close = _close
        dummy_writer.wait_closed = _wait_closed
        healthy = await TeleClaudeDaemon._check_mcp_socket_health(daemon)

    assert healthy is True
    assert daemon._last_mcp_probe_ok is True
    assert daemon._last_mcp_probe_at > 0.0
    assert closed["close"] is True
    assert closed["wait"] is True


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
    assert daemon._last_mcp_probe_at == 123.0
    assert daemon._last_mcp_probe_ok is False


def test_summarize_output_change_reports_diff():
    """_summarize_output_change should report a diff index and snippets."""
    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    summary = daemon._summarize_output_change("hello", "hEllo")
    assert summary.changed is True
    assert summary.diff_index == 1
    assert summary.before_snippet is not None
    assert summary.after_snippet is not None


@pytest.mark.asyncio
async def test_process_agent_stop_uses_registered_transcript_when_payload_missing(tmp_path):
    """Agent stop extraction should use stored transcript path when payload omits it."""
    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )

    transcript_path = tmp_path / "native.json"
    transcript_path.write_text("log")

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="",
        raw={"agent_name": "gemini"},
    )

    mock_session = MagicMock()
    mock_session.active_agent = "gemini"
    mock_session.native_log_file = str(transcript_path)

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new=AsyncMock(return_value=mock_session)),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message", return_value="raw output"),
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock) as mock_summarize,
    ):
        raw = await coordinator._extract_agent_output("tele-123", payload)

    assert raw == "raw output"


@pytest.mark.asyncio
async def test_process_agent_stop_sets_native_session_id_from_payload(tmp_path):
    """Hook dispatch should persist native_session_id when provided."""

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._ensure_output_polling = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.handle_event = AsyncMock()
    daemon.agent_coordinator = mock_coordinator

    session = Session(
        session_id="tele-123",
        computer_name="TestMac",
        tmux_session_name="tmux-123",
        last_input_origin=InputOrigin.API.value,
        title="Test session",
    )

    updates: list[tuple[str, dict[str, object]]] = []  # guard: loose-dict - capture update payloads

    async def record_update(session_id: str, **kwargs):
        updates.append((session_id, kwargs))

    with patch("teleclaude.daemon.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock(side_effect=record_update)

        await daemon._dispatch_hook_event(
            session_id="tele-123",
            event_type="agent_stop",
            data={"native_session_id": "native-123"},
        )

    native_call_found = any(
        session_id == "tele-123" and kwargs.get("native_session_id") == "native-123" for session_id, kwargs in updates
    )
    assert native_call_found, f"Expected native_session_id call, got: {updates}"


@pytest.mark.asyncio
async def test_dispatch_hook_event_bootstraps_headless_codex_session_on_agent_stop():
    """Codex agent_stop events should materialize a missing headless session."""

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._ensure_output_polling = AsyncMock()
    daemon._handle_agent_event = AsyncMock()

    created_session = Session(
        session_id="tele-booted",
        computer_name="TestMac",
        tmux_session_name="",
        last_input_origin=InputOrigin.HOOK.value,
        title="Standalone",
        active_agent="codex",
    )

    with (
        patch.object(daemon, "_ensure_headless_session", AsyncMock(return_value=created_session)) as mock_ensure,
        patch("teleclaude.daemon.db") as mock_db,
    ):
        mock_db.get_session = AsyncMock(return_value=None)
        mock_db.update_session = AsyncMock()

        await daemon._dispatch_hook_event(
            session_id="tele-booted",
            event_type=AgentHookEvents.AGENT_STOP,
            data={
                "agent_name": "codex",
                "native_session_id": "native-123",
                "transcript_path": "/tmp/native.json",
            },
        )

    mock_ensure.assert_awaited_once_with(
        "tele-booted",
        {
            "agent_name": "codex",
            "native_session_id": "native-123",
            "transcript_path": "/tmp/native.json",
        },
    )
    assert daemon._handle_agent_event.await_count == 1


@pytest.mark.asyncio
async def test_dispatch_hook_event_ignores_unknown_non_codex_session():
    """Only codex agent_stop is allowed to bootstrap missing headless sessions."""

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._ensure_output_polling = AsyncMock()
    daemon._handle_agent_event = AsyncMock()

    with (
        patch.object(daemon, "_ensure_headless_session", AsyncMock()) as mock_ensure,
        patch("teleclaude.daemon.db") as mock_db,
    ):
        mock_db.get_session = AsyncMock(return_value=None)
        mock_db.update_session = AsyncMock()

        await daemon._dispatch_hook_event(
            session_id="tele-unknown",
            event_type=AgentHookEvents.AGENT_STOP,
            data={"agent_name": "claude", "native_session_id": "native-123"},
        )

    mock_ensure.assert_not_awaited()
    assert daemon._handle_agent_event.await_count == 0


@pytest.mark.asyncio
async def test_dispatch_hook_event_discovers_codex_transcript_in_worker():
    """Hook worker should resolve Codex transcript path (not receiver boundary)."""

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon._ensure_output_polling = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.handle_event = AsyncMock()
    daemon.agent_coordinator = mock_coordinator

    session = Session(
        session_id="tele-123",
        computer_name="TestMac",
        tmux_session_name="tmux-123",
        last_input_origin=InputOrigin.API.value,
        title="Test session",
    )

    updates: list[tuple[str, dict[str, object]]] = []  # guard: loose-dict - capture update payloads

    async def record_update(session_id: str, **kwargs):
        updates.append((session_id, kwargs))

    with (
        patch("teleclaude.daemon.db") as mock_db,
        patch("teleclaude.daemon.discover_codex_transcript_path", return_value="/tmp/codex.jsonl") as mock_discover,
    ):
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock(side_effect=record_update)

        await daemon._dispatch_hook_event(
            session_id="tele-123",
            event_type="agent_stop",
            data={"agent_name": "codex", "native_session_id": "native-123"},
        )

    assert mock_discover.call_count == 1
    transcript_call_found = any(
        session_id == "tele-123" and kwargs.get("native_log_file") == "/tmp/codex.jsonl"
        for session_id, kwargs in updates
    )
    assert transcript_call_found, f"Expected native_log_file update call, got: {updates}"


@pytest.mark.asyncio
async def test_process_agent_stop_sets_active_agent_from_payload(tmp_path):
    """Agent stop extraction should use payload agent_name when session is missing it."""
    from teleclaude.core.agents import AgentName

    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )

    transcript_path = tmp_path / "native.json"
    transcript_path.write_text("log")

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path=str(transcript_path),
        raw={"agent_name": "claude"},
    )

    session_missing_agent = MagicMock()
    session_missing_agent.active_agent = None
    session_missing_agent.native_log_file = str(transcript_path)

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new=AsyncMock(return_value=session_missing_agent)),
        patch(
            "teleclaude.core.agent_coordinator.extract_last_agent_message", return_value="raw output"
        ) as mock_extract,
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock) as mock_summarize,
    ):
        raw = await coordinator._extract_agent_output("tele-123", payload)

    assert raw == "raw output"
    assert mock_extract.call_args.args[1] == AgentName.CLAUDE


@pytest.mark.asyncio
async def test_process_agent_stop_skips_without_agent_metadata():
    """Agent stop extraction should skip when agent metadata is missing."""
    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path="/tmp/native.json",
        raw={},
    )

    session_missing_agent = MagicMock()
    session_missing_agent.active_agent = None
    session_missing_agent.native_log_file = "/tmp/native.json"

    with patch("teleclaude.core.agent_coordinator.db.get_session", new=AsyncMock(return_value=session_missing_agent)):
        raw = await coordinator._extract_agent_output("tele-123", payload)

    assert raw is None


@pytest.mark.asyncio
async def test_process_agent_stop_does_not_seed_transcript_output(tmp_path):
    """Agent stop handling should not emit output updates directly."""
    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )
    coordinator.client.send_output_update = AsyncMock()
    coordinator._notify_session_listener = AsyncMock()
    coordinator._forward_stop_to_initiator = AsyncMock()
    coordinator._extract_user_input_for_codex = AsyncMock(return_value=None)
    coordinator.tts_manager.speak = AsyncMock()

    transcript_path = tmp_path / "native.json"
    transcript_path.write_text("log")

    payload = AgentStopPayload(
        session_id="native-123",
        transcript_path=str(transcript_path),
        raw={"agent_name": "gemini"},
    )
    context = AgentEventContext(session_id="tele-123", event_type=AgentHookEvents.AGENT_STOP, data=payload)

    session = Session(
        session_id="tele-123",
        computer_name="TestMac",
        tmux_session_name="terminal:abc",
        last_input_origin=InputOrigin.API.value,
        title="Test session",
        adapter_metadata=SessionAdapterMetadata(
            telegram=TelegramAdapterMetadata(topic_id=123, output_message_id="24419")
        ),
        active_agent="gemini",
        native_log_file=str(transcript_path),
        tui_capture_started=False,
    )

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new=AsyncMock(return_value=session)),
        patch("teleclaude.core.agent_coordinator.db.update_session", new=AsyncMock()),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message", return_value="raw output"),
        patch("teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock) as mock_summarize,
    ):
        mock_summarize.return_value = ("title", "summary")
        await coordinator.handle_agent_stop(context)

    assert not coordinator.client.send_output_update.called


@pytest.mark.asyncio
async def test_cleanup_terminates_sessions_inactive_72h():
    """Test that sessions inactive for >72h are terminated."""
    service = MaintenanceService(client=MagicMock(), output_poller=MagicMock(), poller_watch_interval_s=1.0)

    # Create session inactive for 73 hours relative to a fixed "now"
    fixed_now = datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc)
    old_time = fixed_now - timedelta(hours=73)
    inactive_session = Session(
        session_id="inactive-123",
        computer_name="TestMac",
        tmux_session_name="inactive-tmux",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Inactive",
        last_activity=old_time,
    )

    with (
        patch("teleclaude.services.maintenance_service.datetime") as mock_datetime,
        patch("teleclaude.services.maintenance_service.db") as mock_db,
        patch(
            "teleclaude.services.maintenance_service.session_cleanup.terminate_session",
            new_callable=AsyncMock,
        ) as terminate_session,
    ):
        mock_datetime.now.return_value = fixed_now
        mock_db.list_sessions = AsyncMock(return_value=[inactive_session])

        # Execute cleanup
        await service._cleanup_inactive_sessions()

        assert mock_db.list_sessions.called
        assert terminate_session.called
        args, kwargs = terminate_session.call_args
        assert args[0] == "inactive-123"
        assert args[1] == service._client
        assert kwargs["reason"] == "inactive_72h"
        assert kwargs["session"] == inactive_session


@pytest.mark.asyncio
async def test_cleanup_skips_already_closed_inactive_sessions_and_normalizes_status():
    service = MaintenanceService(client=MagicMock(), output_poller=MagicMock(), poller_watch_interval_s=1.0)

    fixed_now = datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc)
    old_time = fixed_now - timedelta(hours=73)
    closed_session = Session(
        session_id="closed-123",
        computer_name="TestMac",
        tmux_session_name="closed-tmux",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Closed",
        last_activity=old_time,
        closed_at=fixed_now - timedelta(days=1),
        lifecycle_status="active",
    )

    with (
        patch("teleclaude.services.maintenance_service.datetime") as mock_datetime,
        patch("teleclaude.services.maintenance_service.db") as mock_db,
        patch(
            "teleclaude.services.maintenance_service.session_cleanup.terminate_session",
            new_callable=AsyncMock,
        ) as terminate_session,
    ):
        mock_datetime.now.return_value = fixed_now
        mock_db.list_sessions = AsyncMock(return_value=[closed_session])
        mock_db.update_session = AsyncMock()

        await service._cleanup_inactive_sessions()

        terminate_session.assert_not_called()
        mock_db.update_session.assert_awaited_once_with("closed-123", lifecycle_status="closed")


@pytest.mark.asyncio
async def test_ensure_tmux_session_recreates_when_missing():
    service = MaintenanceService(client=MagicMock(), output_poller=MagicMock(), poller_watch_interval_s=1.0)

    session = Session(
        session_id="sess-123",
        computer_name="TestMac",
        tmux_session_name="tc_sess-123",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test session",
        project_path="/tmp/project",
        subdir="subdir",
    )

    with (
        patch(
            "teleclaude.services.maintenance_service.tmux_bridge.session_exists",
            new_callable=AsyncMock,
            return_value=False,
        ),
        patch(
            "teleclaude.services.maintenance_service.tmux_bridge.ensure_tmux_session",
            new_callable=AsyncMock,
            return_value=True,
        ) as create_tmux,
        patch.object(service, "_build_tmux_env_vars", new_callable=AsyncMock, return_value={}),
    ):
        result = await service.ensure_tmux_session(session)

        assert result is True
        assert create_tmux.called
        kwargs = create_tmux.await_args.kwargs
        assert kwargs["name"] == "tc_sess-123"
        assert kwargs["working_dir"] == "/tmp/project/subdir"
        assert kwargs["session_id"] == "sess-123"
        assert kwargs["env_vars"] == {}


@pytest.mark.asyncio
async def test_ensure_tmux_session_skips_when_exists():
    service = MaintenanceService(client=MagicMock(), output_poller=MagicMock(), poller_watch_interval_s=1.0)

    session = Session(
        session_id="sess-456",
        computer_name="TestMac",
        tmux_session_name="tc_sess-456",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test session",
        project_path="/tmp/project",
    )

    with (
        patch(
            "teleclaude.services.maintenance_service.tmux_bridge.session_exists",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch.object(service, "_build_tmux_env_vars", new_callable=AsyncMock, return_value={}),
        patch(
            "teleclaude.services.maintenance_service.tmux_bridge.ensure_tmux_session",
            new_callable=AsyncMock,
            return_value=True,
        ) as ensure_tmux,
    ):
        result = await service.ensure_tmux_session(session)

        assert result is True
        assert not ensure_tmux.called

    @pytest.mark.asyncio
    async def test_cleanup_skips_recently_active_sessions(self):
        """Test that recently active sessions are not cleaned up."""
        service = MaintenanceService(client=MagicMock(), output_poller=MagicMock(), poller_watch_interval_s=1.0)

        # Session active 1 hour ago relative to fixed "now"
        fixed_now = datetime(2026, 1, 14, 12, 0, 0, tzinfo=timezone.utc)
        recent_time = fixed_now - timedelta(hours=1)
        active_session = Session(
            session_id="active-456",
            computer_name="TestMac",
            tmux_session_name="active-tmux",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Active",
            last_activity=recent_time,
        )

        with (
            patch("teleclaude.services.maintenance_service.datetime") as mock_datetime,
            patch("teleclaude.services.maintenance_service.db") as mock_db,
            patch(
                "teleclaude.services.maintenance_service.session_cleanup.terminate_session",
                new_callable=AsyncMock,
            ) as terminate_session,
        ):
            mock_datetime.now.return_value = fixed_now
            mock_db.list_sessions = AsyncMock(return_value=[active_session])

            await service._cleanup_inactive_sessions()

            assert mock_db.list_sessions.called
            assert not terminate_session.called


@pytest.mark.asyncio
async def test_dispatch_hook_event_updates_tty_before_polling():
    """TTY metadata should be stored before terminal polling starts."""

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon.client = MagicMock()
    daemon.client.create_channel = AsyncMock()
    daemon._ensure_output_polling = AsyncMock()
    mock_coordinator = MagicMock()
    mock_coordinator.handle_event = AsyncMock()
    daemon.agent_coordinator = mock_coordinator

    session = Session(
        session_id="sess-tty",
        computer_name="TestMac",
        tmux_session_name="terminal:deadbeef",
        last_input_origin=InputOrigin.API.value,
        title="TeleClaude: $TestMac - Tmux",
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

        with patch("teleclaude.daemon.event_bus.emit", new_callable=Mock) as mock_emit:
            await daemon._dispatch_hook_event(
                session_id="sess-tty",
                event_type="agent_stop",
                data={"teleclaude_pid": 123, "teleclaude_tty": "/dev/ttys001", "transcript_path": "/tmp/x.json"},
            )

    assert "poll" in call_order
    assert call_order.index("poll") > max(i for i, v in enumerate(call_order) if v == "update")


@pytest.mark.asyncio
async def test_ensure_output_polling_uses_tmux():
    """Sessions should use tmux polling when tmux exists."""

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon._poll_and_send_output = AsyncMock()
    daemon.client = MagicMock()
    daemon.client.create_channel = AsyncMock()
    daemon.maintenance_service = MagicMock()
    daemon.maintenance_service.ensure_tmux_session = AsyncMock(return_value=True)

    session = Session(
        session_id="sess-term",
        computer_name="TestMac",
        tmux_session_name="telec_1234",
        last_input_origin=InputOrigin.API.value,
        title="TeleClaude: $TestMac - Tmux",
        project_path="/tmp/project",
    )

    with (
        patch("teleclaude.daemon.polling_coordinator.is_polling", new=AsyncMock(return_value=False)),
    ):
        await daemon._ensure_output_polling(session)

    assert daemon._poll_and_send_output.called
    args, _kwargs = daemon._poll_and_send_output.call_args
    assert args == (session.session_id, session.tmux_session_name)


@pytest.mark.asyncio
class TestTitleUpdate:
    """Test session title updates and display title construction."""

    async def test_build_display_title_with_agent_info(self):
        """Display title should include agent info when available."""
        from teleclaude.core.session_utils import build_display_title

        display_title = build_display_title(
            description="Untitled",
            computer_name="TestMac",
            project_path="/home/user/TeleClaude",
            agent_name="claude",
            thinking_mode="slow",
        )

        assert display_title == "TeleClaude: Claude-slow@TestMac - Untitled"

    async def test_build_display_title_with_counter_suffix(self):
        """Display title should preserve counter suffix in description."""
        from teleclaude.core.session_utils import build_display_title

        display_title = build_display_title(
            description="Untitled (2)",
            computer_name="TestMac",
            project_path="/home/user/TeleClaude",
            agent_name="claude",
            thinking_mode="slow",
        )

        assert display_title == "TeleClaude: Claude-slow@TestMac - Untitled (2)"

    async def test_build_display_title_without_agent_info(self):
        """Display title should use $Computer format when agent info is missing."""
        from teleclaude.core.session_utils import build_display_title

        display_title = build_display_title(
            description="Untitled",
            computer_name="TestMac",
            project_path="/home/user/TeleClaude",
            agent_name=None,
            thinking_mode=None,
        )

        assert display_title == "TeleClaude: $TestMac - Untitled"

    async def test_title_summarization_skips_non_untitled(self):
        """Title summarization should skip sessions with meaningful descriptions."""
        coordinator = AgentCoordinator(
            client=MagicMock(),
            tts_manager=MagicMock(),
            headless_snapshot_service=MagicMock(),
        )

        session = Session(
            session_id="sess-1",
            computer_name="TestMac",
            tmux_session_name="tmux-1",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Fix login bug",  # Already has meaningful description
            active_agent="claude",
            thinking_mode="slow",
        )

        context = AgentEventContext(
            session_id="sess-1",
            event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
            data=UserPromptSubmitPayload(prompt="some user input"),
        )

        with (
            patch("teleclaude.core.agent_coordinator.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator.summarize_user_input_title", new_callable=AsyncMock
            ) as mock_summarize,
        ):
            mock_db.get_session = AsyncMock(return_value=session)
            mock_db.update_session = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()

            await coordinator.handle_user_prompt_submit(context)

            # summarize_user_input_title should not be called for non-Untitled sessions
            mock_summarize.assert_not_called()
            # update_session is still called but should NOT include title
            call_kwargs = mock_db.update_session.call_args.kwargs
            assert "title" not in call_kwargs

    async def test_title_summarization_updates_untitled(self):
        """Title summarization should run asynchronously for 'Untitled' sessions."""
        coordinator = AgentCoordinator(
            client=MagicMock(),
            tts_manager=MagicMock(),
            headless_snapshot_service=MagicMock(),
        )

        session = Session(
            session_id="sess-1",
            computer_name="TestMac",
            tmux_session_name="tmux-1",
            last_input_origin=InputOrigin.TELEGRAM.value,
            title="Untitled",  # Should be updated
            active_agent="claude",
            thinking_mode="slow",
        )

        context = AgentEventContext(
            session_id="sess-1",
            event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
            data=UserPromptSubmitPayload(prompt="Help me debug the authentication flow"),
        )

        with (
            patch("teleclaude.core.agent_coordinator.db") as mock_db,
            patch(
                "teleclaude.core.agent_coordinator.summarize_user_input_title", new_callable=AsyncMock
            ) as mock_summarize,
        ):
            mock_db.get_session = AsyncMock(side_effect=[session, session, session])
            mock_db.update_session = AsyncMock()
            mock_db.set_notification_flag = AsyncMock()
            mock_summarize.return_value = "Debug auth flow"

            queued_tasks: list[asyncio.Task[object]] = []

            def _run_now(coro: object, _label: str) -> None:
                queued_tasks.append(asyncio.create_task(coro))

            coordinator._queue_background_task = _run_now  # type: ignore[assignment]
            await coordinator.handle_user_prompt_submit(context)
            await asyncio.gather(*queued_tasks)

            mock_summarize.assert_called_once()
            update_calls = mock_db.update_session.call_args_list
            assert "title" not in update_calls[0].kwargs
            assert "title" not in update_calls[1].kwargs
            assert update_calls[2].kwargs["title"] == "Debug auth flow"


@pytest.mark.asyncio
async def test_user_prompt_submit_skips_empty_prompt() -> None:
    """Empty prompt hook events should not wipe persisted last input."""
    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )

    session = Session(
        session_id="sess-empty",
        computer_name="TestMac",
        tmux_session_name="tmux-1",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Existing title",
        active_agent="gemini",
        thinking_mode="fast",
    )

    context = AgentEventContext(
        session_id="sess-empty",
        event_type=AgentHookEvents.USER_PROMPT_SUBMIT,
        data=UserPromptSubmitPayload(prompt=""),
    )

    with patch("teleclaude.core.agent_coordinator.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=session)
        mock_db.update_session = AsyncMock()
        mock_db.set_notification_flag = AsyncMock()

        await coordinator.handle_user_prompt_submit(context)

        mock_db.set_notification_flag.assert_not_called()
        mock_db.update_session.assert_not_called()


@pytest.mark.asyncio
async def test_periodic_cleanup_replays_recent_closed_sessions() -> None:
    service = MaintenanceService(client=MagicMock(), output_poller=MagicMock(), poller_watch_interval_s=1.0)
    sleep_calls = []

    async def stop_after_second_sleep(*_args: object, **_kwargs: object) -> None:
        if sleep_calls:
            raise asyncio.CancelledError()
        sleep_calls.append(1)

    with (
        patch.object(service, "_cleanup_inactive_sessions", new_callable=AsyncMock) as mock_cleanup_inactive,
        patch(
            "teleclaude.services.maintenance_service.session_cleanup.emit_recently_closed_session_events",
            new_callable=AsyncMock,
        ) as mock_emit_closed,
        patch(
            "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_tmux_sessions",
            new_callable=AsyncMock,
        ),
        patch(
            "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_workspaces", new_callable=AsyncMock
        ),
        patch(
            "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_mcp_wrappers",
            new_callable=AsyncMock,
        ),
        patch("teleclaude.services.maintenance_service.db.cleanup_stale_voice_assignments", new_callable=AsyncMock),
        patch(
            "teleclaude.services.maintenance_service.asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=stop_after_second_sleep,
        ),
    ):
        task = asyncio.create_task(service.periodic_cleanup())
        await task

    assert mock_cleanup_inactive.await_count == 2
    assert mock_emit_closed.await_count == 2
    assert len(sleep_calls) == 1


def test_all_events_have_handlers():
    """Test that every event in TeleClaudeEvents has a registered handler.

    This prevents bugs where new events are added without a specific handler method.
    """

    # Get all events from TeleClaudeEvents
    all_events = []
    for attr_name in dir(TeleClaudeEvents):
        if attr_name.startswith("_"):
            continue
        event_value = getattr(TeleClaudeEvents, attr_name)
        if isinstance(event_value, str):
            all_events.append(event_value)

    # Check each event has a handler
    # Events that don't require explicit daemon handlers
    SKIP_HANDLERS = {"session_updated", "agent_activity"}

    missing_handlers = []
    for event in all_events:
        if event in SKIP_HANDLERS:
            continue

        # Non-command events need specific handler method
        handler_name = f"_handle_{event}"
        if not hasattr(TeleClaudeDaemon, handler_name):
            missing_handlers.append(f"{event} (expected {handler_name})")

    # Report missing handlers
    assert not missing_handlers, (
        f"Events missing handlers: {missing_handlers}\nAdd handler method on TeleClaudeDaemon or mark as skipped."
    )
