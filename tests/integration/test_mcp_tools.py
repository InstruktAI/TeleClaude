"""Paranoid integration tests for MCP tools."""

import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core import tmux_bridge
from teleclaude.mcp_server import TeleClaudeMCPServer

FIXED_NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


@pytest.fixture
async def mcp_server(daemon_with_mocked_telegram):
    """Create MCP server with mocked dependencies."""
    daemon = daemon_with_mocked_telegram

    # Create MCP server using daemon's adapter_client
    server = TeleClaudeMCPServer(adapter_client=daemon.client, tmux_bridge=tmux_bridge)

    return server


@pytest.mark.integration
async def test_teleclaude_list_computers(mcp_server):
    """Paranoid test teleclaude__list_computers returns local computer + discovered peers."""
    # Mock discover_peers to return test data (remote peers)
    with patch.object(mcp_server.client, "discover_peers", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [
            {
                "name": "testcomp",
                "status": "online",
                "last_seen": FIXED_NOW,
                "bot_username": "@teleclaude_testcomp_bot",
            },
            {
                "name": "workstation",
                "status": "online",
                "last_seen": FIXED_NOW,
                "bot_username": "@teleclaude_workstation_bot",
            },
        ]

        result = await mcp_server.teleclaude__list_computers()

        assert isinstance(result, list)
        # Expect 3: local computer + 2 remote peers
        assert len(result) == 3

        # First is local computer (from config mock: "TestComputer")
        assert result[0]["name"] == "TestComputer"
        assert result[0]["status"] == "local"

        # Remote peers follow
        assert result[1]["name"] == "testcomp"
        assert result[2]["name"] == "workstation"


@pytest.mark.integration
async def test_teleclaude_list_sessions(mcp_server, daemon_with_mocked_telegram):
    """Paranoid test teleclaude__list_sessions returns AI-to-AI sessions."""
    daemon = daemon_with_mocked_telegram

    # Create AI-to-AI sessions (with target_computer in metadata)
    await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-1",
        last_input_origin=InputOrigin.API.value,
        title="$testcomp > $workstation",
        adapter_metadata={"target_computer": {"name": "workstation"}},
    )

    await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-2",
        last_input_origin=InputOrigin.API.value,
        title="$testcomp > $server",
        adapter_metadata={"target_computer": {"name": "server"}},
    )

    # List all AI-to-AI sessions
    result = await mcp_server.teleclaude__list_sessions()
    assert len(result) >= 2

    # Verify session structure (fields returned by list_sessions)
    for session in result:
        assert "session_id" in session
        assert "last_input_origin" in session
        assert "title" in session


@pytest.mark.integration
async def test_teleclaude_start_session(mcp_server, daemon_with_mocked_telegram):
    """Paranoid test teleclaude__start_session creates session on remote (no local session)."""
    daemon = daemon_with_mocked_telegram

    # Mock discover_peers to show computer online
    with patch.object(mcp_server.client, "discover_peers", new_callable=AsyncMock) as mock_discover:
        mock_discover.return_value = [
            {"name": "workstation", "status": "online", "bot_username": "@teleclaude_workstation_bot"}
        ]

        # Mock send_request to avoid actual Redis call
        sent_commands: list[str] = []

        async def record_send_request(*, command: str, **_kwargs: object) -> None:
            sent_commands.append(command)
            return None

        with patch.object(mcp_server.client, "send_request", new=record_send_request):
            # Mock read_response to return envelope with remote session_id
            with patch.object(mcp_server.client, "read_response", new_callable=AsyncMock) as mock_read:
                mock_read.return_value = '{"status": "success", "data": {"session_id": "remote-uuid-123"}}'

                result = await mcp_server.teleclaude__start_session(
                    computer="workstation",
                    project_path="/home/user/project",
                    title="TEST: start session",
                    message="ls -la",
                    caller_session_id="caller-session-123",
                )

                # Verify result (ONLY remote session ID returned, no local session)
                assert isinstance(result, dict)
                assert result["status"] == "success"
                assert result["session_id"] == "remote-uuid-123"

                # Verify NO local session created
                session = await daemon.db.get_session(result["session_id"])
                assert session is None

                assert mock_discover.called

                assert "/new_session" in sent_commands
                assert any(cmd.startswith("/agent claude slow '") for cmd in sent_commands)
                assert any(cmd.endswith("ls -la'") for cmd in sent_commands)

                assert mock_read.called  # Wait for response


