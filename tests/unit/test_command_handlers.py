"""Unit tests for command handlers."""

import json
import os
import tempfile
from datetime import datetime, timezone
from typing import Awaitable, TypedDict, cast
from unittest.mock import ANY, AsyncMock, MagicMock, patch

import pytest

from teleclaude.config import AgentConfig
from teleclaude.core import command_handlers
from teleclaude.core.db import Db
from teleclaude.core.identity import IdentityContext
from teleclaude.core.models import MessageMetadata, Session
from teleclaude.core.origins import InputOrigin
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX
from teleclaude.types.commands import (
    CloseSessionCommand,
    CreateSessionCommand,
    GetSessionDataCommand,
    HandleFileCommand,
    HandleVoiceCommand,
    KeysCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
    StartAgentCommand,
)

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")


@pytest.fixture(autouse=True)
def mock_identity_resolver():
    """Default command handler tests to an authorized human identity."""
    with patch("teleclaude.core.command_handlers.get_identity_resolver") as mock_get_resolver:
        resolver = MagicMock()
        resolver.resolve.return_value = IdentityContext(
            person_name="Test User",
            person_role="admin",
            platform="telegram",
            platform_user_id="123",
        )
        mock_get_resolver.return_value = resolver
        yield resolver


@pytest.fixture
async def mock_initialized_db(monkeypatch):
    """Fixture to provide a mocked, initialized database connection."""

    # Create a Db instance with in-memory database
    mock_db_instance = Db(":memory:")

    # Initialize with proper schema (includes all columns after migration)
    await mock_db_instance.initialize()

    # Patch the global db object in command_handlers module
    monkeypatch.setattr("teleclaude.core.command_handlers.db", mock_db_instance)
    monkeypatch.setattr("teleclaude.core.db.db", mock_db_instance)  # Also patch the singleton itself

    yield mock_db_instance

    await mock_db_instance.close()


@pytest.mark.asyncio
async def test_handle_get_computer_info_returns_system_stats():
    """Test that get_computer_info returns system stats."""
    # Mock config values
    mock_config = MagicMock()
    mock_config.computer.user = "testuser"
    mock_config.computer.role = "development"
    mock_config.computer.host = "test.local"

    with patch.object(command_handlers, "config", mock_config):
        result = await command_handlers.get_computer_info()

    # Verify basic fields
    assert result.user == "testuser"
    assert result.role == "development"
    assert result.host == "test.local"

    # Verify system_stats structure
    assert result.system_stats is not None
    system_stats = result.system_stats

    # Memory stats
    assert "memory" in system_stats
    assert "total_gb" in system_stats["memory"]
    assert "available_gb" in system_stats["memory"]
    assert "percent_used" in system_stats["memory"]

    # Disk stats
    assert "disk" in system_stats
    assert "total_gb" in system_stats["disk"]
    assert "free_gb" in system_stats["disk"]
    assert "percent_used" in system_stats["disk"]

    # CPU stats
    assert "cpu" in system_stats
    assert "percent_used" in system_stats["cpu"]


