"""Integration tests for MCP tools."""

import pytest
from unittest.mock import AsyncMock, Mock, patch

from teleclaude.mcp_server import TeleClaudeMCPServer


@pytest.fixture
async def mcp_server(daemon_with_mocked_telegram):
    """Create MCP server with mocked dependencies."""
    daemon = daemon_with_mocked_telegram

    # Import terminal_bridge module
    from teleclaude.core import terminal_bridge

    # Create MCP server using daemon's adapter_client
    server = TeleClaudeMCPServer(
        adapter_client=daemon.client,
        terminal_bridge=terminal_bridge
    )

    return server


@pytest.mark.integration
async def test_teleclaude_list_computers(mcp_server):
    """Test teleclaude__list_computers returns discovered peers."""
    # Mock discover_peers to return test data
    with patch.object(mcp_server.client, 'discover_peers', new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [
            {"name": "testcomp", "status": "online", "bot_username": "@teleclaude_testcomp_bot"},
            {"name": "workstation", "status": "online", "bot_username": "@teleclaude_workstation_bot"}
        ]

        result = await mcp_server.teleclaude__list_computers()

        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["name"] == "testcomp"
        assert result[1]["name"] == "workstation"


@pytest.mark.integration
async def test_teleclaude_list_sessions(mcp_server, daemon_with_mocked_telegram):
    """Test teleclaude__list_sessions returns AI-to-AI sessions."""
    daemon = daemon_with_mocked_telegram

    # Create AI-to-AI sessions (with target_computer in metadata)
    await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-1",
        origin_adapter="redis",
        title="$testcomp > $workstation",
        adapter_metadata={"target_computer": {"name": "workstation"}}
    )

    await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-2",
        origin_adapter="redis",
        title="$testcomp > $server",
        adapter_metadata={"target_computer": {"name": "server"}}
    )

    # List all AI-to-AI sessions
    result = await mcp_server.teleclaude__list_sessions()
    assert len(result) >= 2

    # Verify session structure
    for session in result:
        assert "session_id" in session
        assert "target" in session
        assert "title" in session


@pytest.mark.integration
async def test_teleclaude_start_session(mcp_server, daemon_with_mocked_telegram):
    """Test teleclaude__start_session creates session."""
    daemon = daemon_with_mocked_telegram

    # Mock discover_peers to show computer online
    with patch.object(mcp_server.client, 'discover_peers', new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [
            {"name": "workstation", "status": "online", "bot_username": "@teleclaude_workstation_bot"}
        ]

        # Mock create_channel to avoid Redis initialization
        with patch.object(mcp_server.client, 'create_channel', new_callable=AsyncMock) as mock_create_channel:
            mock_create_channel.return_value = None

            # Mock send_remote_command to avoid actual Redis call
            with patch.object(mcp_server.client, 'send_remote_command', new_callable=AsyncMock) as mock_send:
                mock_send.return_value = None

                result = await mcp_server.teleclaude__start_session(
                    computer="workstation",
                    project_dir="/home/user/project"
                )

                # Verify result
                assert isinstance(result, dict)
                assert result["status"] == "success"
                assert "session_id" in result

                # Verify session created in database
                session = await daemon.db.get_session(result["session_id"])
                assert session is not None
                assert session.origin_adapter == "redis"
                assert "workstation" in session.title

                # Verify mocks were called
                mock_discover.assert_called_once()
                mock_create_channel.assert_called_once()
                assert mock_send.call_count == 2  # cd + claude commands


@pytest.mark.integration
async def test_teleclaude_send_message(mcp_server, daemon_with_mocked_telegram):
    """Test teleclaude__send_message sends to existing session."""
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-send",
        origin_adapter="redis",
        title="Test Send",
        adapter_metadata={
            "target_computer": {"name": "workstation"},
            "claude_session_id": "test-claude-123"
        }
    )

    # Mock send_remote_command
    with patch.object(mcp_server.client, 'send_remote_command', new_callable=AsyncMock) as mock_send:
        mock_send.return_value = "sent"

        # Mock poll_remote_output
        async def mock_poll():
            yield "Output line 1\n"
            yield "Output line 2\n"

        with patch.object(mcp_server.client, 'poll_remote_output', return_value=mock_poll()):
            chunks = []
            async for chunk in mcp_server.teleclaude__send_message(
                session_id=session.session_id,
                message="ls -la"
            ):
                chunks.append(chunk)

            output = "".join(chunks)
            assert "Output line 1" in output
            assert "Output line 2" in output
