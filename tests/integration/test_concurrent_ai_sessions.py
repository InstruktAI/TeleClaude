"""Integration tests for concurrent AI-to-AI sessions."""

import asyncio
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core.computer_registry import ComputerRegistry
from teleclaude.core.session_manager import SessionManager
from teleclaude.mcp_server import TeleClaudeMCPServer


class MockTelegramAdapter:
    """Mock Telegram adapter for testing."""

    def __init__(self, computer_name: str, message_bus: dict):
        self.computer_name = computer_name
        self.message_bus = message_bus
        self.listeners = {}

    async def send_message_to_topic(self, topic_id: int, text: str, parse_mode=None):
        """Send message to topic via message bus."""
        if topic_id not in self.message_bus:
            self.message_bus[topic_id] = []

        msg = Mock()
        msg.text = text
        msg.from_user = Mock()
        msg.from_user.username = f"teleclaude_{self.computer_name}_bot"

        self.message_bus[topic_id].append(msg)

        # Deliver to listeners
        if topic_id in self.listeners:
            for queue in self.listeners[topic_id]:
                await queue.put(msg)

        return Mock(message_id=len(self.message_bus[topic_id]))

    async def create_topic(self, title: str):
        """Create topic."""
        topic_id = hash(title) % 10000
        topic = Mock()
        topic.message_thread_id = topic_id
        return topic

    async def register_mcp_listener(self, topic_id: int):
        """Register listener for topic."""
        queue = asyncio.Queue()
        if topic_id not in self.listeners:
            self.listeners[topic_id] = []
        self.listeners[topic_id].append(queue)
        return queue

    async def unregister_mcp_listener(self, topic_id: int):
        """Unregister listener."""
        if topic_id in self.listeners:
            del self.listeners[topic_id]


@pytest.fixture
async def shared_message_bus():
    """Shared message bus for routing between mocked adapters."""
    return {}


@pytest.fixture
async def session_manager():
    """Create test session manager."""
    manager = SessionManager(db_path=":memory:")
    await manager.initialize()
    yield manager
    await manager.close()


@pytest.fixture
async def terminal_bridge():
    """Create mock terminal bridge."""
    bridge = Mock()
    bridge.send_keys = AsyncMock()
    return bridge


@pytest.fixture
async def computer_registry():
    """Create mock computer registry with online computers."""
    registry = Mock(spec=ComputerRegistry)

    def get_online():
        return [
            {"name": "comp1", "last_seen": "2025-01-01 00:00:00"},
            {"name": "comp2", "last_seen": "2025-01-01 00:00:00"},
            {"name": "comp3", "last_seen": "2025-01-01 00:00:00"},
        ]

    registry.get_online_computers = Mock(return_value=get_online())
    return registry


@pytest.fixture
async def mcp_servers(shared_message_bus, session_manager, terminal_bridge, computer_registry):
    """Create three MCP servers with shared message bus."""
    adapters = {
        "comp1": MockTelegramAdapter("comp1", shared_message_bus),
        "comp2": MockTelegramAdapter("comp2", shared_message_bus),
        "comp3": MockTelegramAdapter("comp3", shared_message_bus),
    }

    servers = []
    for comp_name, adapter in adapters.items():
        server = TeleClaudeMCPServer(
            config={"computer": {"name": comp_name}},
            telegram_adapter=adapter,
            terminal_bridge=terminal_bridge,
            session_manager=session_manager,
            computer_registry=computer_registry,
        )
        servers.append(server)

    return servers, shared_message_bus


@pytest.mark.integration
async def test_concurrent_sessions_dont_interfere(mcp_servers, shared_message_bus):
    """Test multiple concurrent AI-to-AI sessions don't interfere with each other."""
    server1, server2, server3 = mcp_servers[0]

    # Mock _wait_for_claude_ready to avoid actual waiting
    async def mock_wait(session_id, topic_id, timeout=10.0):
        # Instant ACK
        pass

    # Start three concurrent sessions: comp1→comp2, comp1→comp3, comp2→comp3
    with patch.object(server1, "_wait_for_claude_ready", side_effect=mock_wait):
        with patch.object(server2, "_wait_for_claude_ready", side_effect=mock_wait):
            session1_task = asyncio.create_task(
                server1.teleclaude__start_session(target="comp2", title="Session 1", description="Test 1")
            )

            session2_task = asyncio.create_task(
                server1.teleclaude__start_session(target="comp3", title="Session 2", description="Test 2")
            )

            session3_task = asyncio.create_task(
                server2.teleclaude__start_session(target="comp3", title="Session 3", description="Test 3")
            )

            # Wait for all sessions to start
            results = await asyncio.gather(session1_task, session2_task, session3_task)

    # Verify all sessions started successfully
    assert results[0]["status"] == "ready"
    assert results[1]["status"] == "ready"
    assert results[2]["status"] == "ready"

    # Verify each session has unique ID
    session_ids = [r["session_id"] for r in results]
    assert len(set(session_ids)) == 3  # All unique

    # Verify topic names are different
    assert results[0]["topic_name"] != results[1]["topic_name"]
    assert results[1]["topic_name"] != results[2]["topic_name"]


