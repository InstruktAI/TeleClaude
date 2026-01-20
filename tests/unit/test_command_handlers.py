"""Unit tests for command handlers."""

import json
import os
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.config import AgentConfig
from teleclaude.core import command_handlers
from teleclaude.core.db import Db
from teleclaude.core.models import MessageMetadata
from teleclaude.core.session_cleanup import TMUX_SESSION_PREFIX
from teleclaude.types.commands import (
    CreateSessionCommand,
    GetSessionDataCommand,
    KeysCommand,
    RestartAgentCommand,
    ResumeAgentCommand,
    StartAgentCommand,
)

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")


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
        MessageMetadata(origin="telegram", project_path=tmpdir)
        with (
            patch.object(command_handlers, "config") as mock_config,
            patch.object(command_handlers, "db") as mock_db,
            patch.object(command_handlers, "tmux_bridge") as mock_tb,
            patch.object(command_handlers, "ensure_unique_title", new_callable=AsyncMock) as mock_unique,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = mock_initialized_db.create_session
            mock_db.get_session = mock_initialized_db.get_session
            mock_db.assign_voice = mock_initialized_db.assign_voice
            mock_tb.ensure_tmux_session = AsyncMock(return_value=True)
            mock_tb.get_pane_tty = AsyncMock(return_value=None)
            mock_tb.get_pane_pid = AsyncMock(return_value=None)
            mock_unique.return_value = "$TestComputer[user] - Test Title"

            cmd = CreateSessionCommand(project_path=tmpdir, title="Test Title", origin="telegram")
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
        MessageMetadata(origin="telegram", project_path=tmpdir)
        with (
            patch.object(command_handlers, "config") as mock_config,
            patch.object(command_handlers, "db") as mock_db,
            patch.object(command_handlers, "tmux_bridge") as mock_tb,
            patch.object(command_handlers, "ensure_unique_title", new_callable=AsyncMock) as mock_unique,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = mock_initialized_db.create_session
            mock_db.get_session = mock_initialized_db.get_session
            mock_db.assign_voice = mock_initialized_db.assign_voice
            mock_tb.ensure_tmux_session = AsyncMock(return_value=True)
            mock_tb.get_pane_tty = AsyncMock(return_value=None)
            mock_tb.get_pane_pid = AsyncMock(return_value=None)
            mock_unique.return_value = "$TestComputer[user] - Test Title"

            cmd = CreateSessionCommand(project_path=tmpdir, title="Test Title", origin="telegram")
            await command_handlers.create_session(cmd, mock_client)

    assert order == []
    assert mock_client.send_output_update.await_count == 0


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
            patch.object(command_handlers, "tmux_bridge") as mock_tb,
            patch.object(command_handlers, "ensure_unique_title", new_callable=AsyncMock) as mock_unique,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = mock_initialized_db.create_session
            mock_db.get_session = mock_initialized_db.get_session
            mock_db.assign_voice = mock_initialized_db.assign_voice
            mock_db.update_session = mock_initialized_db.update_session
            mock_tb.ensure_tmux_session = AsyncMock(return_value=True)
            mock_unique.return_value = "$TestComputer[user] - Test"

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

    MessageMetadata(origin="telegram", project_path=str(invalid_path))
    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()
    mock_client.send_message = AsyncMock()

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "tmux_bridge") as mock_tb,
        patch.object(command_handlers, "ensure_unique_title", new_callable=AsyncMock) as mock_unique,
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock),
    ):
        mock_config.computer.name = "TestComputer"
        mock_config.computer.default_working_dir = "/home/user"
        mock_db.create_session = mock_initialized_db.create_session
        mock_db.get_session = mock_initialized_db.get_session
        mock_db.delete_session = mock_initialized_db.delete_session
        mock_db.assign_voice = mock_initialized_db.assign_voice
        mock_tb.ensure_tmux_session = AsyncMock(return_value=True)
        mock_tb.get_pane_tty = AsyncMock(return_value=None)
        mock_tb.get_pane_pid = AsyncMock(return_value=None)
        mock_unique.return_value = "$TestComputer[user] - Untitled"

        cmd = CreateSessionCommand(project_path="/nonexistent", origin="telegram")
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

    with patch.object(command_handlers, "tmux_io") as mock_tb:
        mock_tb.send_signal = AsyncMock(return_value=True)

        await command_handlers.kill_command.__wrapped__(mock_session, cmd, AsyncMock())

    mock_tb.send_signal.assert_called_once_with(mock_session, "SIGKILL")