@pytest.mark.asyncio
async def test_handle_new_session_creates_session(mock_initialized_db):
    """Test that handle_new_session returns a session_id and persists the session."""

    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()
    mock_client.send_message = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        MessageMetadata(origin=InputOrigin.TELEGRAM.value, project_path=tmpdir)
        with (
            patch.object(command_handlers, "config") as mock_config,
            patch.object(command_handlers, "db") as mock_db,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = mock_initialized_db.create_session
            mock_db.get_session = mock_initialized_db.get_session

            cmd = CreateSessionCommand(project_path=tmpdir, title="Test Title", origin=InputOrigin.TELEGRAM.value)
            result = await command_handlers.create_session(cmd, mock_client)

    assert result["session_id"]
    assert result["tmux_session_name"].startswith(TMUX_SESSION_PREFIX)
    assert result["tmux_session_name"].endswith(result["session_id"][:8])

    stored = await mock_initialized_db.get_session(result["session_id"])
    assert stored is not None
    assert stored.session_id == result["session_id"]
    assert stored.tmux_session_name == result["tmux_session_name"]


@pytest.mark.asyncio
async def test_handle_create_session_does_not_send_welcome(mock_initialized_db, monkeypatch):
    """Session creation should not emit a welcome message."""
    order: list[str] = []

    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()

    async def _send_message(*_args, **_kwargs):
        order.append("welcome")
        return "msg-1"

    async def _send_output_update(*_args, **_kwargs):
        order.append("output")
        return "msg-2"

    mock_client.send_message = AsyncMock(side_effect=_send_message)
    mock_client.send_output_update = AsyncMock(side_effect=_send_output_update)
    mock_client.adapters = {}

    with tempfile.TemporaryDirectory() as tmpdir:
        MessageMetadata(origin=InputOrigin.TELEGRAM.value, project_path=tmpdir)
        with (
            patch.object(command_handlers, "config") as mock_config,
            patch.object(command_handlers, "db") as mock_db,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = mock_initialized_db.create_session
            mock_db.get_session = mock_initialized_db.get_session

            cmd = CreateSessionCommand(project_path=tmpdir, title="Test Title", origin=InputOrigin.TELEGRAM.value)
            await command_handlers.create_session(cmd, mock_client)

    assert order == []
    assert mock_client.send_output_update.await_count == 0


@pytest.mark.asyncio
async def test_create_session_inherits_parent_origin(mock_initialized_db):
    """AI-to-AI sessions should inherit last_input_origin from the parent session."""
    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()
    mock_client.send_message = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch.object(command_handlers, "config") as mock_config,
            patch.object(command_handlers, "db") as mock_db,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = mock_initialized_db.create_session
            mock_db.get_session = mock_initialized_db.get_session

            parent = await mock_initialized_db.create_session(
                computer_name="TestComputer",
                tmux_session_name="tmux-parent",
                last_input_origin=InputOrigin.TELEGRAM.value,
                title="Parent Session",
            )

            cmd = CreateSessionCommand(
                project_path=tmpdir,
                title="Child Session",
                origin=InputOrigin.TELEGRAM.value,
                initiator_session_id=parent.session_id,
            )
            result = await command_handlers.create_session(cmd, mock_client)

    stored = await mock_initialized_db.get_session(result["session_id"])
    assert stored is not None
    assert stored.last_input_origin == "telegram"


@pytest.mark.asyncio
async def test_handle_create_session_terminal_metadata_updates_size_and_ux_state(mock_initialized_db):
    """Tmux adapter should store terminal metadata on the session."""

    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()
    mock_client.send_message = AsyncMock()

    with tempfile.TemporaryDirectory() as tmpdir:
        MessageMetadata(
            origin="terminal",
            project_path=tmpdir,
            channel_metadata={
                "terminal": {
                    "tty_path": "/dev/pts/7",
                    "parent_pid": 4242,
                }
            },
        )
        with (
            patch.object(command_handlers, "config") as mock_config,
            patch.object(command_handlers, "db") as mock_db,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = mock_initialized_db.create_session
            mock_db.get_session = mock_initialized_db.get_session
            mock_db.update_session = mock_initialized_db.update_session

            cmd = CreateSessionCommand(
                project_path=tmpdir,
                title="Test",
                origin="terminal",
                channel_metadata={
                    "terminal": {
                        "tty_path": "/dev/pts/7",
                        "parent_pid": 4242,
                    }
                },
            )
            result = await command_handlers.create_session(cmd, mock_client)

    stored = await mock_initialized_db.get_session(result["session_id"])
    assert stored is not None


@pytest.mark.asyncio
async def test_handle_new_session_validates_working_dir(mock_initialized_db, tmp_path):
    """Test that handle_new_session rejects invalid working directories."""

    invalid_path = tmp_path / "not-a-dir.txt"
    invalid_path.write_text("nope", encoding="utf-8")

    MessageMetadata(origin=InputOrigin.TELEGRAM.value, project_path=str(invalid_path))
    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()
    mock_client.send_message = AsyncMock()

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock),
    ):
        mock_config.computer.name = "TestComputer"
        mock_config.computer.default_working_dir = "/home/user"
        mock_db.create_session = mock_initialized_db.create_session
        mock_db.get_session = mock_initialized_db.get_session
        mock_db.delete_session = mock_initialized_db.delete_session

        cmd = CreateSessionCommand(project_path="/nonexistent", origin=InputOrigin.TELEGRAM.value)
        with pytest.raises(ValueError, match="Working directory does not exist"):
            await command_handlers.create_session(cmd, mock_client)
    assert await mock_initialized_db.count_sessions() == 0


@pytest.mark.asyncio
async def test_handle_kill_terminates_process():
    """Test that handle_kill sends SIGKILL to running process."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    cmd = KeysCommand(session_id=mock_session.session_id, key="kill")
    sent: list[tuple[object, str]] = []

    async def record_signal(session, signal: str) -> bool:
        sent.append((session, signal))
        return True

    with patch.object(command_handlers, "tmux_io") as mock_tb:
        mock_tb.send_signal = record_signal

        await command_handlers.kill_command.__wrapped__(mock_session, cmd, AsyncMock())

    assert sent == [(mock_session, "SIGKILL")]


@pytest.mark.asyncio
async def test_handle_cancel_sends_ctrl_c():
    """Test that handle_cancel sends Ctrl+C."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    cmd = KeysCommand(session_id=mock_session.session_id, key="cancel")
    sent: list[tuple[object, str]] = []

    async def record_signal(session, signal: str) -> bool:
        sent.append((session, signal))
        return True

    with patch.object(command_handlers, "tmux_io") as mock_tb:
        mock_tb.send_signal = record_signal

        await command_handlers.cancel_command.__wrapped__(mock_session, cmd, AsyncMock())

    assert sent == [(mock_session, "SIGINT")]


@pytest.mark.asyncio
async def test_handle_escape_sends_esc():
    """Test that handle_escape sends ESC key."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    cmd = KeysCommand(session_id=mock_session.session_id, key="escape")
    sent: list[object] = []

    async def record_escape(session) -> bool:
        sent.append(session)
        return True

    with patch.object(command_handlers, "tmux_io") as mock_tb:
        mock_tb.send_escape = record_escape

        await command_handlers.escape_command.__wrapped__(mock_session, cmd, AsyncMock())

    assert sent == [mock_session]


@pytest.mark.asyncio
async def test_handle_ctrl_sends_ctrl_key():
    """Test that handle_ctrl sends Ctrl+<key> combinations."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    cmd = KeysCommand(session_id=mock_session.session_id, key="ctrl", args=["d"])
    mock_client = MagicMock()
    sent: list[tuple[object, str]] = []

    async def record_ctrl(session, key: str) -> bool:
        sent.append((session, key))
        return True

    with patch.object(command_handlers, "tmux_io") as mock_tb:
        mock_tb.send_ctrl_key = record_ctrl

        await command_handlers.ctrl_command.__wrapped__(mock_session, cmd, mock_client, AsyncMock())

    assert sent == [(mock_session, "d")]


@pytest.mark.asyncio
async def test_handle_list_sessions_formats_output():
    """Test that list_sessions formats session list."""
    # Create mock sessions explicitly without loops
    now = datetime.now()

    s0 = MagicMock()
    s0.session_id = "session-0"
    s0.last_input_origin = "telegram"
    s0.title = "Test Session 0"
    s0.project_path = "/home/user"
    s0.created_at = now
    s0.last_activity = now
    s0.thinking_mode = "med"
    s0.lifecycle_status = "active"
    s0.human_email = "owner@example.com"
    s0.human_role = "admin"

    s1 = MagicMock()
    s1.session_id = "session-1"
    s1.last_input_origin = "telegram"
    s1.title = "Test Session 1"
    s1.project_path = "/home/user"
    s1.created_at = now
    s1.last_activity = now
    s1.thinking_mode = "med"
    s1.lifecycle_status = "active"
    s1.human_email = "member@example.com"
    s1.human_role = "member"

    mock_sessions = [s0, s1]

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.list_sessions = AsyncMock(return_value=mock_sessions)

        result = await command_handlers.list_sessions()

    assert len(result) == 2

    assert result[0].session_id == "session-0"
    assert result[0].last_input_origin == "telegram"
    assert result[0].title == "Test Session 0"
    assert result[0].status == "active"
    assert result[0].human_email == "owner@example.com"
    assert result[0].human_role == "admin"

    assert result[1].session_id == "session-1"
    assert result[1].last_input_origin == "telegram"
    assert result[1].title == "Test Session 1"
    assert result[1].status == "active"
    assert result[1].human_email == "member@example.com"
    assert result[1].human_role == "member"


@pytest.mark.asyncio
async def test_handle_get_session_data_returns_transcript():
    """Test that get_session_data returns session transcript."""
    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.title = "Test Session"
    mock_session.project_path = "/home/user"
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None  # No file yet
    mock_session.lifecycle_status = "active"
    mock_session.closed_at = None
    mock_session.last_output_at = datetime.now()

    cmd = GetSessionDataCommand(session_id="test-session-123")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    # No claude_session_file means error
    assert result["status"] == "error"
    assert "file" in result["error"].lower()


@pytest.mark.asyncio
async def test_handle_get_session_data_returns_markdown(tmp_path):
    """Verify successful transcript parsing path for existing file."""
    mock_session = MagicMock()
    mock_session.session_id = "test-session-456"
    mock_session.title = "Markdown Session"
    mock_session.project_path = "/home/user"
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()

    nested_path = tmp_path / "session.json"
    gemini_payload = {
        "sessionId": "test-session-456",
        "messages": [
            {
                "type": "user",
                "timestamp": "2025-12-15T12:00:00.000Z",
                "content": "hi",
            },
            {
                "type": "gemini",
                "timestamp": "2025-12-15T12:01:00.000Z",
                "content": "hello",
                "thoughts": [{"description": "Processing"}, {"description": ""}],
            },
        ],
    }
    nested_path.write_text(json.dumps(gemini_payload), encoding="utf-8")

    mock_session.native_log_file = str(nested_path)
    mock_session.active_agent = "gemini"

    cmd = GetSessionDataCommand(session_id="test-session-456")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert "Markdown Session" in result["messages"]
    assert "hi" in result["messages"]
    assert "hello" in result["messages"]


@pytest.mark.asyncio
async def test_handle_get_session_data_codex_pending_when_no_transcript():
    """Codex get_session_data should be non-error before first transcript binding."""
    mock_session = MagicMock()
    mock_session.session_id = "codex-session-1"
    mock_session.title = "Codex Session"
    mock_session.project_path = "/home/user"
    mock_session.subdir = None
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None
    mock_session.native_session_id = None
    mock_session.active_agent = "codex"
    mock_session.tmux_session_name = None

    cmd = GetSessionDataCommand(session_id="codex-session-1")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert "not available yet" in result["messages"].lower()
    assert result["transcript"] is None


@pytest.mark.asyncio
async def test_handle_get_session_data_codex_pending_when_transcript_path_missing(tmp_path):
    """Codex get_session_data should be non-error when transcript file is not yet on disk."""
    mock_session = MagicMock()
    mock_session.session_id = "codex-session-2"
    mock_session.title = "Codex Session"
    mock_session.project_path = "/home/user"
    mock_session.subdir = None
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = str(tmp_path / "missing-transcript.jsonl")
    mock_session.native_session_id = "019c-test"
    mock_session.active_agent = "codex"
    mock_session.tmux_session_name = None

    cmd = GetSessionDataCommand(session_id="codex-session-2")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert "not available yet" in result["messages"].lower()
    assert result["transcript"] is None


@pytest.mark.asyncio
async def test_handle_get_session_data_pending_for_pre_stop_non_codex_session():
    """Non-codex sessions should return pending payload before first completed turn."""
    mock_session = MagicMock()
    mock_session.session_id = "claude-session-1"
    mock_session.title = "Claude Session"
    mock_session.project_path = "/home/user"
    mock_session.subdir = None
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None
    mock_session.native_session_id = None
    mock_session.active_agent = "claude"
    mock_session.lifecycle_status = "active"
    mock_session.closed_at = None
    mock_session.last_output_at = None
    mock_session.tmux_session_name = None

    cmd = GetSessionDataCommand(session_id="claude-session-1")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert "not available yet" in result["messages"].lower()
    assert result["transcript"] is None


@pytest.mark.asyncio
async def test_handle_get_session_data_errors_after_completed_turn_when_transcript_missing():
    """A missing transcript after a completed turn remains an error for non-codex sessions."""
    mock_session = MagicMock()
    mock_session.session_id = "claude-session-2"
    mock_session.title = "Claude Session"
    mock_session.project_path = "/home/user"
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None
    mock_session.native_session_id = None
    mock_session.active_agent = "claude"
    mock_session.lifecycle_status = "active"
    mock_session.closed_at = None
    mock_session.last_output_at = datetime.now()

    cmd = GetSessionDataCommand(session_id="claude-session-2")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "error"
    assert "file" in result["error"].lower()


@pytest.mark.asyncio
async def test_handle_get_session_data_codex_pending_is_case_insensitive():
    """Codex pending path should work for non-lowercase active_agent values."""
    mock_session = MagicMock()
    mock_session.session_id = "codex-session-3"
    mock_session.title = "Codex Session"
    mock_session.project_path = "/home/user"
    mock_session.subdir = None
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None
    mock_session.native_session_id = "019c-test"
    mock_session.active_agent = "Codex"
    mock_session.lifecycle_status = "active"
    mock_session.closed_at = None
    mock_session.last_output_at = None
    mock_session.tmux_session_name = None

    cmd = GetSessionDataCommand(session_id="codex-session-3")

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch("teleclaude.core.command_handlers.discover_codex_transcript_path", return_value=None),
    ):
        mock_db.get_session = AsyncMock(return_value=mock_session)
        mock_db.update_session = AsyncMock()

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert "not available yet" in result["messages"].lower()
    assert result["transcript"] is None