@pytest.mark.integration
async def test_concurrent_streaming_sessions(mcp_servers, shared_message_bus, session_manager):
    """Test concurrent streaming doesn't mix up messages."""
    server1, server2, server3 = mcp_servers[0]

    # Mock _wait_for_claude_ready
    async def mock_wait(session_id, topic_id, timeout=10.0):
        pass

    # Start two sessions
    with patch.object(server1, "_wait_for_claude_ready", side_effect=mock_wait):
        session1_result = await server1.teleclaude__start_session(
            target="comp2", title="Stream 1", description="Test streaming 1"
        )
        session2_result = await server1.teleclaude__start_session(
            target="comp3", title="Stream 2", description="Test streaming 2"
        )

    # Get topic IDs from session metadata
    session1 = await session_manager.get_session(session1_result["session_id"])
    session2 = await session_manager.get_session(session2_result["session_id"])
    topic1 = int(session1.adapter_metadata["channel_id"])
    topic2 = int(session2.adapter_metadata["channel_id"])

    # Background task: Send different chunks to each session (after listeners registered)
    async def send_chunks_to_session1():
        await asyncio.sleep(0.01)  # Let stream tasks register listeners first
        adapter = server1.telegram_adapter
        await adapter.send_message_to_topic(topic1, "```sh\nSession1-Chunk1\n```\n[Chunk 1/2]")
        await adapter.send_message_to_topic(topic1, "```sh\nSession1-Chunk2\n```\n[Chunk 2/2]")
        await adapter.send_message_to_topic(topic1, "[Output Complete]")

    async def send_chunks_to_session2():
        await asyncio.sleep(0.01)  # Let stream tasks register listeners first
        adapter = server1.telegram_adapter
        await adapter.send_message_to_topic(topic2, "```sh\nSession2-ChunkA\n```\n[Chunk 1/2]")
        await adapter.send_message_to_topic(topic2, "```sh\nSession2-ChunkB\n```\n[Chunk 2/2]")
        await adapter.send_message_to_topic(topic2, "[Output Complete]")

    # Stream from both sessions concurrently
    async def stream_session1():
        chunks = []
        async for chunk in server1.teleclaude__send(session1_result["session_id"], "test1"):
            chunks.append(chunk)
        return "".join(chunks)

    async def stream_session2():
        chunks = []
        async for chunk in server1.teleclaude__send(session2_result["session_id"], "test2"):
            chunks.append(chunk)
        return "".join(chunks)

    # Start stream tasks first (to register listeners), then chunk senders
    stream_task1 = asyncio.create_task(stream_session1())
    stream_task2 = asyncio.create_task(stream_session2())
    chunk_task1 = asyncio.create_task(send_chunks_to_session1())
    chunk_task2 = asyncio.create_task(send_chunks_to_session2())

    # Collect results
    output1, output2 = await asyncio.gather(stream_task1, stream_task2)
    await asyncio.gather(chunk_task1, chunk_task2)

    # Verify each session got correct chunks (no mixing)
    assert "Session1-Chunk1" in output1
    assert "Session1-Chunk2" in output1
    assert "Session2" not in output1  # No cross-contamination

    assert "Session2-ChunkA" in output2
    assert "Session2-ChunkB" in output2
    assert "Session1" not in output2  # No cross-contamination


@pytest.mark.integration
async def test_session_cleanup_doesnt_affect_others(mcp_servers, shared_message_bus, session_manager):
    """Test closing one session doesn't affect other active sessions."""
    server1, server2, server3 = mcp_servers[0]

    # Mock _wait_for_claude_ready
    async def mock_wait(session_id, topic_id, timeout=10.0):
        pass

    # Start two sessions
    with patch.object(server1, "_wait_for_claude_ready", side_effect=mock_wait):
        session1 = await server1.teleclaude__start_session(target="comp2", title="S1", description="Session 1")
        session2 = await server1.teleclaude__start_session(target="comp3", title="S2", description="Session 2")

    # Close session 1
    await session_manager.update_session(session1["session_id"], closed=True)

    # Verify session 2 still works (can stream)
    # Get topic ID from session metadata
    session2_obj = await session_manager.get_session(session2["session_id"])
    topic2 = int(session2_obj.adapter_metadata["channel_id"])

    async def send_chunks():
        await asyncio.sleep(0.01)  # Let stream task register listener first
        await server1.telegram_adapter.send_message_to_topic(topic2, "```sh\nstill working\n```\n[Chunk 1/1]")
        await server1.telegram_adapter.send_message_to_topic(topic2, "[Output Complete]")

    # Start stream first, then chunks
    async def stream_session():
        chunks = []
        async for chunk in server1.teleclaude__send(session2["session_id"], "test"):
            chunks.append(chunk)
        return "".join(chunks)

    stream_task = asyncio.create_task(stream_session())
    chunk_task = asyncio.create_task(send_chunks())

    output = await stream_task
    await chunk_task

    assert "still working" in output


