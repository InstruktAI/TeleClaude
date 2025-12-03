"""Unit tests for MCP server tools."""

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture
def mock_mcp_server():
    """Create MCP server with mocked dependencies."""
    from teleclaude.mcp_server import TeleClaudeMCPServer

    mock_client = MagicMock()
    mock_client.discover_peers = AsyncMock(return_value=[])
    mock_client.handle_event = AsyncMock(return_value={"status": "success", "data": {}})

    mock_terminal_bridge = MagicMock()

    with patch("teleclaude.mcp_server.config") as mock_config:
        mock_config.computer.name = "TestComputer"
        mock_config.mcp.socket_path = "/tmp/test.sock"
        server = TeleClaudeMCPServer(adapter_client=mock_client, terminal_bridge=mock_terminal_bridge)

    return server


@pytest.mark.asyncio
async def test_teleclaude_list_computers_returns_online_computers(mock_mcp_server):
    """Test that list_computers returns online computers from heartbeat."""
    server = mock_mcp_server

    # Mock handle_get_computer_info for local computer
    with patch("teleclaude.mcp_server.command_handlers") as mock_handlers:
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

    with patch("teleclaude.mcp_server.command_handlers") as mock_handlers:
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
    server = mock_mcp_server

    # Mock handle_event to return success with session_id
    server.client.handle_event = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "new-session-456"}}
    )

    result = await server.teleclaude__start_session(
        computer="local",
        project_dir="/home/user/project",
        title="Test Session",
        message="Hello Claude",
    )

    assert result["status"] == "success"
    assert result["session_id"] == "new-session-456"

    # Verify handle_event was called for both NEW_SESSION and CLAUDE
    assert server.client.handle_event.call_count == 2


@pytest.mark.asyncio
async def test_teleclaude_send_message_forwards_to_handler(mock_mcp_server):
    """Test that send_message forwards to command handler."""
    server = mock_mcp_server

    server.client.handle_event = AsyncMock(return_value=None)

    chunks = []
    async for chunk in server.teleclaude__send_message(
        computer="local", session_id="test-session-123", message="ls -la"
    ):
        chunks.append(chunk)

    result = "".join(chunks)
    assert "Message sent" in result
    assert "test-ses" in result  # First 8 chars of session_id

    # Verify handle_event was called
    server.client.handle_event.assert_called_once()


@pytest.mark.asyncio
async def test_teleclaude_send_message_adds_ai_prefix(mock_mcp_server):
    """Test that send_message adds AI-to-AI protocol prefix with sender info."""
    server = mock_mcp_server

    server.client.handle_event = AsyncMock(return_value=None)

    # Set caller's session_id in environment
    with patch.dict("os.environ", {"TELECLAUDE_SESSION_ID": "caller-session-abc"}):
        chunks = []
        async for chunk in server.teleclaude__send_message(
            computer="local", session_id="target-session-123", message="run tests"
        ):
            chunks.append(chunk)

    # Verify handle_event was called with prefixed message
    server.client.handle_event.assert_called_once()
    call_args = server.client.handle_event.call_args

    # Extract the event_data from the call
    event_data = call_args[0][1]  # Second positional arg is event_data
    message_text = event_data["text"]

    # Verify AI prefix format: AI[local:session_id] | message
    # Uses "local" for local targets (not computer name) for clarity
    assert message_text.startswith("AI[local:caller-session-abc]")
    assert " | " in message_text
    assert "run tests" in message_text


@pytest.mark.asyncio
async def test_teleclaude_handle_claude_event_sends_to_session(mock_mcp_server):
    """Test that handle_claude_event sends event to session."""
    server = mock_mcp_server

    # Mock db.get_session to return valid session
    mock_session = MagicMock()
    mock_session.session_id = "test-session-123"

    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=mock_session)
        server.client.handle_event = AsyncMock(return_value=None)

        result = await server.teleclaude__handle_claude_event(
            session_id="test-session-123",
            event_type="notification",
            data={"message": "Test notification"},
        )

        assert result == "OK"
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

        with patch("teleclaude.mcp_server.db") as mock_db:
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

    with patch("teleclaude.mcp_server.command_handlers") as mock_handlers:
        mock_handlers.handle_get_session_data = AsyncMock(
            return_value={
                "status": "success",
                "session_id": "test-session-123",
                "messages": [{"type": "user", "text": "Hello"}],
            }
        )

        result = await server.teleclaude__get_session_data(
            computer="local",
            session_id="test-session-123",
        )

        assert result["status"] == "success"
        assert result["session_id"] == "test-session-123"
        assert len(result["messages"]) == 1


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
    with patch("teleclaude.mcp_server.db") as mock_db:
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

    # Test handle_claude_event with invalid session
    with patch("teleclaude.mcp_server.db") as mock_db:
        mock_db.get_session = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="not found"):
            await server.teleclaude__handle_claude_event(
                session_id="nonexistent-session",
                event_type="notification",
                data={},
            )


@pytest.mark.asyncio
async def test_teleclaude_start_session_with_model_parameter(mock_mcp_server):
    """Test that start_session accepts and passes model parameter through metadata."""
    server = mock_mcp_server

    # Mock handle_event to return success with session_id
    server.client.handle_event = AsyncMock(
        return_value={"status": "success", "data": {"session_id": "model-test-789"}}
    )

    result = await server.teleclaude__start_session(
        computer="local",
        project_dir="/home/user/project",
        title="Sonnet Session",
        message="Test with sonnet",
        model="sonnet",
    )

    assert result["status"] == "success"
    assert result["session_id"] == "model-test-789"

    # Verify handle_event was called with MessageMetadata containing claude_model
    assert server.client.handle_event.call_count == 2  # NEW_SESSION + CLAUDE

    # Check first call (NEW_SESSION) has metadata with claude_model
    first_call = server.client.handle_event.call_args_list[0]
    metadata = first_call[0][2]  # Third positional arg is MessageMetadata
    assert metadata.claude_model == "sonnet"