@pytest.mark.asyncio
async def test_handle_get_session_data_codex_falls_back_to_tmux_when_no_transcript():
    """Codex sessions should return tmux pane tail when no transcript path is available."""
    mock_session = MagicMock()
    mock_session.session_id = "codex-session-tmux-1"
    mock_session.title = "Codex Session"
    mock_session.project_path = "/home/user"
    mock_session.subdir = None
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None
    mock_session.native_session_id = None
    mock_session.active_agent = "codex"
    mock_session.tmux_session_name = "tc_codex_1"

    cmd = GetSessionDataCommand(session_id="codex-session-tmux-1", tail_chars=6)

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(command_handlers.tmux_bridge, "capture_pane", new=AsyncMock(return_value="abcdef123456")),
    ):
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert result["messages"] == "123456"
    assert result.get("transcript") is None


@pytest.mark.asyncio
async def test_handle_get_session_data_non_codex_falls_back_to_tmux_before_pending():
    """Pre-stop non-codex sessions should prefer tmux output over pending transcript notice."""
    mock_session = MagicMock()
    mock_session.session_id = "claude-session-tmux-1"
    mock_session.title = "Claude Session"
    mock_session.project_path = "/home/user"
    mock_session.subdir = None
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None
    mock_session.native_session_id = None
    mock_session.active_agent = "claude"
    mock_session.lifecycle_status = "active"
    mock_session.closed_at = None
    mock_session.last_output_at = None
    mock_session.tmux_session_name = "tc_claude_1"

    cmd = GetSessionDataCommand(session_id="claude-session-tmux-1")

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(command_handlers.tmux_bridge, "capture_pane", new=AsyncMock(return_value="live output")),
    ):
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert result["messages"] == "live output"
    assert "not available yet" not in result["messages"].lower()