@pytest.mark.integration
async def test_high_concurrency_stress(mcp_servers, shared_message_bus):
    """Test many concurrent sessions (stress test)."""
    server1, server2, server3 = mcp_servers[0]

    # Mock _wait_for_claude_ready
    async def mock_wait(session_id, topic_id, timeout=10.0):
        await asyncio.sleep(0.001)  # Very fast for stress test

    # Start 10 concurrent sessions
    with patch.object(server1, "_wait_for_claude_ready", side_effect=mock_wait):
        tasks = []
        for i in range(10):
            target = "comp2" if i % 2 == 0 else "comp3"
            task = asyncio.create_task(
                server1.teleclaude__start_session(target=target, title=f"Stress {i}", description=f"Test {i}")
            )
            tasks.append(task)

        results = await asyncio.gather(*tasks)

    # Verify all sessions started
    assert all(r["status"] == "ready" for r in results)

    # Verify all session IDs are unique
    session_ids = [r["session_id"] for r in results]
    assert len(set(session_ids)) == 10


@pytest.mark.integration
async def test_three_computer_chain(mcp_servers, shared_message_bus, session_manager):
    """Test 3-computer chain: Comp1 → Comp2 → Comp3.

    Scenario: Comp1 asks Comp2 to ask Comp3 for information.
    This tests multi-hop communication capability.
    """
    server1, server2, server3 = mcp_servers[0]

    # Mock _wait_for_claude_ready
    async def mock_wait(session_id, topic_id, timeout=10.0):
        pass

    # === Phase 1: Comp1 → Comp2 ===
    # Comp1 starts session with Comp2
    with patch.object(server1, "_wait_for_claude_ready", side_effect=mock_wait):
        session_1_to_2 = await server1.teleclaude__start_session(
            target="comp2", title="Ask Comp3", description="Comp1 asking Comp2 to query Comp3"
        )

    assert session_1_to_2["status"] == "ready"

    # === Phase 2: Comp2 → Comp3 ===
    # Comp2 starts session with Comp3 (simulating Claude Code on Comp2 doing this)
    with patch.object(server2, "_wait_for_claude_ready", side_effect=mock_wait):
        session_2_to_3 = await server2.teleclaude__start_session(
            target="comp3", title="Get Info", description="Comp2 querying Comp3 for Comp1"
        )

    assert session_2_to_3["status"] == "ready"

    # === Phase 3: Comp3 responds to Comp2 ===
    # Get topic ID for Comp2→Comp3 session
    session_2_to_3_obj = await session_manager.get_session(session_2_to_3["session_id"])
    topic_2_to_3 = int(session_2_to_3_obj.adapter_metadata["channel_id"])

    # Simulate Comp3 sending response to Comp2
    async def comp3_responds_to_comp2():
        await asyncio.sleep(0.01)  # Let listener register
        adapter = server2.telegram_adapter
        await adapter.send_message_to_topic(topic_2_to_3, "```sh\nComp3 data: disk usage 45%\n```\n[Chunk 1/1]")
        await adapter.send_message_to_topic(topic_2_to_3, "[Output Complete]")

    # Comp2 streams response from Comp3
    async def comp2_gets_comp3_response():
        chunks = []
        async for chunk in server2.teleclaude__send(session_2_to_3["session_id"], "df -h"):
            chunks.append(chunk)
        return "".join(chunks)

    # Run Comp2→Comp3 interaction
    stream_task = asyncio.create_task(comp2_gets_comp3_response())
    response_task = asyncio.create_task(comp3_responds_to_comp2())

    comp3_output = await stream_task
    await response_task

    assert "Comp3 data" in comp3_output
    assert "disk usage 45%" in comp3_output

    # === Phase 4: Comp2 responds to Comp1 ===
    # Get topic ID for Comp1→Comp2 session
    session_1_to_2_obj = await session_manager.get_session(session_1_to_2["session_id"])
    topic_1_to_2 = int(session_1_to_2_obj.adapter_metadata["channel_id"])

    # Simulate Comp2 forwarding Comp3's response to Comp1
    async def comp2_responds_to_comp1():
        await asyncio.sleep(0.01)  # Let listener register
        adapter = server1.telegram_adapter
        await adapter.send_message_to_topic(
            topic_1_to_2, f"```sh\nComp2 forwarding Comp3 response:\n{comp3_output}\n```\n[Chunk 1/1]"
        )
        await adapter.send_message_to_topic(topic_1_to_2, "[Output Complete]")

    # Comp1 streams response from Comp2
    async def comp1_gets_comp2_response():
        chunks = []
        async for chunk in server1.teleclaude__send(session_1_to_2["session_id"], "Ask Comp3 for disk usage"):
            chunks.append(chunk)
        return "".join(chunks)

    # Run Comp1→Comp2 interaction
    stream_task = asyncio.create_task(comp1_gets_comp2_response())
    response_task = asyncio.create_task(comp2_responds_to_comp1())

    final_output = await stream_task
    await response_task

    # Verify Comp1 received Comp3's data via Comp2
    assert "Comp2 forwarding Comp3 response" in final_output
    assert "Comp3 data" in final_output
    assert "disk usage 45%" in final_output

    # Verify we have two distinct sessions in DB
    all_sessions = []
    all_sessions.append(await session_manager.get_session(session_1_to_2["session_id"]))
    all_sessions.append(await session_manager.get_session(session_2_to_3["session_id"]))

    # Verify session topics are different
    assert all_sessions[0].title != all_sessions[1].title
    assert "$comp1 > $comp2" in all_sessions[0].title.lower()
    assert "$comp2 > $comp3" in all_sessions[1].title.lower()


