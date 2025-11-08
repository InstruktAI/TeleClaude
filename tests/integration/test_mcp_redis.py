"""Functional tests for Redis-based MCP server.

Tests the actual MCP server implementation using RedisAdapter for AI-to-AI communication.
"""

import asyncio
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core.db import db, Db
from teleclaude.mcp_server import TeleClaudeMCPServer


@pytest.fixture
async def session_manager(tmp_path):
    """Create real session manager with temp database."""
    db_path = tmp_path / "test.db"
    manager = Db(str(db_path))
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
def mock_redis_adapter():
    """Create mock Redis adapter."""
    adapter = Mock()

    # Mock discover_peers (for list_computers)
    adapter.discover_peers = AsyncMock(return_value=[
        {
            "name": "computer1",
            "bot_username": "@teleclaude_computer1_bot",
            "status": "online",
            "last_seen_ago": "5s ago",
            "adapter_type": "redis"
        },
        {
            "name": "computer2",
            "bot_username": "@teleclaude_computer2_bot",
            "status": "online",
            "last_seen_ago": "10s ago",
            "adapter_type": "redis"
        }
    ])

    # Mock send_command_to_computer
    adapter.send_command_to_computer = AsyncMock(return_value="msg_123")

    # Mock poll_output_stream (for streaming responses)
    async def mock_poll_output(session_id, timeout=300.0):
        # Simulate streaming output
        yield "Output line 1\n"
        yield "Output line 2\n"
        yield "[Complete]\n"

    adapter.poll_output_stream = mock_poll_output

    return adapter


@pytest.fixture
def mock_adapter_client(mock_redis_adapter):
    """Create mock adapter client."""
    client = Mock()
    client.discover_peers = mock_redis_adapter.discover_peers
    client.send_remote_command = mock_redis_adapter.send_command_to_computer
    client.poll_remote_output = mock_redis_adapter.poll_output_stream
    client.discover_remote_computers = AsyncMock(return_value=["computer1", "computer2"])
    return client


@pytest.fixture
def mock_terminal_bridge():
    """Create mock terminal bridge."""
    bridge = Mock()
    bridge.send_keys = AsyncMock()
    return bridge


@pytest.fixture
def mcp_server(mock_terminal_bridge, session_manager, mock_adapter_client):
    """Create MCP server with mocked dependencies."""
    return TeleClaudeMCPServer(
        adapter_client=mock_adapter_client,
        terminal_bridge=mock_terminal_bridge,
        session_manager=session_manager,
    )


@pytest.mark.asyncio
async def test_teleclaude_list_computers(mcp_server):
    """Test listing computers via Redis adapter."""
    # Execute
    computers = await mcp_server.teleclaude__list_computers()

    # Verify
    assert len(computers) == 2
    assert computers[0]["name"] == "computer1"
    assert computers[0]["status"] == "online"
    assert computers[1]["name"] == "computer2"
    assert computers[1]["adapter_type"] == "redis"


@pytest.mark.asyncio
async def test_teleclaude_list_projects(mcp_server, mock_adapter_client):
    """Test listing projects on remote computer."""
    # Mock poll_remote_output to return project list
    async def mock_poll_projects(session_id, timeout=10.0):
        yield '["/home/user/project1", "/home/user/project2"]'

    mock_adapter_client.poll_remote_output = mock_poll_projects

    # Execute
    projects = await mcp_server.teleclaude__list_projects("computer1")

    # Verify
    assert isinstance(projects, list)
    assert len(projects) == 2
    mock_adapter_client.send_remote_command.assert_called_once()
    call_args = mock_adapter_client.send_remote_command.call_args
    assert call_args[1]["computer_name"] == "computer1"
    assert call_args[1]["command"] == "list_projects"


