"""Unit tests for MCP server tools."""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.models import ComputerInfo, SessionSummary, ThinkingMode
from teleclaude.mcp_server import MCP_SESSION_DATA_MAX_CHARS, TeleClaudeMCPServer

CALLER_SESSION_ID = "caller-session-123"

# System boundary: MCP tools dispatch events to the adapter client. Payload assertions verify this boundary.


@pytest.fixture
def mock_mcp_server():
    """Create MCP server with mocked dependencies."""
    mock_client = MagicMock()
    mock_client.discover_peers = AsyncMock(return_value=[])
    mock_client.handle_event = AsyncMock(return_value={"status": "success", "data": {}})
    mock_client.handle_internal_command = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "test-session-123"}}
    )

    mock_tmux_bridge = MagicMock()

    # Mock caller session for db.get_session
    mock_caller_session = MagicMock()
    mock_caller_session.active_agent = "claude"
    mock_caller_session.thinking_mode = "slow"

    with (
        patch("teleclaude.mcp_server.config") as mock_config,
        patch("teleclaude.mcp.handlers.db") as mock_db,
    ):
        mock_config.computer.name = "TestComputer"
        mock_config.mcp.socket_path = "/tmp/test.sock"
        mock_db.get_session = AsyncMock(return_value=mock_caller_session)

        server = TeleClaudeMCPServer(adapter_client=mock_client, tmux_bridge=mock_tmux_bridge)

        yield server


@pytest.mark.asyncio
async def test_teleclaude_list_computers_returns_online_computers(mock_mcp_server):
    """Test that list_computers returns online computers from heartbeat."""
    server = mock_mcp_server

    # Mock get_computer_info for local computer
    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.get_computer_info = AsyncMock(
            return_value=ComputerInfo(
                name="TestComputer",
                status="online",
                user="testuser",
                host="localhost",
                role="development",
                is_local=True,
                system_stats={"memory": {"percent_used": 50.0}},
            )
        )

        # Mock discover_peers to return remote peers
        server.client.discover_peers = AsyncMock(
            return_value=[
                {
                    "name": "RemotePC",
                    "status": "online",
                    "last_seen": datetime.now(timezone.utc),
                    "user": "remoteuser",
                    "host": "remote.local",
                }
            ]
        )

        result = await server.teleclaude__list_computers()

        assert len(result) == 2
        # First is local computer
        assert result[0]["name"] == "TestComputer"
        assert result[0]["status"] == "local"
        # Second is remote
        assert result[1]["name"] == "RemotePC"
        assert result[1]["status"] == "online"


@pytest.mark.asyncio
async def test_teleclaude_list_sessions_formats_sessions(mock_mcp_server):
    """Test that list_sessions formats session data for MCP."""
    server = mock_mcp_server

    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.list_sessions = AsyncMock(
            return_value=[
                SessionSummary(
                    session_id="test-session-123",
                    origin_adapter="telegram",
                    title="Test Session",
                    project_path="/home/user",
                    thinking_mode="slow",
                    active_agent=None,
                    status="active",
                )
            ]
        )

        result = await server.teleclaude__list_sessions(computer="local")

        assert len(result) == 1
        assert result[0]["session_id"] == "test-session-123"
        assert result[0]["origin_adapter"] == "telegram"
        assert result[0]["computer"] == "TestComputer"


@pytest.mark.asyncio
async def test_teleclaude_start_session_creates_session(mock_mcp_server):
    """Test that start_session creates a new session."""
    server = mock_mcp_server

    # Mock handle_internal_command to return success with session_id
    server.client.handle_internal_command = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "new-session-456"}}
    )

    with patch("teleclaude.mcp.handlers.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Test Session",
            message="Hello Claude",
            caller_session_id=CALLER_SESSION_ID,
        )

        assert result["status"] == "success"
    assert result["session_id"] == "new-session-456"