@pytest.mark.integration
async def test_concurrent_streaming_performance(mcp_servers, shared_message_bus, session_manager):
    """Test concurrent streaming with 10+ sessions (performance validation).

    Validates performance characteristics:
    - Supports 10+ concurrent AI-to-AI sessions
    - Streaming works under load
    - No message mixing between sessions
    """
    server1, server2, server3 = mcp_servers[0]

    # Mock _wait_for_claude_ready
    async def mock_wait(session_id, topic_id, timeout=10.0):
        pass

    # Start 15 concurrent sessions (mix of comp2 and comp3 targets)
    with patch.object(server1, "_wait_for_claude_ready", side_effect=mock_wait):
        sessions = []
        for i in range(15):
            target = "comp2" if i % 2 == 0 else "comp3"
            session = await server1.teleclaude__start_session(
                target=target, title=f"Perf Test {i}", description=f"Performance test session {i}"
            )
            sessions.append(session)

    assert len(sessions) == 15
    assert all(s["status"] == "ready" for s in sessions)

    # Prepare streaming tasks for each session
    stream_tasks = []
    chunk_tasks = []

    for i, session in enumerate(sessions):
        session_obj = await session_manager.get_session(session["session_id"])
        topic_id = int(session_obj.adapter_metadata["channel_id"])

        # Task to send chunks to this session
        async def send_chunks(topic=topic_id, session_num=i):
            await asyncio.sleep(0.01)  # Let listeners register
            adapter = server1.telegram_adapter
            # Send 3 chunks per session
            await adapter.send_message_to_topic(topic, f"```sh\nSession{session_num} Line1\n```\n[Chunk 1/3]")
            await adapter.send_message_to_topic(topic, f"```sh\nSession{session_num} Line2\n```\n[Chunk 2/3]")
            await adapter.send_message_to_topic(topic, f"```sh\nSession{session_num} Line3\n```\n[Chunk 3/3]")
            await adapter.send_message_to_topic(topic, "[Output Complete]")

        # Task to stream from this session
        async def stream_session(session_id=session["session_id"], session_num=i):
            chunks = []
            async for chunk in server1.teleclaude__send(session_id, f"test command {session_num}"):
                chunks.append(chunk)
            return session_num, "".join(chunks)

        stream_tasks.append(asyncio.create_task(stream_session()))
        chunk_tasks.append(asyncio.create_task(send_chunks()))

    # Run all streaming tasks concurrently
    results = await asyncio.gather(*stream_tasks)
    await asyncio.gather(*chunk_tasks)

    # Verify all sessions completed successfully
    assert len(results) == 15

    # Verify no message mixing (each session got its own output)
    for session_num, output in results:
        # Should contain lines from this session only
        assert f"Session{session_num} Line1" in output
        assert f"Session{session_num} Line2" in output
        assert f"Session{session_num} Line3" in output

        # Should NOT contain lines from other sessions
        for other_num in range(15):
            if other_num != session_num:
                assert f"Session{other_num} Line" not in output, f"Session {session_num} got data from session {other_num}"
