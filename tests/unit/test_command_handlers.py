"""Unit tests for command handlers."""

import json
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
async def mock_initialized_db(monkeypatch):
    """Fixture to provide a mocked, initialized database connection."""
    import aiosqlite

    from teleclaude.core.db import Db

    # Create an in-memory SQLite database
    mock_conn = await aiosqlite.connect(":memory:")
    await mock_conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY, ux_state TEXT)")
    await mock_conn.commit()

    # Create a mock Db instance that uses our in-memory connection
    mock_db_instance = Db(":memory:")
    mock_db_instance._db = mock_conn  # Directly set the connection

    # Patch the global db object in command_handlers module
    monkeypatch.setattr("teleclaude.core.command_handlers.db", mock_db_instance)
    monkeypatch.setattr("teleclaude.core.db.db", mock_db_instance)  # Also patch the singleton itself

    yield mock_db_instance

    await mock_conn.close()


@pytest.mark.asyncio
async def test_handle_get_computer_info_returns_system_stats():
    """Test that handle_get_computer_info returns system stats."""
    from teleclaude.core import command_handlers

    # Mock config values
    mock_config = MagicMock()
    mock_config.computer.user = "testuser"
    mock_config.computer.role = "development"
    mock_config.computer.host = "test.local"

    with patch.object(command_handlers, "config", mock_config):
        result = await command_handlers.handle_get_computer_info()

    # Verify basic fields
    assert result["user"] == "testuser"
    assert result["role"] == "development"
    assert result["host"] == "test.local"

    # Verify system_stats structure
    assert "system_stats" in result
    system_stats = result["system_stats"]

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
async def test_handle_new_session_creates_session():
    """Test that handle_new_session creates a session with correct metadata."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext
    from teleclaude.core.models import MessageMetadata

    mock_context = MagicMock(spec=EventContext)
    mock_metadata = MessageMetadata(adapter_type="telegram")
    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()
    mock_client.send_feedback = AsyncMock()

    # Mock session object
    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test-ses"

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch.object(command_handlers, "config") as mock_config,
            patch.object(command_handlers, "db") as mock_db,
            patch.object(command_handlers, "terminal_bridge") as mock_tb,
            patch.object(command_handlers, "ensure_unique_title", new_callable=AsyncMock) as mock_unique,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = AsyncMock(return_value=mock_session)
            mock_db.get_session = AsyncMock(return_value=mock_session)
            mock_db.assign_voice = AsyncMock()  # Voice assignment
            mock_tb.create_tmux_session = AsyncMock(return_value=True)
            mock_tb.get_pane_tty = AsyncMock(return_value=None)
            mock_tb.get_pane_pid = AsyncMock(return_value=None)
            mock_unique.return_value = "$TestComputer[user] - Test Title"

            result = await command_handlers.handle_create_session(
                mock_context, ["Test", "Title"], mock_metadata, mock_client
            )

    assert "session_id" in result
    mock_db.create_session.assert_called_once()
    mock_tb.create_tmux_session.assert_called_once()
    created_session_id = mock_db.create_session.call_args.kwargs.get("session_id")
    _, call_kwargs = mock_tb.create_tmux_session.call_args
    env_vars = call_kwargs.get("env_vars") or {}
    assert env_vars.get("TELECLAUDE_SESSION_ID") == created_session_id
    assert call_kwargs.get("session_id") == created_session_id


@pytest.mark.asyncio
async def test_handle_create_session_terminal_metadata_updates_size_and_ux_state():
    """Terminal adapter should honor terminal metadata for size and UX state."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext
    from teleclaude.core.models import MessageMetadata

    mock_context = MagicMock(spec=EventContext)
    mock_metadata = MessageMetadata(
        adapter_type="terminal",
        channel_metadata={
            "terminal": {
                "tty_path": "/dev/pts/7",
                "parent_pid": 4242,
                "terminal_size": "200x55",
            }
        },
    )
    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()
    mock_client.send_feedback = AsyncMock()

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test-ses"

    with tempfile.TemporaryDirectory() as tmpdir:
        with (
            patch.object(command_handlers, "config") as mock_config,
            patch.object(command_handlers, "db") as mock_db,
            patch.object(command_handlers, "terminal_bridge") as mock_tb,
            patch.object(command_handlers, "ensure_unique_title", new_callable=AsyncMock) as mock_unique,
        ):
            mock_config.computer.name = "TestComputer"
            mock_config.computer.default_working_dir = tmpdir
            mock_db.create_session = AsyncMock(return_value=mock_session)
            mock_db.get_session = AsyncMock(return_value=mock_session)
            mock_db.assign_voice = AsyncMock()
            mock_db.update_session = AsyncMock()
            mock_tb.create_tmux_session = AsyncMock(return_value=True)
            mock_unique.return_value = "$TestComputer[user] - Test Title"

            await command_handlers.handle_create_session(mock_context, ["Test"], mock_metadata, mock_client)

            _, create_kwargs = mock_db.create_session.call_args
            assert create_kwargs.get("terminal_size") == "200x55"

            _, tmux_kwargs = mock_tb.create_tmux_session.call_args
            assert tmux_kwargs.get("cols") == 200
            assert tmux_kwargs.get("rows") == 55

            update_args, update_kwargs = mock_db.update_session.call_args
            assert update_args[0] == create_kwargs.get("session_id")
            assert update_kwargs.get("native_tty_path") == "/dev/pts/7"
            assert update_kwargs.get("native_pid") == 4242


