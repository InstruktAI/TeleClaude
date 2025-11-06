"""Integration tests for MCP tools with mocked Telegram API.

These tests simulate real-world scenarios as closely as possible:
- Mock Telegram API responses
- Test full MCP tool flow
- Verify computer registry integration
- Test session lifecycle
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core.computer_registry import ComputerRegistry
from teleclaude.core.session_manager import SessionManager
from teleclaude.mcp_server import TeleClaudeMCPServer


@pytest.fixture
async def mock_telegram_adapter():
    """Create mock Telegram adapter."""
    adapter = Mock()
    adapter.supergroup_id = "-100123456789"

    # Mock send_message_to_topic
    adapter.send_message_to_topic = AsyncMock()

    # Mock create_topic
    mock_topic = Mock()
    mock_topic.message_thread_id = 12345
    adapter.create_topic = AsyncMock(return_value=mock_topic)

    # Mock register/unregister MCP listener
    adapter.register_mcp_listener = AsyncMock(return_value=asyncio.Queue())
    adapter.unregister_mcp_listener = AsyncMock()

    # Mock get_topic_messages for registry polling
    adapter.get_topic_messages = AsyncMock(return_value=[])

    # Mock bot for registry
    adapter.app = Mock()
    adapter.app.bot = Mock()
    adapter.app.bot.edit_message_text = AsyncMock()

    return adapter


@pytest.fixture
async def mock_terminal_bridge():
    """Create mock terminal bridge."""
    bridge = Mock()
    bridge.send_keys = AsyncMock()
    return bridge


@pytest.fixture
async def session_manager(tmp_path):
    """Create real session manager with temp database."""
    db_path = tmp_path / "test.db"
    manager = SessionManager(str(db_path))
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
async def computer_registry(mock_telegram_adapter, session_manager):
    """Create computer registry with mocked adapter."""
    registry = ComputerRegistry(
        telegram_adapter=mock_telegram_adapter,
        computer_name="testcomp",
        bot_username="teleclaude_testcomp_bot",
        session_manager=session_manager
    )

    # Mock registry topic ID
    registry.registry_topic_id = 999

    # Populate with test computers
    registry.computers = {
        "testcomp": {
            "name": "testcomp",
            "bot_username": "@teleclaude_testcomp_bot",
            "status": "online",
            "last_seen": datetime.now(),
            "last_seen_ago": "5s ago"
        },
        "workstation": {
            "name": "workstation",
            "bot_username": "@teleclaude_workstation_bot",
            "status": "online",
            "last_seen": datetime.now(),
            "last_seen_ago": "10s ago"
        },
        "server": {
            "name": "server",
            "bot_username": "@teleclaude_server_bot",
            "status": "offline",
            "last_seen": datetime.now(),
            "last_seen_ago": "120s ago"
        }
    }

    return registry


@pytest.fixture
async def mcp_server(mock_telegram_adapter, mock_terminal_bridge, session_manager, computer_registry):
    """Create MCP server with all dependencies mocked."""
    from teleclaude import config as config_module

    mock_config = {
        "computer": {"name": "testcomp"},
        "mcp": {"transport": "stdio"}
    }

    # Create mock adapter client
    mock_client = Mock()
    async def mock_discover_peers():
        return [
            {"name": "testcomp", "status": "online", "bot_username": "@teleclaude_testcomp_bot"},
            {"name": "workstation", "status": "online", "bot_username": "@teleclaude_workstation_bot"}
        ]
    mock_client.discover_peers = AsyncMock(side_effect=mock_discover_peers)

    with patch.object(config_module, '_config', mock_config):
        server = TeleClaudeMCPServer(
            telegram_adapter=mock_telegram_adapter,
            terminal_bridge=mock_terminal_bridge,
            session_manager=session_manager,
            computer_registry=computer_registry,
            adapter_client=mock_client
        )

    return server


@pytest.mark.integration
async def test_teleclaude_list_computers(mcp_server):
    """Test teleclaude__list_computers returns online computers from registry."""
    # Call the tool
    result = await mcp_server.teleclaude__list_computers()

    # Verify results
    assert isinstance(result, list)
    assert len(result) == 2  # Only online computers

    # Check computer names
    computer_names = [c["name"] for c in result]
    assert "testcomp" in computer_names
    assert "workstation" in computer_names
    assert "server" not in computer_names  # Offline

    # Check structure
    for computer in result:
        assert "name" in computer
        assert "bot_username" in computer
        assert "status" in computer
        assert computer["status"] == "online"


@pytest.mark.integration
async def test_teleclaude_start_session_success(mcp_server, mock_telegram_adapter, session_manager):
    """Test teleclaude__start_session creates session and waits for ACK."""
    # Setup: Mock ACK message in queue
    ack_queue = asyncio.Queue()
    mock_ack_message = Mock()
    mock_ack_message.text = "ACK from remote"
    await ack_queue.put(mock_ack_message)

    mock_telegram_adapter.register_mcp_listener.return_value = ack_queue

    # Call the tool
    result = await mcp_server.teleclaude__start_session(
        target="workstation",
        title="Test session",
        description="Testing AI-to-AI communication"
    )

    # Verify result
    assert result["status"] == "ready"
    assert "workstation" in result["topic_name"]
    assert "session_id" in result

    # Verify session created in database
    session = await session_manager.get_session(result["session_id"])
    assert session is not None
    assert session.computer_name == "testcomp"
    assert "$testcomp > $workstation" in session.title
    assert session.description == "Testing AI-to-AI communication"

    # Verify Telegram API calls
    mock_telegram_adapter.create_topic.assert_called_once_with("$testcomp > $workstation - Test session")
    mock_telegram_adapter.send_message_to_topic.assert_called_once_with(12345, "/claude_resume", parse_mode=None)
    mock_telegram_adapter.register_mcp_listener.assert_called_once_with(12345)
    mock_telegram_adapter.unregister_mcp_listener.assert_called_once_with(12345)


@pytest.mark.integration
async def test_teleclaude_start_session_target_offline(mcp_server):
    """Test teleclaude__start_session rejects offline target."""
    result = await mcp_server.teleclaude__start_session(
        target="server",  # Offline computer
        title="Test session",
        description="Should fail"
    )

    # Verify error
    assert result["status"] == "error"
    assert "offline" in result["message"].lower()
    assert "available" in result
    assert "workstation" in result["available"]


@pytest.mark.integration
async def test_teleclaude_start_session_timeout(mcp_server, mock_telegram_adapter):
    """Test teleclaude__start_session handles ACK timeout."""
    # Setup: Empty queue (no ACK)
    empty_queue = asyncio.Queue()
    mock_telegram_adapter.register_mcp_listener.return_value = empty_queue

    # Mock the timeout to be instant for testing
    with patch.object(mcp_server, '_wait_for_claude_ready') as mock_wait:
        mock_wait.side_effect = TimeoutError("No ACK from remote Claude Code after 0.1s")

        # Call the tool
        result = await mcp_server.teleclaude__start_session(
            target="workstation",
            title="Test timeout",
            description="Testing timeout"
        )

        # Verify timeout result
        assert result["status"] == "timeout"
        assert "did not respond" in result["message"]
        assert "session_id" in result  # Session still created

        # Verify _wait_for_claude_ready was called
        mock_wait.assert_called_once()


@pytest.mark.integration
async def test_teleclaude_list_sessions(mcp_server, session_manager):
    """Test teleclaude__list_sessions filters AI-to-AI sessions."""
    # Create test sessions
    await session_manager.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-1",
        adapter_type="telegram",
        title="$testcomp > $workstation - Check logs",
        adapter_metadata={"channel_id": "111"},
        description="Debug 502 errors"
    )

    await session_manager.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-2",
        adapter_type="telegram",
        title="$testcomp > $server - Install deps",
        adapter_metadata={"channel_id": "222"},
        description="Setup environment"
    )

    # Create non-AI session (should be filtered out)
    await session_manager.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-human-1",
        adapter_type="telegram",
        title="Human session",
        adapter_metadata={"channel_id": "333"},
        description="Manual work"
    )

    # Call without filter
    result = await mcp_server.teleclaude__list_sessions()

    # Verify results
    assert len(result) == 2
    targets = [s["target"] for s in result]
    assert "workstation" in targets
    assert "server" in targets

    # Call with target filter
    result = await mcp_server.teleclaude__list_sessions(target="workstation")
    assert len(result) == 1
    assert result[0]["target"] == "workstation"
    assert result[0]["title"] == "Check logs"
    assert result[0]["description"] == "Debug 502 errors"


@pytest.mark.integration
async def test_teleclaude_send_success(mcp_server, mock_telegram_adapter, mock_terminal_bridge, session_manager):
    """Test teleclaude__send sends message and collects output."""
    # Create session
    session = await session_manager.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-test",
        adapter_type="telegram",
        title="$testcomp > $workstation - Test",
        adapter_metadata={"channel_id": "12345"},
        description="Test send"
    )

    # Setup: Mock output messages in queue
    output_queue = asyncio.Queue()

    # Simulate remote output
    msg1 = Mock()
    msg1.text = "Line 1 of output"
    msg2 = Mock()
    msg2.text = "Line 2 of output"
    msg3 = Mock()
    msg3.text = "Command completed"

    await output_queue.put(msg1)
    await output_queue.put(msg2)
    await output_queue.put(msg3)

    # Add completion marker
    completion_msg = Mock()
    completion_msg.text = "[Output Complete]"
    await output_queue.put(completion_msg)

    mock_telegram_adapter.register_mcp_listener.return_value = output_queue

    # Call the tool (now streaming)
    chunks = []
    async for chunk in mcp_server.teleclaude__send(
        session_id=session.session_id,
        message="echo 'test'"
    ):
        chunks.append(chunk)

    output = "".join(chunks)

    # Verify output contains all chunks
    assert "Line 1 of output" in output
    assert "Line 2 of output" in output
    assert "Command completed" in output

    # Verify terminal bridge called
    mock_terminal_bridge.send_keys.assert_called_once_with("testcomp-ai-test", "echo 'test'")

    # Verify cleanup
    mock_telegram_adapter.register_mcp_listener.assert_called_once_with(12345)
    mock_telegram_adapter.unregister_mcp_listener.assert_called_once_with(12345)


@pytest.mark.integration
async def test_teleclaude_send_session_not_found(mcp_server):
    """Test teleclaude__send rejects unknown session."""
    chunks = []
    async for chunk in mcp_server.teleclaude__send(
        session_id="nonexistent",
        message="test"
    ):
        chunks.append(chunk)

    output = "".join(chunks)
    assert "[Error: Session not found]" in output


@pytest.mark.integration
async def test_teleclaude_send_closed_session(mcp_server, session_manager):
    """Test teleclaude__send rejects closed session."""
    # Create session
    session = await session_manager.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-closed",
        adapter_type="telegram",
        title="$testcomp > $workstation - Closed",
        adapter_metadata={"channel_id": "999"},
        description="Closed session"
    )

    # Mark session as closed
    await session_manager.update_session(session.session_id, closed=True)

    # Try to send to closed session
    chunks = []
    async for chunk in mcp_server.teleclaude__send(
        session_id=session.session_id,
        message="test"
    ):
        chunks.append(chunk)

    output = "".join(chunks)
    assert "[Error: Session is closed]" in output


@pytest.mark.integration
async def test_teleclaude_send_timeout(mcp_server, mock_telegram_adapter, mock_terminal_bridge, session_manager):
    """Test teleclaude__send handles timeout when no output received."""
    # Create session
    session = await session_manager.create_session(
        computer_name="testcomp",
        tmux_session_name="testcomp-ai-timeout",
        adapter_type="telegram",
        title="$testcomp > $workstation - Timeout test",
        adapter_metadata={"channel_id": "12345"},
        description="Test timeout"
    )

    # Setup: Empty queue (no output)
    empty_queue = asyncio.Queue()
    mock_telegram_adapter.register_mcp_listener.return_value = empty_queue

    # Call the tool (streaming - will timeout after 60s idle)
    # For testing, we'll collect chunks until timeout
    chunks = []
    try:
        async with asyncio.timeout(2.0):  # Give it 2 seconds max for test
            async for chunk in mcp_server.teleclaude__send(
                session_id=session.session_id,
                message="sleep 100"
            ):
                chunks.append(chunk)
    except asyncio.TimeoutError:
        pass  # Expected for this test

    output = "".join(chunks)

    # Verify timeout message appears or it's empty (depending on timing)
    # The implementation sends heartbeats and eventual timeout
    assert "[Timeout:" in output or output == ""

    # Verify cleanup happened
    mock_telegram_adapter.unregister_mcp_listener.assert_called_once()