@pytest.mark.asyncio
async def test_handle_get_session_data_codex_returns_empty_tmux_tail_instead_of_pending():
    """Codex sessions should return tmux fallback immediately even when pane output is currently empty."""
    mock_session = MagicMock()
    mock_session.session_id = "codex-session-tmux-empty"
    mock_session.title = "Codex Session"
    mock_session.project_path = "/home/user"
    mock_session.subdir = None
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None
    mock_session.native_session_id = None
    mock_session.active_agent = "codex"
    mock_session.tmux_session_name = "tc_codex_empty"

    cmd = GetSessionDataCommand(session_id="codex-session-tmux-empty")

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(command_handlers.tmux_bridge, "capture_pane", new=AsyncMock(return_value="")),
    ):
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert result["messages"] == ""
    assert "not available yet" not in result["messages"].lower()


@pytest.mark.asyncio
async def test_handle_get_session_data_non_codex_returns_empty_tmux_tail_before_pending():
    """Pre-stop non-codex sessions should return empty tmux fallback instead of pending notice."""
    mock_session = MagicMock()
    mock_session.session_id = "claude-session-tmux-empty"
    mock_session.title = "Claude Session"
    mock_session.project_path = "/home/user"
    mock_session.subdir = None
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None
    mock_session.native_session_id = None
    mock_session.active_agent = "claude"
    mock_session.lifecycle_status = "active"
    mock_session.closed_at = None
    mock_session.last_output_at = None
    mock_session.tmux_session_name = "tc_claude_empty"

    cmd = GetSessionDataCommand(session_id="claude-session-tmux-empty")

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(command_handlers.tmux_bridge, "capture_pane", new=AsyncMock(return_value="")),
    ):
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "success"
    assert result["messages"] == ""
    assert "not available yet" not in result["messages"].lower()


@pytest.mark.asyncio
async def test_handle_get_session_data_returns_error_for_missing_session():
    """Test that get_session_data returns error for missing sessions."""
    cmd = GetSessionDataCommand(session_id="missing-session")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        result = await command_handlers.get_session_data(cmd)

    assert result["status"] == "error"
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_handle_list_projects_returns_trusted_dirs():
    """Test that list_projects returns trusted directories."""

    mock_trusted_dir = MagicMock()
    mock_trusted_dir.name = "Project"
    mock_trusted_dir.desc = "Test project"
    mock_trusted_dir.path = "/tmp"  # Use /tmp as it always exists

    with patch.object(command_handlers, "config") as mock_config:
        mock_config.computer.get_all_trusted_dirs.return_value = [mock_trusted_dir]

        result = await command_handlers.list_projects()

    assert len(result) == 1
    assert result[0].name == "Project"
    assert result[0].description == "Test project"
    assert "/tmp" in result[0].path


@pytest.mark.asyncio
async def test_handle_ctrl_requires_key_argument(mock_initialized_db):
    """Test that handle_ctrl requires a key argument."""

    messages: list[str] = []

    class FakeClient:
        """Capture outgoing messages for assertions."""

        async def send_message(self, _session, message, **_kwargs):
            messages.append(str(message))

    session = await mock_initialized_db.create_session(
        computer_name="TestPC",
        tmux_session_name="tc_test",
        last_input_origin=InputOrigin.API.value,
        title="Test Session",
        project_path="/home/user",
    )

    cmd = KeysCommand(session_id=session.session_id, key="ctrl", args=[])
    await command_handlers.ctrl_command.__wrapped__(session, cmd, FakeClient(), AsyncMock())

    assert len(messages) > 0
    assert "Usage" in messages[0]