@pytest.mark.integration
async def test_teleclaude_send_message(mcp_server, daemon_with_mocked_telegram):
    """Paranoid test teleclaude__send_message sends via request/response (no streaming)."""
    daemon = daemon_with_mocked_telegram

    # Remote session ID (no local session needed)
    remote_session_id = "remote-uuid-123"
    target_computer = "RasPi"
    await daemon.db.create_session(
        computer_name="TestPC",
        tmux_session_name="tmux-caller",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Caller Session",
        session_id="caller-session-123",
    )

    # Mock send_request (new architecture uses request/response)
    sent: list[tuple[str, str]] = []

    async def record_send_request(*, command: str, session_id: str, **_kwargs: object) -> None:
        sent.append((session_id, command))
        return None

    with patch.object(mcp_server.client, "send_request", new=record_send_request):
        chunks = []
        async for chunk in mcp_server.teleclaude__send_message(
            computer=target_computer,
            session_id=remote_session_id,
            message="ls -la",
            caller_session_id="caller-session-123",
        ):
            chunks.append(chunk)

        output = "".join(chunks)
        # New architecture returns acknowledgment, not output
        assert "Message sent" in output
        assert remote_session_id[:8] in output
        assert "teleclaude__get_session_data" in output

        # Verify send_request was called
        assert sent


@pytest.mark.integration
async def test_teleclaude_send_file(mcp_server, daemon_with_mocked_telegram):
    """Paranoid test teleclaude__send_file sends file via AdapterClient to origin adapter."""
    daemon = daemon_with_mocked_telegram

    # Create session with telegram origin
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-file-upload",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test File Upload",
        adapter_metadata={"channel_id": "12345"},
    )

    # Create temporary test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("Test file content for MCP upload")
        test_file_path = tmp.name

    try:
        # Wrap adapter.send_file to record arguments during the call under test
        telegram_adapter = daemon.client.adapters.get("telegram")
        sent_files = []
        original_send_file = telegram_adapter.send_file

        async def record_send_file(*args, **kwargs):
            sent_files.append((args, kwargs))
            return await original_send_file(*args, **kwargs)

        telegram_adapter.send_file = record_send_file

        # Call MCP tool with explicit session_id
        result = await mcp_server.teleclaude__send_file(
            session_id=session.session_id, file_path=test_file_path, caption="Test upload from Claude"
        )

        # Verify success message
        assert "File sent successfully" in result
        assert Path(test_file_path).name in result
        assert "file-msg-789" in result

        # Verify adapter.send_file was called via client layer
        assert len(sent_files) == 1
        call_args, call_kwargs = sent_files[0]
        assert call_args[0].session_id == session.session_id  # Session object
        assert call_args[1] == test_file_path
        # caption is now a keyword argument
        assert call_kwargs.get("caption") == "Test upload from Claude"

    finally:
        # Cleanup test file
        Path(test_file_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_teleclaude_send_file_invalid_session(mcp_server):
    """Paranoid test teleclaude__send_file fails gracefully with invalid session_id."""
    # Create temporary test file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as tmp:
        tmp.write("Test content")
        test_file_path = tmp.name

    try:
        result = await mcp_server.teleclaude__send_file(session_id="nonexistent-session-id", file_path=test_file_path)

        # Verify error message (session not found)
        assert "Error:" in result

    finally:
        Path(test_file_path).unlink(missing_ok=True)


@pytest.mark.integration
async def test_teleclaude_send_file_nonexistent_file(mcp_server, daemon_with_mocked_telegram):
    """Paranoid test teleclaude__send_file fails gracefully for missing files."""
    daemon = daemon_with_mocked_telegram

    # Create session
    session = await daemon.db.create_session(
        computer_name="testcomp",
        tmux_session_name="test-missing-file",
        last_input_origin=InputOrigin.TELEGRAM.value,
        title="Test Missing File",
        adapter_metadata={"channel_id": "12345"},
    )

    # Try to send non-existent file
    result = await mcp_server.teleclaude__send_file(
        session_id=session.session_id, file_path="/tmp/nonexistent-file-12345.txt"
    )

    # Verify error message
    assert "Error:" in result
    assert "File not found" in result