@pytest.mark.asyncio
async def test_teleclaude_start_session(mcp_server, session_manager, mock_adapter_client):
    """Test starting AI-to-AI session via transport adapter."""
    # Mock poll_remote_output to return startup messages
    async def mock_poll_startup(session_id, timeout=30.0):
        for i in range(6):  # Return 6 chunks (>5 to trigger break)
            yield f"Startup chunk {i}\n"

    mock_adapter_client.poll_remote_output = mock_poll_startup

    # Execute
    result = await mcp_server.teleclaude__start_session(
        computer="computer1",
        project_dir="/home/user/project1",
        initial_message="Hello"
    )

    # Verify
    assert result["status"] == "success"
    assert "session_id" in result
    assert "output" in result
    assert "Startup chunk" in result["output"]

    # Verify session created with Redis as origin
    session = await db.get_session(result["session_id"])
    assert session is not None
    assert session.origin_adapter == "redis"
    assert session.adapter_metadata["is_ai_to_ai"] is True
    assert session.adapter_metadata["project_dir"] == "/home/user/project1"
    assert session.adapter_metadata["target_computer"] == "computer1"

    # Verify command sent via AdapterClient
    mock_adapter_client.send_remote_command.assert_called_once()
    call_args = mock_adapter_client.send_remote_command.call_args
    assert call_args[1]["computer_name"] == "computer1"
    assert "cd " in call_args[1]["command"]
    assert "claude" in call_args[1]["command"]


@pytest.mark.asyncio
async def test_teleclaude_list_sessions(mcp_server, session_manager):
    """Test listing AI-managed sessions."""
    # Create test sessions
    await db.create_session(
        session_id=str(uuid.uuid4()),
        computer_name="testcomp",
        tmux_session_name="test-tmux-1",
        origin_adapter="redis",
        title="AI:computer1:project1",
        adapter_metadata={
            "is_ai_to_ai": True,
            "is_auto_managed": True,
            "project_dir": "/home/user/project1",
            "target_computer": "computer1"
        }
    )

    await db.create_session(
        session_id=str(uuid.uuid4()),
        computer_name="testcomp",
        tmux_session_name="test-tmux-2",
        origin_adapter="telegram",
        title="Human Session",  # Not AI session
        adapter_metadata={}
    )

    # Execute
    sessions = await mcp_server.teleclaude__list_sessions()

    # Verify - should only return AI sessions
    assert len(sessions) == 1
    assert sessions[0]["target"] == "computer1"
    assert sessions[0]["project_dir"] == "/home/user/project1"
    assert sessions[0]["is_auto_managed"] is True


@pytest.mark.asyncio
async def test_teleclaude_send_message(mcp_server, session_manager, mock_adapter_client):
    """Test sending message to existing AI session."""
    # Create test session
    session_id = str(uuid.uuid4())
    await db.create_session(
        session_id=session_id,
        computer_name="testcomp",
        tmux_session_name="test-tmux",
        origin_adapter="redis",
        title="AI:computer1:project1",
        adapter_metadata={
            "target_computer": "computer1"
        }
    )

    # Mock poll_remote_output
    async def mock_poll_response(sid, timeout=300.0):
        yield "Response line 1\n"
        yield "Response line 2\n"

    mock_adapter_client.poll_remote_output = mock_poll_response

    # Execute - collect all chunks
    chunks = []
    async for chunk in mcp_server.teleclaude__send_message(session_id, "ls -la"):
        chunks.append(chunk)

    # Verify
    assert len(chunks) == 2
    assert "Response line 1" in chunks[0]
    assert "Response line 2" in chunks[1]

    # Verify command sent via AdapterClient
    mock_adapter_client.send_remote_command.assert_called_once()
    call_args = mock_adapter_client.send_remote_command.call_args
    assert call_args[1]["computer_name"] == "computer1"
    assert call_args[1]["session_id"] == session_id
    assert call_args[1]["command"] == "ls -la"


@pytest.mark.asyncio
async def test_teleclaude_send_message_session_not_found(mcp_server):
    """Test error handling when session doesn't exist."""
    # Execute
    chunks = []
    async for chunk in mcp_server.teleclaude__send_message("nonexistent", "test"):
        chunks.append(chunk)

    # Verify
    assert len(chunks) == 1
    assert "Error: Session not found" in chunks[0]


@pytest.mark.asyncio
async def test_teleclaude_send_message_closed_session(mcp_server, session_manager):
    """Test error handling for closed sessions."""
    # Create closed session
    session_id = str(uuid.uuid4())
    session = await db.create_session(
        session_id=session_id,
        computer_name="testcomp",
        tmux_session_name="test-tmux",
        origin_adapter="redis",
        title="Test",
        adapter_metadata={"target_computer": "computer1"}
    )
    await db.update_session(session_id, closed=True)

    # Execute
    chunks = []
    async for chunk in mcp_server.teleclaude__send_message(session_id, "test"):
        chunks.append(chunk)

    # Verify
    assert len(chunks) == 1
    assert "Error: Session is closed" in chunks[0]