@pytest.mark.asyncio
async def test_handle_agent_start_executes_command_with_args(mock_initialized_db):
    """Test that agent_start executes agent's command with provided arguments."""

    mock_session = MagicMock()
    mock_session.session_id = "model-session-789"
    mock_session.tmux_session_name = "tc_test"

    mock_execute_calls = []

    async def record_execute(*args, **kwargs):
        mock_execute_calls.append((args, kwargs))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        binary="claude",
        profiles={"default": ""},
        session_dir="~/.claude/sessions",
        log_pattern="*.jsonl",
        model_flags={"fast": "-m haiku", "med": "-m sonnet", "slow": "-m opus"},
        exec_subcommand="",
        interactive_flag="-p",
        non_interactive_flag="-p",
        resume_template="{base_cmd} --resume {session_id}",
        continue_template="",
    )

    with patch.object(command_handlers, "config") as mock_config:
        mock_config.agents.get.return_value = mock_agent_config

        cmd = StartAgentCommand(
            session_id=mock_session.session_id,
            agent_name="claude",
            args=["--model=haiku", "--test"],
        )
        await command_handlers.start_agent.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    # Verify execute_terminal_command was called with base command and args
    assert len(mock_execute_calls) == 1
    command = mock_execute_calls[0][0][1]

    # Check for parts since shlex.quote behavior can vary in tests
    assert "claude" in command
    assert "--model=haiku" in command
    assert "--test" in command


@pytest.mark.asyncio
async def test_handle_agent_start_executes_command_without_extra_args_if_none_provided(mock_initialized_db):
    """Test that agent_start executes agent's command correctly when no extra args are provided."""

    mock_session = MagicMock()
    mock_session.session_id = "regular-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_execute_calls = []

    async def record_execute(*args, **kwargs):
        mock_execute_calls.append((args, kwargs))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        binary="codex",
        profiles={"default": "--dangerously-bypass-approvals-and-sandbox --search"},
        session_dir="~/.codex/sessions",
        log_pattern="*.jsonl",
        model_flags={"fast": "-m gpt-5.1-codex-mini", "med": "-m gpt-5.1-codex", "slow": "-m gpt-5.3"},
        exec_subcommand="exec",
        interactive_flag="",
        non_interactive_flag="",
        resume_template="{base_cmd} resume {session_id}",
        continue_template="",
    )

    with patch.object(command_handlers, "config") as mock_config:
        mock_config.agents.get.return_value = mock_agent_config

        cmd = StartAgentCommand(session_id=mock_session.session_id, agent_name="codex", args=[])
        await command_handlers.start_agent.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert len(mock_execute_calls) == 1
    command = mock_execute_calls[0][0][1]
    assert "codex" in command


@pytest.mark.asyncio
async def test_handle_agent_start_does_not_clear_native_fields(mock_initialized_db):
    """Ensure agent_start does not wipe native session metadata."""
    mock_session = MagicMock()
    mock_session.session_id = "native-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.native_session_id = "native-123"
    mock_session.native_log_file = "/tmp/native.jsonl"
    mock_session.title = "Project: $local - Test"

    mock_execute_calls = []

    async def record_execute(*args, **kwargs):
        mock_execute_calls.append((args, kwargs))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
    ):
        mock_config.computer.name = "local"
        mock_db.update_session = AsyncMock()
        mock_get_agent_command.return_value = "claude"

        cmd = StartAgentCommand(session_id=mock_session.session_id, agent_name="claude", args=[])
        await command_handlers.start_agent.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    _, kwargs = mock_db.update_session.call_args
    assert "native_session_id" not in kwargs
    assert "native_log_file" not in kwargs


@pytest.mark.asyncio
async def test_handle_agent_start_accepts_deep_for_codex(mock_initialized_db):
    """Ensure /codex deep maps to the deep model flag."""

    mock_session = MagicMock()
    mock_session.session_id = "deep-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.thinking_mode = "slow"

    mock_execute_calls: list[tuple[tuple[object, ...], ExecuteKwargs]] = []

    async def record_execute(*args: object, **kwargs: object) -> bool:
        mock_execute_calls.append((args, cast(ExecuteKwargs, kwargs)))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
    ):
        mock_config.agents.get.return_value = MagicMock()
        mock_db.update_session = AsyncMock()
        mock_get_agent_command.return_value = "codex -m deep"

        cmd = StartAgentCommand(session_id=mock_session.session_id, agent_name="codex", args=["deep"])
        await command_handlers.start_agent.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert len(mock_execute_calls) == 1
    # "deep" is parsed as thinking_mode, so user_args is empty -> interactive=False
    assert mock_get_agent_command.call_args == (
        ("codex",),
        {"thinking_mode": "deep", "interactive": False, "profile": "default"},
    )
    command = mock_execute_calls[0][0][1]
    assert "codex -m deep" in command