@pytest.mark.asyncio
async def test_handle_new_session_validates_working_dir():
    """Test that handle_new_session rejects non-existent working directories."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext
    from teleclaude.core.models import MessageMetadata

    mock_context = MagicMock(spec=EventContext)
    mock_metadata = MessageMetadata(adapter_type="telegram", project_dir="/nonexistent/path")
    mock_client = MagicMock()
    mock_client.create_channel = AsyncMock()
    mock_client.send_feedback = AsyncMock()

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "terminal_bridge") as mock_tb,
        patch.object(command_handlers, "ensure_unique_title", new_callable=AsyncMock) as mock_unique,
        patch("teleclaude.core.session_cleanup.db.clear_pending_deletions", new_callable=AsyncMock),
        patch("teleclaude.core.session_cleanup.db.update_session", new_callable=AsyncMock),
    ):
        mock_config.computer.name = "TestComputer"
        mock_config.computer.default_working_dir = "/home/user"
        mock_db.create_session = AsyncMock(return_value=mock_session)
        mock_db.get_session = AsyncMock(return_value=mock_session)
        mock_db.delete_session = AsyncMock()
        mock_db.assign_voice = AsyncMock()  # Voice assignment
        mock_tb.create_tmux_session = AsyncMock(return_value=True)
        mock_tb.get_pane_tty = AsyncMock(return_value=None)
        mock_tb.get_pane_pid = AsyncMock(return_value=None)
        mock_unique.return_value = "Test Title"

        with pytest.raises(ValueError, match="could not be created"):
            await command_handlers.handle_create_session(mock_context, [], mock_metadata, mock_client)

        mock_tb.create_tmux_session.assert_not_called()


@pytest.mark.asyncio
async def test_handle_cd_changes_directory():
    """Test that handle_cd changes working directory."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()
    mock_client.send_feedback = AsyncMock(return_value="msg-123")

    # Mock execute_terminal_command
    mock_execute = AsyncMock(return_value=True)

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(command_handlers, "db") as mock_db:
            mock_db.update_session = AsyncMock()
            mock_db.add_pending_deletion = AsyncMock()

            # handle_cd_session signature: session, context, args, client, execute_terminal_command
            await command_handlers.handle_cd_session.__wrapped__(
                mock_session, mock_context, [tmpdir], mock_client, mock_execute
            )

        mock_db.update_session.assert_called_once()