@pytest.mark.asyncio
async def test_teleclaude_send_message_forwards_to_handler(mock_mcp_server):
    """Test that send_message forwards to command handler."""
    server = mock_mcp_server

    server.client.handle_internal_command = AsyncMock(return_value={"status": "success"})

    chunks = []
    async for chunk in server.teleclaude__send_message(
        computer="local",
        session_id="test-session-123",
        message="ls -la",
        caller_session_id=CALLER_SESSION_ID,
    ):
        chunks.append(chunk)

    result = "".join(chunks)
    assert "Message sent" in result
    assert "test-ses" in result  # First 8 chars of session_id


@pytest.mark.asyncio
async def test_teleclaude_send_file_handles_upload(mock_mcp_server):
    """Test that send_file uploads file to session."""
    import tempfile

    server = mock_mcp_server

    # Create temp file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("Test content")
        test_file = f.name

    try:
        # Mock db.get_session
        mock_session = MagicMock()
        mock_session.session_id = "test-session-123"

        with patch("teleclaude.mcp.handlers.db") as mock_db:
            mock_db.get_session = AsyncMock(return_value=mock_session)
            server.client.send_file = AsyncMock(return_value="file-msg-123")

            result = await server.teleclaude__send_file(
                session_id="test-session-123",
                file_path=test_file,
                caption="Test caption",
            )

            assert "File sent successfully" in result
            assert "file-msg-123" in result
    finally:
        Path(test_file).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_teleclaude_get_session_data_formats_transcript(mock_mcp_server):
    """Test that get_session_data returns transcript summary."""
    server = mock_mcp_server

    # Mock command handler
    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.get_session_data = AsyncMock(
            return_value={
                "status": "success",
                "session_id": "test-session-123",
                "messages": "Parsed transcript content",
            }
        )

        result = await server.teleclaude__get_session_data(
            computer="local",
            session_id="test-session-123",
            caller_session_id=CALLER_SESSION_ID,
        )

        assert result["status"] == "success"
        assert result["messages"] == "Parsed transcript content"


@pytest.mark.asyncio
async def test_teleclaude_get_session_data_caps_large_transcripts(mock_mcp_server):
    """Test that large transcripts are capped to protect transport."""
    server = mock_mcp_server

    # Create large transcript (> 48KB)
    large_transcript = "A" * (MCP_SESSION_DATA_MAX_CHARS + 1000)

    # Mock command handler
    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.get_session_data = AsyncMock(
            return_value={
                "status": "success",
                "session_id": "test-session-123",
                "messages": large_transcript,
            }
        )

        result = await server.teleclaude__get_session_data(
            computer="local",
            session_id="test-session-123",
            caller_session_id=CALLER_SESSION_ID,
        )

    assert result["status"] == "success"
    assert len(result["messages"]) <= MCP_SESSION_DATA_MAX_CHARS
    assert result["truncated"] is True
    assert "Response capped" in result["cap_notice"]


@pytest.mark.asyncio
async def test_teleclaude_send_file_validates_file_path(mock_mcp_server):
    """Test that send_file rejects invalid paths."""
    server = mock_mcp_server

    # Non-existent file
    result = await server.teleclaude__send_file(
        session_id="test-session-123",
        file_path="/nonexistent/file.txt",
    )
    assert "Error: File not found" in result

    # Directory instead of file
    with tempfile.TemporaryDirectory() as tmpdir:
        result = await server.teleclaude__send_file(
            session_id="test-session-123",
            file_path=tmpdir,
        )
        assert "Error: Not a file" in result