@pytest.mark.asyncio
async def test_handle_agent_start_rejects_deep_for_non_codex(mock_initialized_db):
    """Ensure deep is rejected for non-codex agents."""

    mock_session = MagicMock()
    mock_session.session_id = "deep-session-456"
    mock_session.tmux_session_name = "tc_test"
    mock_session.thinking_mode = "slow"

    mock_execute_calls: list[tuple[tuple[object, ...], ExecuteKwargs]] = []

    async def record_execute(*args: object, **kwargs: object) -> bool:
        mock_execute_calls.append((args, cast(ExecuteKwargs, kwargs)))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
    ):
        mock_config.agents.get.return_value = MagicMock()
        mock_db.update_session = AsyncMock()

        cmd = StartAgentCommand(session_id=mock_session.session_id, agent_name="claude", args=["deep"])
        await command_handlers.start_agent.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert mock_client.send_message.call_args == (
        (mock_session, "deep is only supported for codex. Use fast/med/slow for other agents."),
        {},
    )
    assert mock_execute_calls == []
    mock_get_agent_command.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_resume_executes_command_with_session_id_from_db(mock_initialized_db):
    """Test that agent_resume uses native_session_id from database and resume template."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.native_session_id = "native-123-abc"
    mock_session.thinking_mode = "slow"

    mock_execute_calls = []

    async def record_execute(*args, **kwargs):
        mock_execute_calls.append((args, kwargs))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        binary="gemini",
        profiles={"default": "--yolo"},
        session_dir="~/.gemini/sessions",
        log_pattern="*.jsonl",
        model_flags={
            "fast": "-m gemini-2.5-flash-lite",
            "med": "-m gemini-2.5-flash",
            "slow": "-m gemini-3-pro-preview",
        },
        exec_subcommand="",
        interactive_flag="-i",
        non_interactive_flag="",
        resume_template="{base_cmd} --resume {session_id}",
        continue_template="",
    )

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
    ):
        mock_config.agents.get.return_value = mock_agent_config
        mock_db.update_session = AsyncMock()

        cmd = ResumeAgentCommand(session_id=mock_session.session_id, agent_name="gemini")
        await command_handlers.resume_agent.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert len(mock_execute_calls) == 1
    command = mock_execute_calls[0][0][1]

    # Gemini uses --resume flag with session ID from database
    assert "--yolo" in command
    assert "--resume" in command
    assert "native-123-abc" in command


@pytest.mark.asyncio
async def test_handle_agent_resume_uses_continue_template_when_no_native_session_id(mock_initialized_db):
    """Test that agent_resume continues latest conversation when no native_session_id is stored."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-continue-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.native_session_id = None
    mock_session.thinking_mode = "slow"

    mock_execute_calls = []

    async def record_execute(*args, **kwargs):
        mock_execute_calls.append((args, kwargs))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        binary="claude",
        profiles={"default": "--dangerously-skip-permissions"},
        session_dir="~/.claude/sessions",
        log_pattern="*.jsonl",
        model_flags={"fast": "-m haiku", "med": "-m sonnet", "slow": "-m opus"},
        exec_subcommand="",
        interactive_flag="-p",
        non_interactive_flag="-p",
        resume_template="{base_cmd} --resume {session_id}",
        continue_template="{base_cmd} --continue",
    )

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
    ):
        mock_config.agents.get.return_value = mock_agent_config
        mock_db.update_session = AsyncMock()

        cmd = ResumeAgentCommand(session_id=mock_session.session_id, agent_name="claude")
        await command_handlers.resume_agent.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert len(mock_execute_calls) == 1
    command = mock_execute_calls[0][0][1]

    # Check for Claude's key flags and continue template behavior
    assert "--dangerously-skip-permissions" in command
    assert command.endswith("--continue")
    assert "--resume" not in command
    assert "-m " not in command  # continue_template path skips model flag


@pytest.mark.asyncio
async def test_handle_agent_resume_uses_override_session_id_from_args(mock_initialized_db):
    """Test that agent_resume accepts an explicit native session ID argument."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-override-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.native_session_id = "native-db-123"
    mock_session.thinking_mode = "slow"

    mock_execute_calls = []

    async def record_execute(*args, **kwargs):
        mock_execute_calls.append((args, kwargs))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        binary="codex",
        profiles={"default": "--yolo"},
        session_dir="~/.codex/sessions",
        log_pattern="*.jsonl",
        model_flags={},
        exec_subcommand="",
        interactive_flag="",
        non_interactive_flag="",
        resume_template="{base_cmd} resume {session_id}",
        continue_template="",
    )

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
    ):
        mock_config.agents.get.return_value = mock_agent_config
        mock_db.update_session = AsyncMock()

        cmd = ResumeAgentCommand(
            session_id=mock_session.session_id,
            agent_name="codex",
            native_session_id="native-override-999",
        )
        await command_handlers.resume_agent.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    mock_db.update_session.assert_any_await(
        "test-session-override-123",
        native_session_id="native-override-999",
    )
    assert len(mock_execute_calls) == 1
    command = mock_execute_calls[0][0][1]
    assert "resume" in command
    assert "native-override-999" in command


@pytest.mark.asyncio
async def test_handle_agent_restart_fails_without_active_agent(mock_initialized_db):
    """Restart should fail fast when no active agent is stored."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.closed_at = None

    mock_execute_calls = []

    async def record_execute(*args, **kwargs):
        mock_execute_calls.append((args, kwargs))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()
    mock_session.active_agent = None
    mock_session.native_session_id = None

    with patch.object(command_handlers, "db") as mock_db:
        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        result = await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert result == (False, "Cannot restart agent: no active agent for this session.")
    assert mock_client.send_message.call_args == (
        (mock_session, "❌ Cannot restart agent: no active agent for this session."),
        {},
    )
    assert mock_execute_calls == []