@pytest.mark.asyncio
async def test_handle_cd_executes_command_for_any_path():
    """Test that handle_cd executes cd command for any path (validation in terminal)."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_context.message_id = "msg-123"
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value="msg-456")

    # Mock execute_terminal_command to simulate success
    mock_execute = AsyncMock(return_value=True)

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.add_pending_deletion = AsyncMock()
        mock_db.update_session = AsyncMock()

        # Path validation happens in terminal, not Python
        await command_handlers.handle_cd_session.__wrapped__(
            mock_session, mock_context, ["/some/path"], mock_client, mock_execute
        )

    # Verify execute_terminal_command was called
    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    assert "cd" in call_args[1]
    assert "/some/path" in call_args[1]


@pytest.mark.asyncio
async def test_handle_kill_terminates_process():
    """Test that handle_kill sends SIGKILL to running process."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()

    with patch.object(command_handlers, "terminal_io") as mock_tb:
        mock_tb.send_signal = AsyncMock(return_value=True)

        await command_handlers.handle_kill_command.__wrapped__(mock_session, mock_context, mock_client, AsyncMock())

    mock_tb.send_signal.assert_called_once_with(mock_session, "SIGKILL")


@pytest.mark.asyncio
async def test_handle_cancel_sends_ctrl_c():
    """Test that handle_cancel sends Ctrl+C."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()

    with patch.object(command_handlers, "terminal_io") as mock_tb:
        mock_tb.send_signal = AsyncMock(return_value=True)

        await command_handlers.handle_cancel_command.__wrapped__(mock_session, mock_context, mock_client, AsyncMock())

    mock_tb.send_signal.assert_called_once_with(mock_session, "SIGINT")


@pytest.mark.asyncio
async def test_handle_escape_sends_esc():
    """Test that handle_escape sends ESC key."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()

    with patch.object(command_handlers, "terminal_io") as mock_tb:
        mock_tb.send_escape = AsyncMock(return_value=True)

        await command_handlers.handle_escape_command.__wrapped__(
            mock_session, mock_context, [], mock_client, AsyncMock()
        )

    mock_tb.send_escape.assert_called_once_with(mock_session)


@pytest.mark.asyncio
async def test_handle_ctrl_sends_ctrl_key():
    """Test that handle_ctrl sends Ctrl+<key> combinations."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()

    with patch.object(command_handlers, "terminal_io") as mock_tb:
        mock_tb.send_ctrl_key = AsyncMock(return_value=True)

        await command_handlers.handle_ctrl_command.__wrapped__(
            mock_session, mock_context, ["d"], mock_client, AsyncMock()
        )

    mock_tb.send_ctrl_key.assert_called_once_with(mock_session, "d")


@pytest.mark.asyncio
async def test_handle_rename_updates_title():
    """Test that handle_rename updates session title."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()
    mock_client.update_channel_title = AsyncMock()
    mock_client.send_message = AsyncMock(return_value="msg-123")
    mock_client.send_feedback = AsyncMock(return_value="msg-123")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.update_session = AsyncMock()
        mock_db.add_pending_deletion = AsyncMock()

        # handle_rename_session signature: session, context, args, client (no start_polling)
        await command_handlers.handle_rename_session.__wrapped__(
            mock_session, mock_context, ["New", "Title"], mock_client
        )

    mock_db.update_session.assert_called_once()
    mock_client.update_channel_title.assert_called_once()


@pytest.mark.asyncio
async def test_handle_list_sessions_formats_output():
    """Test that handle_list_sessions formats session list."""
    from datetime import datetime

    from teleclaude.core import command_handlers

    # Create mock sessions
    mock_sessions = []
    for i in range(2):
        s = MagicMock()
        s.session_id = f"session-{i}"
        s.origin_adapter = "telegram"
        s.title = f"Test Session {i}"
        s.working_directory = "/home/user"
        s.created_at = datetime.now()
        s.last_activity = datetime.now()
        mock_sessions.append(s)

    # Set thinking_mode on mock sessions
    for s in mock_sessions:
        s.thinking_mode = "med"

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.list_sessions = AsyncMock(return_value=mock_sessions)

        result = await command_handlers.handle_list_sessions()

    assert len(result) == 2
    for session_data in result:
        assert "session_id" in session_data
        assert "origin_adapter" in session_data
        assert "title" in session_data
        assert session_data["status"] == "active"