@pytest.mark.asyncio
async def test_mcp_tools_handle_invalid_session_id(mock_mcp_server):
    """Test that tools return errors for missing sessions."""
    server = mock_mcp_server

    # Mock db.get_session to return None
    with patch("teleclaude.mcp.handlers.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        # Use an existing path (the test file itself)
        existing_path = __file__

        # test send_file
        result = await server.teleclaude__send_file(
            session_id="missing-sess",
            file_path=existing_path,
        )
        assert "Error: Session missing-sess not found" in result


@pytest.mark.asyncio
async def test_teleclaude_start_session_with_agent_parameter(mock_mcp_server):
    """Test that start_session dispatches correct agent event based on parameter."""
    server = mock_mcp_server

    # Mock handle_internal_command
    async def mock_handle_cmd(cmd, **kwargs):
        if cmd.command_type == "create_session":
            sid = "agent-test-123"
            if "Gemini" in cmd.title:
                sid = "agent-test-123"
            elif "Codex" in cmd.title:
                sid = "agent-test-456"
            elif "Claude" in cmd.title:
                sid = "agent-test-789"
            if "Fast" in cmd.title:
                sid = "agent-test-fast"
            return {"status": "success", "data": {"session_id": sid}}
        return {"status": "success"}

    server.client.handle_internal_command = AsyncMock(side_effect=mock_handle_cmd)

    with patch("teleclaude.mcp.handlers.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        # Test 1: Gemini agent
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Gemini Session",
            message="Hello Gemini",
            agent="gemini",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        assert result["session_id"] == "agent-test-123"

        # Test 2: Codex agent
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Codex Session",
            message="Hello Codex",
            agent="codex",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        assert result["session_id"] == "agent-test-456"

        # Test 3: Claude agent (default)
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Claude Session",
            message="Hello Claude",
            agent="claude",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        assert result["session_id"] == "agent-test-789"

        # Test explicit fast mode
        result = await server.teleclaude__start_session(
            computer="local",
            project_path="/home/user/project",
            title="Fast Claude Session",
            message="Hello Claude",
            agent="claude",
            thinking_mode=ThinkingMode.FAST,
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        assert result["session_id"] == "agent-test-fast"


@pytest.mark.asyncio
async def test_run_agent_command_passes_mode_for_new_session(mock_mcp_server):
    """Test that run_agent_command passes thinking_mode for new sessions."""
    server = mock_mcp_server
    server.client.handle_internal_command = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "sess-123"}}
    )

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        args="",
        project="/home/user/project",
        agent="codex",
        thinking_mode=ThinkingMode.MED,
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    server.client.handle_internal_command.assert_awaited_once()
    call_args = server.client.handle_internal_command.call_args
    call_args[0][0]
    metadata = call_args[1].get("metadata")
    assert metadata is not None
    assert "codex" in metadata.auto_command
    assert "med" in metadata.auto_command


@pytest.mark.asyncio
async def test_run_agent_command_ignores_mode_when_session_provided(mock_mcp_server):
    """Test that run_agent_command ignores thinking_mode when session_id provided."""
    server = mock_mcp_server

    async def fake_send_message(*_args, **_kwargs):
        yield "sent"

    server.teleclaude__send_message = fake_send_message
    server.teleclaude__start_session = AsyncMock()

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        session_id="existing-session",
        thinking_mode=ThinkingMode.FAST,
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "sent"
    server.teleclaude__start_session.assert_not_called()


# --- run_agent_command tests ---


@pytest.mark.asyncio
async def test_run_agent_command_normalizes_leading_slash(mock_mcp_server):
    """Test that run_agent_command strips leading / from command."""
    server = mock_mcp_server
    server.client.handle_internal_command = AsyncMock(return_value={"status": "success"})

    # Call with leading slash - should be normalized
    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="/compact",
        session_id="test-session-123",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "sent"
    # Verify the message sent was /compact (single slash)
    call_args = server.client.handle_internal_command.call_args
    command = call_args[0][0]
    assert command.text == "/compact"


@pytest.mark.asyncio
async def test_run_agent_command_without_leading_slash(mock_mcp_server):
    """Test that run_agent_command adds / to command without leading slash."""
    server = mock_mcp_server
    server.client.handle_internal_command = AsyncMock(return_value={"status": "success"})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="compact",
        session_id="test-session-123",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "sent"
    call_args = server.client.handle_internal_command.call_args
    command = call_args[0][0]
    assert command.text == "/compact"