@pytest.mark.asyncio
async def test_handle_agent_restart_fails_without_native_session_id(mock_initialized_db):
    """Restart should fail fast when native_session_id is missing."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-456"
    mock_session.tmux_session_name = "tc_test"
    mock_session.active_agent = "claude"
    mock_session.native_session_id = None
    mock_session.closed_at = None

    mock_execute = AsyncMock()
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()

    cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
    result = await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert result == (False, "Cannot restart agent: no native session ID stored. Start the agent first.")
    assert mock_client.send_message.call_args == (
        (mock_session, "❌ Cannot restart agent: no native session ID stored. Start the agent first."),
        {},
    )
    mock_execute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_restart_resumes_with_native_session_id(mock_initialized_db):
    """Restart should send SIGINTs and resume using stored native_session_id."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-789"
    mock_session.tmux_session_name = "tc_test"
    mock_session.active_agent = "claude"
    mock_session.native_session_id = "native-abc"
    mock_session.closed_at = None

    mock_execute_calls: list[tuple[tuple[object, ...], ExecuteKwargs]] = []

    async def record_execute(*args: object, **kwargs: object) -> bool:
        mock_execute_calls.append((args, cast(ExecuteKwargs, kwargs)))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()

    with (
        patch.object(command_handlers, "tmux_io") as mock_tmux_bridge,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
        patch.object(command_handlers.asyncio, "sleep", new=AsyncMock()),
        patch.object(command_handlers.asyncio, "create_task", side_effect=lambda coro: (coro.close(), MagicMock())[1]),
        patch.object(command_handlers, "config") as mock_config,
    ):
        mock_tmux_bridge.send_signal = AsyncMock(return_value=True)
        mock_tmux_bridge.wait_for_shell_ready = AsyncMock(return_value=True)
        mock_get_agent_command.return_value = "claude --resume native-abc"
        mock_config.agents.get.return_value = MagicMock()

        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert mock_tmux_bridge.send_signal.await_count == 2
    assert len(mock_execute_calls) == 1
    command = mock_execute_calls[0][0][1]
    assert "claude --resume native-abc" in command


@pytest.mark.asyncio
async def test_handle_agent_restart_aborts_when_shell_not_ready(mock_initialized_db):
    """Restart should abort if the foreground process does not exit."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-999"
    mock_session.tmux_session_name = "tc_test"
    mock_session.active_agent = "claude"
    mock_session.native_session_id = "native-xyz"
    mock_session.closed_at = None

    mock_execute_calls = []

    async def record_execute(*args, **kwargs):
        mock_execute_calls.append((args, kwargs))
        return True

    mock_execute = record_execute
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()

    with (
        patch.object(command_handlers, "tmux_io") as mock_tmux_bridge,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(command_handlers, "config") as mock_config,
    ):
        mock_tmux_bridge.send_signal = AsyncMock(return_value=True)
        mock_tmux_bridge.wait_for_shell_ready = AsyncMock(return_value=False)
        mock_config.agents.get.return_value = MagicMock()

        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert mock_client.send_message.await_count == 1
    assert mock_execute_calls == []


@pytest.mark.asyncio
async def test_handle_agent_restart_uses_context_payload_for_post_restart_checkpoint(mock_initialized_db):
    """Restart checkpoint injection should use context-aware payload, not legacy constant."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-ctx"
    mock_session.tmux_session_name = "tc_ctx"
    mock_session.active_agent = "codex"
    mock_session.native_session_id = "native-ctx"
    mock_session.lifecycle_status = "active"
    mock_session.thinking_mode = "med"
    mock_session.closed_at = None

    fresh_session = MagicMock()
    fresh_session.tmux_session_name = "tc_ctx"
    fresh_session.native_log_file = "/tmp/codex-transcript.jsonl"
    fresh_session.project_path = "/tmp/project"
    fresh_session.working_slug = "agent-output-monitor"
    fresh_session.active_agent = "codex"

    mock_execute = AsyncMock(return_value=True)
    mock_client = MagicMock()
    scheduled_coroutines: list[Awaitable[object]] = []

    def _capture_task(coro: Awaitable[object]) -> MagicMock:
        scheduled_coroutines.append(coro)
        return MagicMock()

    with (
        patch.object(command_handlers, "tmux_io") as mock_tmux_bridge,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers.asyncio, "sleep", new=AsyncMock()),
        patch.object(command_handlers.asyncio, "create_task", side_effect=_capture_task),
        patch(
            "teleclaude.hooks.checkpoint.get_checkpoint_content",
            return_value="[TeleClaude Checkpoint] - Context-aware checkpoint\n\nok",
        ) as mock_ckpt,
        patch(
            "teleclaude.core.tmux_bridge.send_keys_existing_tmux", new=AsyncMock(return_value=True)
        ) as mock_send_keys,
    ):
        mock_tmux_bridge.send_signal = AsyncMock(return_value=True)
        mock_tmux_bridge.wait_for_shell_ready = AsyncMock(return_value=True)
        mock_get_agent_command.return_value = "codex --resume native-ctx"
        mock_config.agents.get.return_value = MagicMock()
        mock_db.get_session = AsyncMock(return_value=fresh_session)
        mock_db.update_session = AsyncMock()

        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

        assert len(scheduled_coroutines) == 1
        await scheduled_coroutines[0]

    mock_ckpt.assert_called_once_with(
        transcript_path="/tmp/codex-transcript.jsonl",
        agent_name=command_handlers.AgentName.CODEX,
        project_path="/tmp/project",
        working_slug="agent-output-monitor",
        elapsed_since_turn_start_s=None,
    )
    mock_send_keys.assert_awaited_once_with(
        session_name="tc_ctx",
        text="[TeleClaude Checkpoint] - Context-aware checkpoint\n\nok",
        send_enter=True,
    )
    assert mock_execute.await_count == 1
    assert mock_tmux_bridge.send_signal.await_count == 2
    mock_db.update_session.assert_awaited()