@pytest.mark.asyncio
async def test_handle_get_session_data_returns_transcript():
    """Test that handle_get_session_data returns session transcript."""
    from datetime import datetime

    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.title = "Test Session"
    mock_session.working_directory = "/home/user"
    mock_session.created_at = datetime.now()
    mock_session.last_activity = datetime.now()
    mock_session.native_log_file = None  # No file yet

    mock_context = MagicMock(spec=EventContext)
    mock_context.session_id = "test-session-123"

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.handle_get_session_data(mock_context, [])

    # No claude_session_file means error
    assert result["status"] == "error"
    assert "file" in result["error"].lower()


@pytest.mark.asyncio
async def test_handle_get_session_data_returns_markdown(tmp_path):
    """Verify successful transcript parsing path for existing file."""
    from datetime import datetime

    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "test-session-456"
    mock_session.title = "Markdown Session"
    mock_session.working_directory = "/home/user"
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

    mock_context = MagicMock(spec=EventContext)
    mock_context.session_id = "test-session-456"

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)

        result = await command_handlers.handle_get_session_data(mock_context)

    assert result["status"] == "success"
    assert "Markdown Session" in result["messages"]
    assert "hi" in result["messages"]
    assert "hello" in result["messages"]


@pytest.mark.asyncio
async def test_handle_get_session_data_returns_error_for_missing_session():
    """Test that handle_get_session_data returns error for missing sessions."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_context = MagicMock(spec=EventContext)
    mock_context.session_id = "missing-session"

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        result = await command_handlers.handle_get_session_data(mock_context)

    assert result["status"] == "error"
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_handle_list_projects_returns_trusted_dirs():
    """Test that handle_list_projects returns trusted directories."""
    from teleclaude.core import command_handlers

    mock_trusted_dir = MagicMock()
    mock_trusted_dir.name = "Project"
    mock_trusted_dir.desc = "Test project"
    mock_trusted_dir.path = "/tmp"  # Use /tmp as it always exists

    with patch.object(command_handlers, "config") as mock_config:
        mock_config.computer.get_all_trusted_dirs.return_value = [mock_trusted_dir]

        result = await command_handlers.handle_list_projects()

    assert len(result) == 1
    assert result[0]["name"] == "Project"
    assert result[0]["desc"] == "Test project"
    assert "/tmp" in result[0]["location"]


@pytest.mark.asyncio
async def test_handle_ctrl_requires_key_argument():
    """Test that handle_ctrl requires a key argument."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"

    mock_context = MagicMock()
    mock_client = MagicMock()
    mock_client.send_message = AsyncMock(return_value="msg-123")

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.add_pending_deletion = AsyncMock()

        await command_handlers.handle_ctrl_command.__wrapped__(mock_session, mock_context, [], mock_client, AsyncMock())

    # Verify usage message was sent
    mock_client.send_message.assert_called_once()
    call_args = mock_client.send_message.call_args[0]
    assert "Usage" in call_args[1]


@pytest.mark.asyncio
async def test_handle_agent_start_executes_command_with_args(mock_initialized_db):
    """Test that handle_agent_start executes agent's command with provided arguments."""
    from teleclaude.config import AgentConfig
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "model-session-789"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock(spec=EventContext)
    mock_context.message_id = "msg-123"
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

        await command_handlers.handle_agent_start.__wrapped__(
            mock_session, mock_context, "claude", ["--model=haiku", "--test"], mock_client, mock_execute
        )

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
    """Test that handle_agent_start executes agent's command correctly when no extra args are provided."""
    from teleclaude.config import AgentConfig
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "regular-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock(spec=EventContext)
    mock_context.message_id = "msg-456"
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

        await command_handlers.handle_agent_start.__wrapped__(
            mock_session, mock_context, "codex", [], mock_client, mock_execute
        )

    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    command = call_args[1]
    assert "codex" in command