@pytest.mark.asyncio
async def test_run_agent_command_with_args(mock_mcp_server):
    """Test that run_agent_command appends args to command."""
    server = mock_mcp_server
    server.client.handle_internal_command = AsyncMock(return_value={"status": "success"})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        args="my-feature",
        session_id="test-session-123",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "sent"
    call_args = server.client.handle_internal_command.call_args
    command = call_args[0][0]
    assert command.text == "/next-work my-feature"


@pytest.mark.asyncio
async def test_run_agent_command_adds_prompts_prefix_for_codex(mock_mcp_server):
    """Test that codex commands are prefixed with /prompts:."""
    server = mock_mcp_server
    server.client.handle_internal_command = AsyncMock(return_value={"status": "success"})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        session_id="test-session-123",
        agent="codex",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "sent"
    call_args = server.client.handle_internal_command.call_args
    command = call_args[0][0]
    assert command.text == "/prompts:next-work"


@pytest.mark.asyncio
async def test_run_agent_command_starts_new_session(mock_mcp_server):
    """Test that run_agent_command starts new session when session_id not provided."""
    server = mock_mcp_server
    server.client.handle_internal_command = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "new-session-789"}}
    )

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        project="/home/user/project",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    assert result["session_id"] == "new-session-789"


@pytest.mark.asyncio
async def test_run_agent_command_requires_project_for_new_session(mock_mcp_server):
    """Test that run_agent_command returns error if project missing for new session."""
    server = mock_mcp_server

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        session_id=None,
        project=None,
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "error"
    assert "project required" in result["message"]


@pytest.mark.asyncio
async def test_run_agent_command_with_subfolder(mock_mcp_server):
    """Test that run_agent_command passes subfolder to new session."""
    server = mock_mcp_server
    server.client.handle_internal_command = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "sess-sub"}}
    )

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        project="/home/user/project",
        subfolder="worktrees/feat",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    # Metadata check
    call_args = server.client.handle_internal_command.call_args_list[0]
    cmd = call_args[0][0]
    assert cmd.subdir == "worktrees/feat"


@pytest.mark.asyncio
async def test_run_agent_command_with_agent_type(mock_mcp_server):
    """Test that run_agent_command uses specified agent."""
    server = mock_mcp_server
    server.client.handle_internal_command = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "sess-agent"}}
    )

    await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        project="/home/user/project",
        agent="gemini",
        caller_session_id=CALLER_SESSION_ID,
    )

    # Check auto_command in metadata
    call_args = server.client.handle_internal_command.call_args
    metadata = call_args[1].get("metadata")
    assert metadata is not None
    assert "gemini" in metadata.auto_command


@pytest.mark.asyncio
async def test_mark_phase_schema_allows_pending(mock_mcp_server):
    """Test that mark_phase accepts 'pending' status."""
    server = mock_mcp_server

    with (
        patch("teleclaude.mcp.handlers.mark_phase") as mock_mark,
        patch("teleclaude.mcp.handlers.Path.exists", return_value=True),
        patch("teleclaude.mcp.handlers.has_uncommitted_changes", return_value=False),
    ):
        mock_mark.return_value = "pending"

        result = await server.teleclaude__mark_phase(
            slug="test-slug",
            phase="build",
            status="pending",
            cwd="/home/user/project",
        )

        assert "state updated" in result
        mock_mark.assert_called_once()


@pytest.mark.asyncio
async def test_mark_phase_blocks_on_uncommitted_changes(mock_mcp_server):
    """Test that mark_phase returns error if there are uncommitted changes."""
    server = mock_mcp_server

    with (
        patch("teleclaude.mcp.handlers.has_uncommitted_changes", return_value=True),
        patch("teleclaude.mcp.handlers.Path.exists", return_value=True),
    ):
        result = await server.teleclaude__mark_phase(
            slug="test-slug",
            phase="build",
            status="complete",
            cwd="/home/user/project",
        )

        assert "UNCOMMITTED_CHANGES" in result
