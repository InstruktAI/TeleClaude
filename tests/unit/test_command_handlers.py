"""Unit tests for command handlers."""

import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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

    with (
        patch.object(command_handlers, "config") as mock_config,
        patch.object(command_handlers, "db") as mock_db,
        patch.object(command_handlers, "terminal_bridge") as mock_tb,
        patch.object(command_handlers, "ensure_unique_title", new_callable=AsyncMock) as mock_unique,
    ):
        mock_config.computer.name = "TestComputer"
        mock_config.computer.default_working_dir = "/home/user"
        mock_db.create_session = AsyncMock(return_value=mock_session)
        mock_db.get_session = AsyncMock(return_value=mock_session)
        mock_db.assign_voice = AsyncMock()  # Voice assignment
        mock_tb.create_tmux_session = AsyncMock(return_value=True)
        mock_unique.return_value = "$TestComputer[user] - Test Title"

        result = await command_handlers.handle_create_session(
            mock_context, ["Test", "Title"], mock_metadata, mock_client
        )

    assert "session_id" in result
    mock_db.create_session.assert_called_once()
    mock_tb.create_tmux_session.assert_called_once()


@pytest.mark.asyncio
async def test_handle_new_session_validates_working_dir():
    """Test that handle_new_session validates working directory."""
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
        patch("teleclaude.core.session_cleanup.db.update_ux_state", new_callable=AsyncMock),
    ):
        mock_config.computer.name = "TestComputer"
        mock_config.computer.default_working_dir = "/home/user"
        mock_db.create_session = AsyncMock(return_value=mock_session)
        mock_db.get_session = AsyncMock(return_value=mock_session)
        mock_db.delete_session = AsyncMock()
        mock_db.assign_voice = AsyncMock()  # Voice assignment
        mock_tb.create_tmux_session = AsyncMock(return_value=False)  # Fail
        mock_unique.return_value = "Test Title"

        with pytest.raises(RuntimeError, match="Failed to create tmux session"):
            await command_handlers.handle_create_session(mock_context, [], mock_metadata, mock_client)


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

    with patch.object(command_handlers, "terminal_bridge") as mock_tb:
        mock_tb.send_signal = AsyncMock(return_value=True)

        await command_handlers.handle_kill_command.__wrapped__(mock_session, mock_context, mock_client, AsyncMock())

    mock_tb.send_signal.assert_called_once_with("tc_test", "SIGKILL")


@pytest.mark.asyncio
async def test_handle_cancel_sends_ctrl_c():
    """Test that handle_cancel sends Ctrl+C."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()

    with patch.object(command_handlers, "terminal_bridge") as mock_tb:
        mock_tb.send_signal = AsyncMock(return_value=True)

        await command_handlers.handle_cancel_command.__wrapped__(mock_session, mock_context, mock_client, AsyncMock())

    mock_tb.send_signal.assert_called_once_with("tc_test", "SIGINT")


@pytest.mark.asyncio
async def test_handle_escape_sends_esc():
    """Test that handle_escape sends ESC key."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()

    with patch.object(command_handlers, "terminal_bridge") as mock_tb:
        mock_tb.send_escape = AsyncMock(return_value=True)

        await command_handlers.handle_escape_command.__wrapped__(
            mock_session, mock_context, [], mock_client, AsyncMock()
        )

    mock_tb.send_escape.assert_called_once_with("tc_test")


@pytest.mark.asyncio
async def test_handle_ctrl_sends_ctrl_key():
    """Test that handle_ctrl sends Ctrl+<key> combinations."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"

    mock_context = MagicMock()
    mock_client = MagicMock()

    with patch.object(command_handlers, "terminal_bridge") as mock_tb:
        mock_tb.send_ctrl_key = AsyncMock(return_value=True)

        await command_handlers.handle_ctrl_command.__wrapped__(
            mock_session, mock_context, ["d"], mock_client, AsyncMock()
        )

    mock_tb.send_ctrl_key.assert_called_once_with("tc_test", "d")


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
async def test_handle_claude_starts_claude_code():
    """Test that handle_claude starts Claude Code session."""
    from teleclaude.core import command_handlers

    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"
    mock_session.tmux_session_name = "tc_test"
    mock_session.working_directory = "/home/user/project"
    mock_session.terminal_size = "120x40"

    mock_context = MagicMock()
    mock_context.message_id = "msg-123"

    # Mock execute_terminal_command that handle_claude_session expects
    mock_execute = AsyncMock(return_value=True)

    with patch.object(command_handlers, "config") as mock_config:
        mock_config.mcp.claude_command = "claude"

        # handle_claude_session signature: session, context, args, execute_terminal_command
        await command_handlers.handle_claude_session.__wrapped__(
            mock_session, mock_context, ["Hello Claude"], mock_execute
        )

    # Verify execute_terminal_command was called with claude command
    mock_execute.assert_called_once()
    call_args = mock_execute.call_args[0]
    # First arg is session_id, second is command
    assert "claude" in call_args[1].lower()


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
        s.closed = False
        s.created_at = datetime.now()
        s.last_activity = datetime.now()
        mock_sessions.append(s)

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

    mock_ux_state = MagicMock()
    mock_ux_state.claude_session_file = None  # No file yet

    mock_context = MagicMock(spec=EventContext)
    mock_context.session_id = "test-session-123"

    with patch.object(command_handlers, "db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)
        mock_db.get_ux_state = AsyncMock(return_value=mock_ux_state)

        result = await command_handlers.handle_get_session_data(mock_context, [])

    # No claude_session_file means error
    assert result["status"] == "error"
    assert "file" in result["error"].lower()


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