@pytest.mark.asyncio
async def test_handle_agent_start_accepts_deep_for_codex(mock_initialized_db):
    """Ensure /codex deep maps to the deep model flag."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "deep-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.thinking_mode = "slow"

    mock_context = MagicMock(spec=EventContext)
    mock_context.message_id = "msg-deep"
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

        await command_handlers.handle_agent_start.__wrapped__(
            mock_session, mock_context, "codex", ["deep"], mock_client, mock_execute
        )

    mock_execute.assert_called_once()
    # "deep" is parsed as thinking_mode, so user_args is empty -> interactive=False
    mock_get_agent_command.assert_called_once_with("codex", thinking_mode="deep", interactive=False)
    command = mock_execute.call_args[0][1]
    assert "codex -m deep" in command


@pytest.mark.asyncio
async def test_handle_agent_start_rejects_deep_for_non_codex(mock_initialized_db):
    """Ensure deep is rejected for non-codex agents."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "deep-session-456"
    mock_session.tmux_session_name = "tc_test"
    mock_session.thinking_mode = "slow"

    mock_context = MagicMock(spec=EventContext)
    mock_context.message_id = "msg-deep"
    mock_execute = AsyncMock()
    mock_client = MagicMock()
    mock_client.send_feedback = AsyncMock()

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
    ):
        mock_config.agents.get.return_value = MagicMock()
        mock_db.update_session = AsyncMock()

        await command_handlers.handle_agent_start.__wrapped__(
            mock_session, mock_context, "claude", ["deep"], mock_client, mock_execute
        )

    mock_client.send_feedback.assert_awaited_once()
    mock_execute.assert_not_called()
    mock_get_agent_command.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_resume_executes_command_with_session_id_from_db(mock_initialized_db):
    """Test that handle_agent_resume uses native_session_id from database and resume template."""
    from teleclaude.config import AgentConfig
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.native_session_id = "native-123-abc"
    mock_session.thinking_mode = "slow"

    mock_context = MagicMock(spec=EventContext)
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

        await command_handlers.handle_agent_resume.__wrapped__(
            mock_session, mock_context, "gemini", [], mock_client, mock_execute
        )

    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    command = call_args[1]

    # Gemini uses --resume flag with session ID from database
    assert "--yolo" in command
    assert "--resume" in command
    assert "native-123-abc" in command


@pytest.mark.asyncio
async def test_handle_agent_resume_uses_continue_template_when_no_native_session_id(mock_initialized_db):
    """Test that handle_agent_resume continues latest conversation when no native_session_id is stored."""
    from teleclaude.config import AgentConfig
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "test-session-continue-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.native_session_id = None
    mock_session.thinking_mode = "slow"

    mock_context = MagicMock(spec=EventContext)
    mock_context.message_id = "msg-continue-123"
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

        await command_handlers.handle_agent_resume.__wrapped__(
            mock_session, mock_context, "claude", [], mock_client, mock_execute
        )

    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    command = call_args[1]

    # Check for Claude's key flags and continue template behavior
    assert "--dangerously-skip-permissions" in command
    assert command.endswith("--continue")
    assert "--resume" not in command
    assert "-m " not in command  # continue_template path skips model flag