@pytest.mark.asyncio
async def test_handle_cancel_sends_ctrl_c():
    """Test that handle_cancel sends Ctrl+C."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    cmd = KeysCommand(session_id=mock_session.session_id, key="cancel")

    with patch.object(command_handlers, "tmux_io") as mock_tb:
        mock_tb.send_signal = AsyncMock(return_value=True)

        await command_handlers.cancel_command.__wrapped__(mock_session, cmd, AsyncMock())

    mock_tb.send_signal.assert_called_once_with(mock_session, "SIGINT")


@pytest.mark.asyncio
async def test_handle_escape_sends_esc():
    """Test that handle_escape sends ESC key."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    cmd = KeysCommand(session_id=mock_session.session_id, key="escape")

    with patch.object(command_handlers, "tmux_io") as mock_tb:
        mock_tb.send_escape = AsyncMock(return_value=True)

        await command_handlers.escape_command.__wrapped__(mock_session, cmd, AsyncMock())

    mock_tb.send_escape.assert_called_once_with(mock_session)


@pytest.mark.asyncio
async def test_handle_ctrl_sends_ctrl_key():
    """Test that handle_ctrl sends Ctrl+<key> combinations."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    cmd = KeysCommand(session_id=mock_session.session_id, key="ctrl", args=["d"])
    mock_client = MagicMock()

    with patch.object(command_handlers, "tmux_io") as mock_tb:
        mock_tb.send_ctrl_key = AsyncMock(return_value=True)

        await command_handlers.ctrl_command.__wrapped__(mock_session, cmd, mock_client, AsyncMock())

    mock_tb.send_ctrl_key.assert_called_once_with(mock_session, "d")


@pytest.mark.asyncio
async def test_handle_list_sessions_formats_output():
    """Test that list_sessions formats session list."""
    # Create mock sessions explicitly without loops
    now = datetime.now()

    s0 = MagicMock()
    s0.session_id = "session-0"
    s0.origin_adapter = "telegram"
    s0.title = "Test Session 0"
    s0.project_path = "/home/user"
    s0.created_at = now
    s0.last_activity = now
    s0.thinking_mode = "med"

    s1 = MagicMock()
    s1.session_id = "session-1"
    s1.origin_adapter = "telegram"
    s1.title = "Test Session 1"
    s1.project_path = "/home/user"
    s1.created_at = now
    s1.last_activity = now
    s1.thinking_mode = "med"

    mock_sessions = [s0, s1]

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.list_sessions = AsyncMock(return_value=mock_sessions)

        result = await command_handlers.list_sessions()

    assert len(result) == 2

    assert result[0].session_id == "session-0"
    assert result[0].origin_adapter == "telegram"
    assert result[0].title == "Test Session 0"
    assert result[0].status == "active"

    assert result[1].session_id == "session-1"
    assert result[1].origin_adapter == "telegram"
    assert result[1].title == "Test Session 1"
    assert result[1].status == "active"


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
        origin_adapter="terminal",
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

    mock_execute = AsyncMock()
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        command="claude",
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
    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    command = call_args[1]

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

    mock_execute = AsyncMock()
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        command="codex",
        session_dir="~/.codex/sessions",
        log_pattern="*.jsonl",
        model_flags={"fast": "-m gpt-5.1-codex-mini", "med": "-m gpt-5.1-codex", "slow": "-m gpt-5.2"},
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

    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    command = call_args[1]
    assert "codex" in command


@pytest.mark.asyncio
async def test_handle_agent_start_accepts_deep_for_codex(mock_initialized_db):
    """Ensure /codex deep maps to the deep model flag."""

    mock_session = MagicMock()
    mock_session.session_id = "deep-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.thinking_mode = "slow"

    mock_execute = AsyncMock()
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

    mock_execute.assert_called_once()
    # "deep" is parsed as thinking_mode, so user_args is empty -> interactive=False
    mock_get_agent_command.assert_called_once_with("codex", thinking_mode="deep", interactive=False)
    command = mock_execute.call_args[0][1]
    assert "codex -m deep" in command


@pytest.mark.asyncio
async def test_handle_agent_start_rejects_deep_for_non_codex(mock_initialized_db):
    """Ensure deep is rejected for non-codex agents."""

    mock_session = MagicMock()
    mock_session.session_id = "deep-session-456"
    mock_session.tmux_session_name = "tc_test"
    mock_session.thinking_mode = "slow"

    mock_execute = AsyncMock()
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

    mock_client.send_message.assert_awaited_once()
    mock_execute.assert_not_called()
    mock_get_agent_command.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_resume_executes_command_with_session_id_from_db(mock_initialized_db):
    """Test that agent_resume uses native_session_id from database and resume template."""

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.native_session_id = "native-123-abc"
    mock_session.thinking_mode = "slow"

    mock_execute = AsyncMock(return_value=True)
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        command="gemini --yolo",
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

    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    command = call_args[1]

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

    mock_execute = AsyncMock(return_value=True)
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        command="claude --dangerously-skip-permissions",
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

    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    command = call_args[1]

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

    mock_execute = AsyncMock(return_value=True)
    mock_client = MagicMock()

    mock_agent_config = AgentConfig(
        command="codex --yolo",
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
    mock_execute.assert_called_once()
    command = mock_execute.call_args[0][1]
    assert "resume" in command
    assert "native-override-999" in command


@pytest.mark.asyncio
async def test_handle_agent_restart_fails_without_active_agent(mock_initialized_db):
    """Restart should fail fast when no active agent is stored."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_execute = AsyncMock()
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()
    mock_session.active_agent = None
    mock_session.native_session_id = None

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "tmux_io") as mock_tmux_bridge,
    ):
        mock_tmux_bridge.send_signal = AsyncMock(return_value=True)
        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    mock_client.send_message.assert_awaited_once()
    mock_execute.assert_not_called()
    mock_tmux_bridge.send_signal.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_restart_fails_without_native_session_id(mock_initialized_db):
    """Restart should fail fast when native_session_id is missing."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-456"
    mock_session.tmux_session_name = "tc_test"
    mock_session.active_agent = "claude"
    mock_session.native_session_id = None

    mock_execute = AsyncMock()
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()

    cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
    await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    mock_client.send_message.assert_awaited_once()
    mock_execute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_restart_resumes_with_native_session_id(mock_initialized_db):
    """Restart should send SIGINTs and resume using stored native_session_id."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-789"
    mock_session.tmux_session_name = "tc_test"
    mock_session.active_agent = "claude"
    mock_session.native_session_id = "native-abc"

    mock_execute = AsyncMock()
    mock_client = MagicMock()

    with (
        patch.object(command_handlers, "tmux_io") as mock_tmux_bridge,
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
        patch.object(command_handlers.asyncio, "sleep", new=AsyncMock()),
        patch.object(command_handlers, "config") as mock_config,
    ):
        mock_tmux_bridge.send_signal = AsyncMock(return_value=True)
        mock_tmux_bridge.wait_for_shell_ready = AsyncMock(return_value=True)
        mock_get_agent_command.return_value = "claude --resume native-abc"
        mock_config.agents.get.return_value = MagicMock()

        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    assert mock_tmux_bridge.send_signal.await_count == 2
    mock_execute.assert_called_once()
    command = mock_execute.call_args[0][1]
    assert "claude --resume native-abc" in command


@pytest.mark.asyncio
async def test_handle_agent_restart_aborts_when_shell_not_ready(mock_initialized_db):
    """Restart should abort if the foreground process does not exit."""

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-999"
    mock_session.tmux_session_name = "tc_test"
    mock_session.active_agent = "claude"
    mock_session.native_session_id = "native-xyz"

    mock_execute = AsyncMock()
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock()

    with (
        patch.object(command_handlers, "tmux_io") as mock_tmux_bridge,
        patch.object(command_handlers, "config") as mock_config,
    ):
        mock_tmux_bridge.send_signal = AsyncMock(return_value=True)
        mock_tmux_bridge.wait_for_shell_ready = AsyncMock(return_value=False)
        mock_config.agents.get.return_value = MagicMock()

        cmd = RestartAgentCommand(session_id=mock_session.session_id, agent_name=None)
        await command_handlers.agent_restart.__wrapped__(mock_session, cmd, mock_client, mock_execute)

    mock_client.send_message.assert_awaited_once()
    mock_execute.assert_not_called()