@pytest.mark.asyncio
async def test_handle_agent_restart_skips_post_restart_checkpoint_when_no_payload(mock_initialized_db):
    mock_session = MagicMock()
    mock_session.session_id = "restart-session-empty"
    mock_session.tmux_session_name = "tc_empty"
    mock_session.active_agent = "codex"
    mock_session.native_session_id = "native-empty"
    mock_session.lifecycle_status = "active"
    mock_session.thinking_mode = "med"
    mock_session.closed_at = None

    fresh_session = MagicMock()
    fresh_session.tmux_session_name = "tc_empty"
    fresh_session.native_log_file = "/tmp/codex-transcript.jsonl"
    fresh_session.project_path = "/tmp/project"
    fresh_session.working_slug = "agent-output-monitor"
    fresh_session.active_agent = "codex"

    mock_execute = AsyncMock(return_value=True)
    mock_client = MagicMock()
    scheduled_coroutines: list[Awaitable[object]] = []

    def _capture_task(coro: Awaitable[object]) -> MagicMock:
        scheduled_coroutines.append(coro)
        return MagicMock()

    with (
        patch.object(command_handlers, "tmux_io") as mock_tmux_bridge,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=True)),
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers.asyncio, "sleep", new=AsyncMock()),
        patch.object(command_handlers.asyncio, "create_task", side_effect=_capture_task),
        patch("teleclaude.hooks.checkpoint.get_checkpoint_content", return_value=None),
        patch(
            "teleclaude.core.tmux_bridge.send_keys_existing_tmux", new=AsyncMock(return_value=True)
        ) as mock_send_keys,
    ):
        mock_tmux_bridge.send_signal = AsyncMock(return_value=True)
        mock_tmux_bridge.wait_for_shell_ready = AsyncMock(return_value=True)
        mock_get_agent_command.return_value = "codex --resume native-empty"
        mock_config.agents.get.return_value = MagicMock()
        mock_db.get_session = AsyncMock(return_value=fresh_session)
        mock_db.update_session = AsyncMock()

        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

        assert len(scheduled_coroutines) == 1
        await scheduled_coroutines[0]

    mock_send_keys.assert_not_awaited()
    mock_db.update_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_agent_restart_revives_closed_session_before_restart(mock_initialized_db):
    """Restart should revive closed sessions before attempting resume."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-closed"
    mock_session.tmux_session_name = "tc_stale"
    mock_session.active_agent = "claude"
    mock_session.native_session_id = "native-closed"
    mock_session.lifecycle_status = "closed"
    mock_session.closed_at = datetime.now(timezone.utc)

    revived_session = MagicMock()
    revived_session.session_id = mock_session.session_id
    revived_session.tmux_session_name = "tc_revived"
    revived_session.active_agent = "claude"
    revived_session.native_session_id = "native-closed"
    revived_session.lifecycle_status = "active"
    revived_session.closed_at = None
    revived_session.thinking_mode = "slow"

    mock_execute = AsyncMock(return_value=True)
    mock_client = MagicMock()

    with (
        patch.object(command_handlers, "tmux_io") as mock_tmux_io,
        patch.object(command_handlers.tmux_bridge, "session_exists", new=AsyncMock(return_value=False)),
        patch.object(command_handlers, "_ensure_tmux_for_headless", new=AsyncMock(return_value=revived_session)),
        patch.object(command_handlers, "get_agent_command", return_value="claude --resume native-closed"),
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers.asyncio, "sleep", new=AsyncMock()),
        patch.object(command_handlers.asyncio, "create_task", side_effect=lambda coro: (coro.close(), MagicMock())[1]),
    ):
        mock_tmux_io.send_signal = AsyncMock(return_value=True)
        mock_tmux_io.wait_for_shell_ready = AsyncMock(return_value=True)
        mock_config.agents.get.return_value = MagicMock()
        mock_db.update_session = AsyncMock()
        mock_db.get_session = AsyncMock(return_value=revived_session)

        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        result = await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert result == (True, None)
    mock_db.update_session.assert_awaited_once_with(
        "restart-session-closed",
        closed_at=None,
        lifecycle_status="headless",
        tmux_session_name=None,
    )
    mock_execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_voice_sends_transcribed_text(mock_initialized_db) -> None:
    """Voice input should forward transcribed text via send_message handler."""
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()
    mock_client.delete_message = AsyncMock()

    send_calls = []

    async def record_send(*args, **kwargs):
        send_calls.append((args, kwargs))

    with (
        patch.object(command_handlers.voice_message_handler, "handle_voice", new_callable=AsyncMock) as mock_handle,
        patch.object(command_handlers, "process_message", new=record_send),
    ):
        mock_handle.return_value = "hello world"
        cmd = HandleVoiceCommand(session_id="sess-123", file_path="/tmp/voice.ogg")
        await command_handlers.handle_voice(cmd, mock_client, AsyncMock())

    assert len(send_calls) == 1


@pytest.mark.asyncio
async def test_end_session_replays_session_closed_event_for_terminal_session() -> None:
    """End session should emit session_closed for already terminal sessions."""
    mock_db = AsyncMock()
    mock_db.get_session = AsyncMock(
        return_value=Session(
            session_id="sess-closed",
            computer_name="local",
            tmux_session_name="tc-closed",
            title="Closed Session",
            closed_at=datetime.now(timezone.utc),
            lifecycle_status="closed",
        )
    )

    with (
        patch.object(command_handlers, "db", mock_db),
        patch.object(command_handlers, "terminate_session", new=AsyncMock()) as mock_terminate,
        patch.object(command_handlers.event_bus, "emit") as mock_emit,
    ):
        result = await command_handlers.end_session(
            CloseSessionCommand(session_id="sess-closed"),
            MagicMock(),
        )

    assert result["status"] == "success"
    assert "already closed" in result["message"]
    mock_emit.assert_called_once_with("session_closed", ANY)
    mock_terminate.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_file_invokes_file_handler() -> None:
    """File input should delegate to file handler with typed context."""
    mock_client = MagicMock()

    with patch.object(command_handlers, "handle_file_upload", new_callable=AsyncMock) as mock_handle:
        cmd = HandleFileCommand(
            session_id="sess-456",
            file_path="/tmp/file.txt",
            filename="file.txt",
            caption="hello",
            file_size=123,
        )
        await command_handlers.handle_file(cmd, mock_client)

    assert mock_handle.await_count == 1
    call_kwargs = mock_handle.call_args.kwargs
    context = call_kwargs["context"]
    assert context.session_id == "sess-456"
    assert context.file_path == "/tmp/file.txt"
    assert context.filename == "file.txt"


class ExecuteKwargs(TypedDict, total=False):
    """Typed kwargs payload for mock execute calls."""