@pytest.mark.asyncio
async def test_handle_agent_restart_fails_without_active_agent(mock_initialized_db):
    """Restart should fail fast when no active agent is stored."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock(spec=EventContext)
    mock_execute = AsyncMock()
    mock_client = MagicMock()
    mock_client.send_feedback = AsyncMock()

    mock_ux_state = MagicMock()
    mock_ux_state.active_agent = None
    mock_ux_state.native_session_id = None
    mock_ux_state.thinking_mode = "slow"

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "terminal_io") as mock_terminal_bridge,
    ):
        mock_db.get_ux_state = AsyncMock(return_value=mock_ux_state)
        mock_terminal_bridge.send_signal = AsyncMock(return_value=True)

        await command_handlers.handle_agent_restart.__wrapped__(
            mock_session, mock_context, "", [], mock_client, mock_execute
        )

    mock_client.send_feedback.assert_awaited_once()
    mock_execute.assert_not_called()
    mock_terminal_bridge.send_signal.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_restart_fails_without_native_session_id(mock_initialized_db):
    """Restart should fail fast when native_session_id is missing."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-456"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock(spec=EventContext)
    mock_execute = AsyncMock()
    mock_client = MagicMock()
    mock_client.send_feedback = AsyncMock()

    mock_ux_state = MagicMock()
    mock_ux_state.active_agent = "claude"
    mock_ux_state.native_session_id = None
    mock_ux_state.thinking_mode = "slow"

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_ux_state = AsyncMock(return_value=mock_ux_state)

        await command_handlers.handle_agent_restart.__wrapped__(
            mock_session, mock_context, "", [], mock_client, mock_execute
        )

    mock_client.send_feedback.assert_awaited_once()
    mock_execute.assert_not_called()


@pytest.mark.asyncio
async def test_handle_agent_restart_resumes_with_native_session_id(mock_initialized_db):
    """Restart should send SIGINTs and resume using stored native_session_id."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-789"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock(spec=EventContext)
    mock_execute = AsyncMock()
    mock_client = MagicMock()

    mock_ux_state = MagicMock()
    mock_ux_state.active_agent = "claude"
    mock_ux_state.native_session_id = "native-abc"
    mock_ux_state.thinking_mode = "slow"

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "terminal_io") as mock_terminal_bridge,
        patch.object(command_handlers, "get_agent_command") as mock_get_agent_command,
        patch.object(command_handlers.asyncio, "sleep", new=AsyncMock()),
        patch.object(command_handlers, "config") as mock_config,
    ):
        mock_db.get_ux_state = AsyncMock(return_value=mock_ux_state)
        mock_terminal_bridge.send_signal = AsyncMock(return_value=True)
        mock_terminal_bridge.wait_for_shell_ready = AsyncMock(return_value=True)
        mock_get_agent_command.return_value = "claude --resume native-abc"
        mock_config.agents.get.return_value = MagicMock()

        await command_handlers.handle_agent_restart.__wrapped__(
            mock_session, mock_context, "", [], mock_client, mock_execute
        )

    assert mock_terminal_bridge.send_signal.await_count == 2
    mock_execute.assert_called_once()
    command = mock_execute.call_args[0][1]
    assert "claude --resume native-abc" in command


@pytest.mark.asyncio
async def test_handle_agent_restart_aborts_when_shell_not_ready(mock_initialized_db):
    """Restart should abort if the foreground process does not exit."""
    from teleclaude.core import command_handlers
    from teleclaude.core.events import EventContext

    mock_session = MagicMock()
    mock_session.session_id = "restart-session-999"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock(spec=EventContext)
    mock_execute = AsyncMock()
    mock_client = MagicMock()
    mock_client.send_feedback = AsyncMock()

    mock_ux_state = MagicMock()
    mock_ux_state.active_agent = "claude"
    mock_ux_state.native_session_id = "native-xyz"
    mock_ux_state.thinking_mode = "slow"

    with (
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "terminal_io") as mock_terminal_bridge,
        patch.object(command_handlers, "config") as mock_config,
    ):
        mock_db.get_ux_state = AsyncMock(return_value=mock_ux_state)
        mock_terminal_bridge.send_signal = AsyncMock(return_value=True)
        mock_terminal_bridge.wait_for_shell_ready = AsyncMock(return_value=False)
        mock_config.agents.get.return_value = MagicMock()

        await command_handlers.handle_agent_restart.__wrapped__(
            mock_session, mock_context, "", [], mock_client, mock_execute
        )

    mock_client.send_feedback.assert_awaited_once()
    mock_execute.assert_not_called()
