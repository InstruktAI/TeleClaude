"""End-to-end integration test for daemon-to-daemon MCP communication.

This test simulates two daemon instances communicating with controlled timing.
All timeouts are mocked - no real waits.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core.computer_registry import ComputerRegistry
from teleclaude.core.session_manager import SessionManager
from teleclaude.mcp_server import TeleClaudeMCPServer


class SharedMessageBus:
    """Simulates Telegram topics with message routing between daemons."""

    def __init__(self):
        self.topics = {}  # topic_id -> list of messages
        self.listeners = {}  # (adapter_id, topic_id) -> queue

    async def create_topic(self, name: str):
        """Create a new topic."""
        topic_id = len(self.topics) + 1000
        self.topics[topic_id] = []
        topic = Mock()
        topic.message_thread_id = topic_id
        return topic

    async def send_message(self, sender: str, topic_id: int, text: str):
        """Send message to topic from sender."""
        msg = Mock()
        msg.text = text
        msg.message_id = len(self.topics.get(topic_id, [])) + 1
        msg.from_user = Mock()
        msg.from_user.username = f"teleclaude_{sender}_bot"

        # Store message
        if topic_id not in self.topics:
            self.topics[topic_id] = []
        self.topics[topic_id].append(msg)

        # Deliver to all listeners for this topic
        for (adapter_id, tid), queue in list(self.listeners.items()):
            if tid == topic_id:
                await queue.put(msg)

        return msg

    def register_listener(self, adapter_id: str, topic_id: int):
        """Register listener queue for topic."""
        queue = asyncio.Queue()
        self.listeners[(adapter_id, topic_id)] = queue
        return queue

    def unregister_listener(self, adapter_id: str, topic_id: int):
        """Unregister listener."""
        self.listeners.pop((adapter_id, topic_id), None)


class MockTelegramAdapter:
    """Mock adapter that uses shared message bus."""

    def __init__(self, computer_name: str, message_bus: SharedMessageBus):
        self.computer_name = computer_name
        self.message_bus = message_bus
        self.supergroup_id = "-100123456789"

        # Mock bot for registry
        self.app = Mock()
        self.app.bot = Mock()
        self.app.bot.edit_message_text = AsyncMock()

    async def create_topic(self, name: str):
        """Create topic."""
        return await self.message_bus.create_topic(name)

    async def send_message_to_topic(self, topic_id: int, text: str, parse_mode=None):
        """Send message to topic."""
        return await self.message_bus.send_message(self.computer_name, topic_id, text)

    async def register_mcp_listener(self, topic_id: int):
        """Register MCP listener."""
        return self.message_bus.register_listener(self.computer_name, topic_id)

    async def unregister_mcp_listener(self, topic_id: int):
        """Unregister MCP listener."""
        self.message_bus.unregister_listener(self.computer_name, topic_id)

    async def get_topic_messages(self, topic_id: int, limit: int = 100):
        """Get messages (for registry)."""
        return self.message_bus.topics.get(topic_id, [])[:limit]


@pytest.fixture
def message_bus():
    """Shared message bus between daemons."""
    return SharedMessageBus()


@pytest.fixture
async def session_managers(tmp_path):
    """Session managers for both daemons."""
    db1 = SessionManager(str(tmp_path / "comp1.db"))
    await db1.initialize()

    db2 = SessionManager(str(tmp_path / "comp2.db"))
    await db2.initialize()

    yield db1, db2

    await db1.close()
    await db2.close()


@pytest.fixture
def telegram_adapters(message_bus):
    """Telegram adapters for both daemons."""
    adapter1 = MockTelegramAdapter("comp1", message_bus)
    adapter2 = MockTelegramAdapter("comp2", message_bus)
    return adapter1, adapter2


@pytest.fixture
def computer_registries(telegram_adapters, session_managers):
    """Computer registries for both daemons."""
    adapter1, adapter2 = telegram_adapters
    db1, db2 = session_managers

    registry1 = ComputerRegistry(adapter1, "comp1", "teleclaude_comp1_bot", db1)
    registry1.registry_topic_id = 999

    registry2 = ComputerRegistry(adapter2, "comp2", "teleclaude_comp2_bot", db2)
    registry2.registry_topic_id = 999

    # Both see each other as online
    now = datetime.now()
    for registry in [registry1, registry2]:
        registry.computers = {
            "comp1": {"name": "comp1", "status": "online", "last_seen": now},
            "comp2": {"name": "comp2", "status": "online", "last_seen": now}
        }

    return registry1, registry2


@pytest.fixture
def mcp_servers(telegram_adapters, session_managers, computer_registries):
    """MCP servers for both daemons."""
    from teleclaude import config as config_module

    adapter1, adapter2 = telegram_adapters
    db1, db2 = session_managers
    registry1, registry2 = computer_registries

    mock_bridge = Mock()
    mock_bridge.send_keys = AsyncMock()

    # Create mock adapter client
    mock_client = Mock()
    async def mock_discover_peers():
        return [
            {"name": "comp1", "status": "online"},
            {"name": "comp2", "status": "online"}
        ]
    mock_client.discover_peers = AsyncMock(side_effect=mock_discover_peers)

    # Create server1 with mocked config
    with patch.object(config_module, '_config', {"computer": {"name": "comp1"}, "mcp": {"transport": "stdio"}}):
        server1 = TeleClaudeMCPServer(adapter1, mock_bridge, db1, registry1, mock_client)

    # Create server2 with mocked config
    with patch.object(config_module, '_config', {"computer": {"name": "comp2"}, "mcp": {"transport": "stdio"}}):
        server2 = TeleClaudeMCPServer(adapter2, mock_bridge, db2, registry2, mock_client)

    return server1, server2


@pytest.mark.integration
async def test_daemon_to_daemon_full_flow(mcp_servers, message_bus):
    """Test full Comp1 -> Comp2 communication flow with controlled timing."""
    server1, server2 = mcp_servers

    # STEP 1: Comp1 starts session
    # We need to mock _wait_for_claude_ready to not actually wait 10s

    async def mock_wait_for_ready(session_id, topic_id, timeout=10.0):
        """Mock wait that returns when ACK arrives (no timeout)."""
        queue = await server1.telegram_adapter.register_mcp_listener(topic_id)
        try:
            # Just get next message (assume it's ACK)
            msg = await asyncio.wait_for(queue.get(), timeout=1.0)
            if msg.text != "/claude_resume":
                return  # Got ACK
        finally:
            await server1.telegram_adapter.unregister_mcp_listener(topic_id)

    # Background task: Comp2 responds to /claude_resume
    async def comp2_daemon_receives_resume():
        """Simulate Comp2 daemon detecting /claude_resume and sending ACK."""
        await asyncio.sleep(0.05)  # Minimal delay

        # Find the topic with /claude_resume
        for topic_id, messages in message_bus.topics.items():
            for msg in messages:
                if msg.text == "/claude_resume":
                    # Comp2 sends ACK
                    await message_bus.send_message("comp2", topic_id, "ACK: Claude Code ready")
                    return

    with patch.object(server1, '_wait_for_claude_ready', side_effect=mock_wait_for_ready):
        comp2_task = asyncio.create_task(comp2_daemon_receives_resume())

        # Comp1 starts session
        result = await server1.teleclaude__start_session(
            target="comp2",
            title="Test",
            description="Testing flow"
        )

        await comp2_task

    assert result["status"] == "ready"
    assert "comp2" in result["topic_name"]
    session_id = result["session_id"]
    topic_id = int((await server1.session_manager.get_session(session_id)).adapter_metadata["channel_id"])

    # STEP 2: Comp1 sends command
    # We need to mock the stability check (3 seconds of no messages)

    # Background task: Comp2 executes and sends output
    async def comp2_daemon_executes():
        """Simulate Comp2 executing command and streaming output."""
        await asyncio.sleep(0.05)
        await message_bus.send_message("comp2", topic_id, "Output line 1")
        await asyncio.sleep(0.05)
        await message_bus.send_message("comp2", topic_id, "Output line 2")
        await asyncio.sleep(0.05)
        await message_bus.send_message("comp2", topic_id, "Command complete")

    # Mock the stability timeout to be instant
    original_send = server1.teleclaude__send

    async def mock_send(session_id, message):
        """Mock send with instant stability check."""
        session = await server1.session_manager.get_session(session_id)
        if not session:
            return {"status": "error", "message": f"Session '{session_id}' not found"}
        if session.closed:
            return {"status": "error", "message": f"Session '{session_id}' is closed"}

        # Send to terminal
        await server1.terminal_bridge.send_keys(session.tmux_session_name, message)

        # Collect output with FAST stability check
        topic_id = int(session.adapter_metadata.get("channel_id"))
        queue = await server1.telegram_adapter.register_mcp_listener(topic_id)

        try:
            output_lines = []
            stable_count = 0

            # Wait max 2 seconds total, 0.1s per check
            for _ in range(20):
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=0.1)
                    stable_count = 0
                    if msg.text:
                        output_lines.append(msg.text)
                except asyncio.TimeoutError:
                    stable_count += 1
                    if stable_count >= 2:  # 0.2s stability = done
                        break

            return {
                "status": "success",
                "output": "\n".join(output_lines),
                "message": "Command executed"
            }
        finally:
            await server1.telegram_adapter.unregister_mcp_listener(topic_id)

    with patch.object(server1, 'teleclaude__send', side_effect=mock_send):
        comp2_exec_task = asyncio.create_task(comp2_daemon_executes())

        result = await server1.teleclaude__send(
            session_id=session_id,
            message="echo test"
        )

        await comp2_exec_task

    assert result["status"] == "success"
    assert "Output line 1" in result["output"]
    assert "Output line 2" in result["output"]
    assert "Command complete" in result["output"]


@pytest.mark.integration
async def test_daemon_to_daemon_lists_sessions(mcp_servers, message_bus):
    """Test that Comp1 can list sessions it created with Comp2."""
    server1, server2 = mcp_servers

    # Create a session directly in database (bypass the /claude_resume flow)
    session = await server1.session_manager.create_session(
        computer_name="comp1",
        tmux_session_name="comp1-ai-test",
        adapter_type="telegram",
        title="$comp1 > $comp2 - Debug logs",
        adapter_metadata={"channel_id": "12345"},
        description="Debugging 502 errors"
    )

    # List sessions
    result = await server1.teleclaude__list_sessions(target="comp2")

    assert len(result) == 1
    assert result[0]["target"] == "comp2"
    assert result[0]["title"] == "Debug logs"
    assert result[0]["description"] == "Debugging 502 errors"
