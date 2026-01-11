"""Unit tests for MCP server tools."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from mcp import types
from mcp.server import Server

from teleclaude.core.models import ThinkingMode

CALLER_SESSION_ID = "caller-session-123"


@pytest.fixture
def mock_mcp_server():
    """Create MCP server with mocked dependencies."""
    from teleclaude.mcp_server import TeleClaudeMCPServer

    mock_client = MagicMock()
    mock_client.discover_peers = AsyncMock(return_value=[])
    mock_client.handle_event = AsyncMock(return_value={"status": "success", "data": {}})

    mock_terminal_bridge = MagicMock()

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

        server = TeleClaudeMCPServer(adapter_client=mock_client, terminal_bridge=mock_terminal_bridge)

        yield server


@pytest.mark.asyncio
async def test_teleclaude_list_computers_returns_online_computers(mock_mcp_server):
    """Test that list_computers returns online computers from heartbeat."""
    server = mock_mcp_server

    # Mock handle_get_computer_info for local computer
    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.handle_get_computer_info = AsyncMock(
            return_value={
                "user": "testuser",
                "host": "localhost",
                "role": "development",
                "system_stats": {"memory": {"percent_used": 50.0}},
            }
        )

        # Mock discover_peers to return remote peers
        server.client.discover_peers = AsyncMock(
            return_value=[{"name": "RemotePC", "status": "online", "user": "remoteuser", "host": "remote.local"}]
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
        mock_handlers.handle_list_sessions = AsyncMock(
            return_value=[
                {
                    "session_id": "test-session-123",
                    "origin_adapter": "telegram",
                    "title": "Test Session",
                    "status": "active",
                }
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
    from teleclaude.core.events import TeleClaudeEvents

    server = mock_mcp_server

    # Mock handle_event to return success with session_id
    server.client.handle_event = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "new-session-456"}}
    )

    with patch("teleclaude.mcp.handlers.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        result = await server.teleclaude__start_session(
            computer="local",
            project_dir="/home/user/project",
            title="Test Session",
            message="Hello Claude",
            caller_session_id=CALLER_SESSION_ID,
        )

        assert result["status"] == "success"
    assert result["session_id"] == "new-session-456"

    # Verify handle_event was called for NEW_SESSION (AGENT_START may run in background)
    assert server.client.handle_event.call_count >= 1
    assert server.client.handle_event.call_args_list[0].args[0] == TeleClaudeEvents.NEW_SESSION
    if server.client.handle_event.call_count > 1:
        assert server.client.handle_event.call_args_list[1].args[0] == TeleClaudeEvents.AGENT_START


@pytest.mark.asyncio
async def test_teleclaude_send_message_forwards_to_handler(mock_mcp_server):
    """Test that send_message forwards to command handler."""
    server = mock_mcp_server

    server.client.handle_event = AsyncMock(return_value=None)

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

    # Verify handle_event was called
    server.client.handle_event.assert_called_once()


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
            server.client.send_file.assert_called_once()
    finally:
        Path(test_file).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_teleclaude_get_session_data_formats_transcript(mock_mcp_server):
    """Test that get_session_data returns formatted transcript."""
    server = mock_mcp_server

    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.handle_get_session_data = AsyncMock(
            return_value={
                "status": "success",
                "session_id": "test-session-123",
                "messages": "Hello",
            }
        )

        result = await server.teleclaude__get_session_data(
            computer="local",
            session_id="test-session-123",
            caller_session_id=CALLER_SESSION_ID,
        )

        assert result["status"] == "success"
        assert result["session_id"] == "test-session-123"
        assert result["messages"] == "Hello"


@pytest.mark.asyncio
async def test_teleclaude_get_session_data_caps_large_transcripts(mock_mcp_server):
    """Test that get_session_data caps oversized transcripts."""
    server = mock_mcp_server
    from teleclaude.mcp_server import MCP_SESSION_DATA_MAX_CHARS

    oversized = "x" * (MCP_SESSION_DATA_MAX_CHARS + 100)

    with patch("teleclaude.mcp.handlers.command_handlers") as mock_handlers:
        mock_handlers.handle_get_session_data = AsyncMock(
            return_value={
                "status": "success",
                "session_id": "test-session-123",
                "messages": oversized,
            }
        )

        result = await server.teleclaude__get_session_data(
            computer="local",
            session_id="test-session-123",
            tail_chars=0,
            caller_session_id=CALLER_SESSION_ID,
        )

        assert result["status"] == "success"
        assert result["truncated"] is True
        assert result["max_chars"] == MCP_SESSION_DATA_MAX_CHARS
        assert result["requested_tail_chars"] == 0
        assert result["effective_tail_chars"] == MCP_SESSION_DATA_MAX_CHARS
        assert len(result["messages"]) <= MCP_SESSION_DATA_MAX_CHARS


@pytest.mark.asyncio
async def test_teleclaude_send_file_validates_file_path(mock_mcp_server):
    """Test that send_file validates file exists."""
    server = mock_mcp_server

    result = await server.teleclaude__send_file(
        session_id="test-session-123",
        file_path="/nonexistent/file.txt",
    )

    assert "Error:" in result
    assert "File not found" in result


@pytest.mark.asyncio
async def test_mcp_tools_handle_invalid_session_id(mock_mcp_server):
    """Test that MCP tools handle invalid session_id gracefully."""
    server = mock_mcp_server

    # Test send_file with invalid session
    with patch("teleclaude.mcp.handlers.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        # Create temp file for the test
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("Test")
            test_file = f.name

        try:
            result = await server.teleclaude__send_file(
                session_id="nonexistent-session",
                file_path=test_file,
            )

            assert "Error:" in result
            assert "not found" in result
        finally:
            Path(test_file).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_teleclaude_start_session_with_agent_parameter(mock_mcp_server):
    """Test that start_session dispatches correct agent event based on parameter."""
    from teleclaude.core.events import TeleClaudeEvents

    server = mock_mcp_server

    # Mock handle_event to return success with session_id
    server.client.handle_event = AsyncMock(return_value={"status": "success", "data": {"session_id": "agent-test-123"}})

    with patch("teleclaude.mcp.handlers.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        # Test 1: Gemini agent
        result = await server.teleclaude__start_session(
            computer="local",
            project_dir="/home/user/project",
            title="Gemini Session",
            message="Hello Gemini",
            agent="gemini",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"

        # Verify events
    assert server.client.handle_event.call_count >= 1
    assert server.client.handle_event.call_args_list[0].args[0] == TeleClaudeEvents.NEW_SESSION
    if server.client.handle_event.call_count > 1:
        assert server.client.handle_event.call_args_list[1].args[0] == TeleClaudeEvents.AGENT_START

        # Check session creation call
        first_call = server.client.handle_event.call_args_list[0]
        assert first_call[0][0] == "new_session"

        # Check command call - should be "agent" event with "gemini" in args
        second_call = server.client.handle_event.call_args_list[1]
        assert second_call[0][0] == "agent"  # TeleClaudeEvents.AGENT_START
        call_payload = second_call[0][1]
        assert call_payload["args"][0] == "gemini"
        assert call_payload["args"][1] == "slow"

        # Reset mock
        server.client.handle_event.reset_mock()
        server.client.handle_event.return_value = {"status": "success", "data": {"session_id": "agent-test-456"}}

        # Test 2: Codex agent
        result = await server.teleclaude__start_session(
            computer="local",
            project_dir="/home/user/project",
            title="Codex Session",
            message="Hello Codex",
            agent="codex",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"

        # Check command call - should be "agent" event with "codex"
        second_call = server.client.handle_event.call_args_list[1]
        assert second_call[0][0] == "agent"
        call_payload = second_call[0][1]
        assert call_payload["args"][0] == "codex"
        assert call_payload["args"][1] == "slow"

        # Reset mock
        server.client.handle_event.reset_mock()
        server.client.handle_event.return_value = {"status": "success", "data": {"session_id": "agent-test-789"}}

        # Test 3: Claude agent (default)
        result = await server.teleclaude__start_session(
            computer="local",
            project_dir="/home/user/project",
            title="Claude Session",
            message="Hello Claude",
            agent="claude",
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"

        # Check command call - should be "agent" event with "claude"
        second_call = server.client.handle_event.call_args_list[1]
        assert second_call[0][0] == "agent"
        call_payload = second_call[0][1]
        assert call_payload["args"][0] == "claude"
        assert call_payload["args"][1] == "slow"

        # Reset mock and test explicit fast mode
        server.client.handle_event.reset_mock()
        server.client.handle_event.return_value = {"status": "success", "data": {"session_id": "agent-test-fast"}}

        result = await server.teleclaude__start_session(
            computer="local",
            project_dir="/home/user/project",
            title="Fast Claude Session",
            message="Hello Claude",
            agent="claude",
            thinking_mode=ThinkingMode.FAST,
            caller_session_id=CALLER_SESSION_ID,
        )
        assert result["status"] == "success"
        second_call = server.client.handle_event.call_args_list[1]
        call_payload = second_call[0][1]
        assert call_payload["args"][1] == "fast"


@pytest.mark.asyncio
async def test_run_agent_command_passes_mode_for_new_session(monkeypatch, mock_mcp_server):
    server = mock_mcp_server
    server.client.handle_event = AsyncMock(return_value={"status": "success", "data": {"session_id": "sess-123"}})

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
    server.client.handle_event.assert_awaited_once()
    call_args = server.client.handle_event.call_args
    metadata = call_args[0][2]
    assert "codex" in metadata.auto_command
    assert "med" in metadata.auto_command


@pytest.mark.asyncio
async def test_run_agent_command_ignores_mode_when_session_provided(mock_mcp_server):
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
    server.client.handle_event = AsyncMock(return_value=None)

    # Call with leading slash - should be normalized
    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="/compact",
        session_id="test-session-123",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "sent"
    # Verify the message sent was /compact (single slash)
    call_args = server.client.handle_event.call_args
    event_data = call_args[0][1]
    assert event_data["text"] == "/compact"


@pytest.mark.asyncio
async def test_run_agent_command_without_leading_slash(mock_mcp_server):
    """Test that run_agent_command adds / to command without leading slash."""
    server = mock_mcp_server
    server.client.handle_event = AsyncMock(return_value=None)

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="compact",
        session_id="test-session-123",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "sent"
    call_args = server.client.handle_event.call_args
    event_data = call_args[0][1]
    assert event_data["text"] == "/compact"


@pytest.mark.asyncio
async def test_run_agent_command_with_args(mock_mcp_server):
    """Test that run_agent_command appends args to command."""
    server = mock_mcp_server
    server.client.handle_event = AsyncMock(return_value=None)

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        args="my-feature",
        session_id="test-session-123",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "sent"
    call_args = server.client.handle_event.call_args
    event_data = call_args[0][1]
    assert event_data["text"] == "/next-work my-feature"


@pytest.mark.asyncio
async def test_run_agent_command_starts_new_session(mock_mcp_server):
    """Test that run_agent_command starts new session when session_id not provided."""
    server = mock_mcp_server
    server.client.handle_event = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "new-session-789"}}
    )

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        args="feature-x",
        project="/home/user/myproject",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"
    assert result["session_id"] == "new-session-789"

    # Verify handle_event was called once for new_session with auto_command
    assert server.client.handle_event.call_count == 1
    call_args = server.client.handle_event.call_args
    metadata = call_args[0][2]
    assert metadata.auto_command


@pytest.mark.asyncio
async def test_run_agent_command_requires_project_for_new_session(mock_mcp_server):
    """Test that run_agent_command returns error when project missing for new session."""
    server = mock_mcp_server

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        # No session_id and no project
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "error"
    assert "project required" in result["message"]


@pytest.mark.asyncio
async def test_run_agent_command_with_subfolder(mock_mcp_server):
    """Test that run_agent_command passes raw project and subfolder separately."""
    server = mock_mcp_server
    server.client.handle_event = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "worktree-session"}}
    )

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="next-work",
        project="/home/user/myproject",
        subfolder="worktrees/my-feature",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"

    # Verify raw inputs are passed separately (not concatenated)
    # handle_create_session derives working_dir from these
    first_call = server.client.handle_event.call_args_list[0]
    metadata = first_call[0][2]  # Third arg is MessageMetadata
    assert metadata.project_dir == "/home/user/myproject"
    assert metadata.channel_metadata["subfolder"] == "worktrees/my-feature"


@pytest.mark.asyncio
async def test_run_agent_command_with_agent_type(mock_mcp_server):
    """Test that run_agent_command passes agent type for new sessions."""
    server = mock_mcp_server
    server.client.handle_event = AsyncMock(return_value={"status": "success", "data": {"session_id": "gemini-session"}})

    result = await server.teleclaude__run_agent_command(
        computer="local",
        command="help",
        project="/home/user/myproject",
        agent="gemini",
        caller_session_id=CALLER_SESSION_ID,
    )

    assert result["status"] == "success"

    # Verify auto_command includes agent type
    call_args = server.client.handle_event.call_args
    metadata = call_args[0][2]
    assert "gemini" in metadata.auto_command


@pytest.mark.asyncio
async def test_mark_phase_schema_allows_pending(mock_mcp_server):
    """mark_phase tool schema includes pending status."""
    server = mock_mcp_server
    mcp_server = Server("teleclaude")
    server._setup_tools(mcp_server)

    handler = mcp_server.request_handlers[types.ListToolsRequest]
    result = await handler(types.ListToolsRequest())

    tools = result.root.tools
    mark_phase_tool = next(tool for tool in tools if tool.name == "teleclaude__mark_phase")
    status_enum = mark_phase_tool.inputSchema["properties"]["status"]["enum"]

    assert "pending" in status_enum


@pytest.mark.asyncio
async def test_mark_phase_blocks_on_uncommitted_changes(mock_mcp_server, tmp_path):
    """mark_phase refuses to update state when worktree is dirty."""
    server = mock_mcp_server
    slug = "dirty-slug"

    worktree_path = tmp_path / "trees" / slug
    worktree_path.mkdir(parents=True, exist_ok=True)

    with patch("teleclaude.mcp.handlers.has_uncommitted_changes", return_value=True):
        result = await server.teleclaude__mark_phase(
            slug=slug,
            phase="build",
            status="complete",
            cwd=str(tmp_path),
        )

    assert "ERROR: UNCOMMITTED_CHANGES" in result
