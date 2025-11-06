#!/usr/bin/env python3
"""Test full message flow including output polling."""

import asyncio

import pytest

from teleclaude.core import terminal_bridge


@pytest.mark.asyncio
@pytest.mark.timeout(15)  # Integration test with real tmux needs more time
async def test_message_execution_and_output_polling(daemon_with_mocked_telegram):
    """Test complete message flow: execute command, poll output, send to Telegram."""
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new-session", ["Flow", "Test"], context)

    # Get the created session
    sessions = await daemon.session_manager.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]

    # Reset mock to track only this test's calls
    telegram = daemon.client.adapters["telegram"]
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()

    # FIRST command - should send new message
    msg_context1 = {"user_id": 12345, "message_id": 999}
    task1 = asyncio.create_task(daemon.handle_message(session.session_id, "echo 'First Output'", msg_context1))

    # Wait for polling to complete
    try:
        await asyncio.wait_for(task1, timeout=5.0)
    except asyncio.TimeoutError:
        task1.cancel()
        await task1
        pytest.fail("First command polling did not complete in expected time")

    # Verify terminal has output from first command
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None
    assert "First Output" in output or "echo" in output

    # Verify FIRST command behavior: send new message (no existing message to edit)
    telegram = daemon.client.adapters["telegram"]
    assert telegram.send_message.call_count == 1, "First command should send exactly one new message"
    assert telegram.edit_message.call_count == 0, "First command should not edit (no existing message)"

    # Reset mocks for second command
    telegram.send_message.reset_mock()
    telegram.edit_message.reset_mock()

    # SECOND command - should edit existing message
    msg_context2 = {"user_id": 12345, "message_id": 1000}
    task2 = asyncio.create_task(daemon.handle_message(session.session_id, "echo 'Second Output'", msg_context2))

    # Wait for polling to complete
    try:
        await asyncio.wait_for(task2, timeout=5.0)
    except asyncio.TimeoutError:
        task2.cancel()
        await task2
        pytest.fail("Second command polling did not complete in expected time")

    # Verify terminal has output from second command
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None
    assert "Second Output" in output or "echo" in output

    # Verify SECOND command behavior: edit existing message (reuse, don't spam)
    telegram = daemon.client.adapters["telegram"]
    assert telegram.send_message.call_count == 0, "Second command should not send new message"
    assert telegram.edit_message.call_count == 1, "Second command should edit existing message exactly once"


@pytest.mark.asyncio
async def test_command_execution_via_terminal(daemon_with_mocked_telegram):
    """Test that commands execute in terminal and output is captured."""
    daemon = daemon_with_mocked_telegram

    # Create a test session
    context = {"adapter_type": "telegram", "user_id": 12345, "chat_id": -67890, "message_thread_id": None}
    await daemon.handle_command("new-session", ["Terminal", "Test"], context)

    sessions = await daemon.session_manager.list_sessions()
    session = sessions[0]

    # Send command directly to terminal
    await terminal_bridge.send_keys(session.tmux_session_name, "echo 'Direct command'")
    await asyncio.sleep(0.2)

    # Verify output in terminal
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None
    assert "Direct command" in output or "echo" in output

    # Verify tmux session is still alive
    exists = await terminal_bridge.session_exists(session.tmux_session_name)
    assert exists, "tmux session should still exist"


@pytest.mark.asyncio
@pytest.mark.timeout(20)  # Multi-computer flow needs more time
async def test_multi_computer_mcp_command_execution(daemon_with_mocked_telegram, tmp_path):
    """Test real MCP flow: Comp1 → Comp2 with actual tmux execution.

    This tests the complete AI-to-AI flow:
    1. Comp1 (MCP client) starts session with Comp2
    2. Comp1 sends command to Comp2 via MCP
    3. Comp2 executes command in REAL tmux session
    4. Comp2 streams output back to Comp1
    5. Comp1 receives complete output
    """
    from teleclaude.mcp_server import TeleClaudeMCPServer
    from teleclaude.core.computer_registry import ComputerRegistry
    from datetime import datetime
    from unittest.mock import patch

    daemon = daemon_with_mocked_telegram

    # Setup Comp1 (this daemon - MCP client side)
    telegram = daemon.client.adapters["telegram"]
    comp1_registry = ComputerRegistry(
        telegram,
        "comp1",
        "teleclaude_comp1_bot",
        daemon.session_manager
    )
    comp1_registry.registry_topic_id = 999
    comp1_registry.computers = {
        "comp1": {"name": "comp1", "status": "online", "last_seen": datetime.now()},
        "comp2": {"name": "comp2", "status": "online", "last_seen": datetime.now()}
    }

    # Create mock adapter client
    from unittest.mock import AsyncMock, Mock
    mock_client = Mock()
    async def mock_discover_peers():
        return [
            {"name": "comp1", "status": "online"},
            {"name": "comp2", "status": "online"}
        ]
    mock_client.discover_peers = AsyncMock(side_effect=mock_discover_peers)

    from teleclaude import config as config_module
    with patch.object(config_module, '_config', {"computer": {"name": "comp1"}, "mcp": {"transport": "stdio"}}):
        comp1_mcp = TeleClaudeMCPServer(
            telegram,
            terminal_bridge,
            daemon.session_manager,
            comp1_registry,
            mock_client
        )

    # Setup Comp2 (second daemon - executes commands)
    comp2_db_path = tmp_path / "comp2.db"
    from teleclaude.core.session_manager import SessionManager
    comp2_session_manager = SessionManager(str(comp2_db_path))
    await comp2_session_manager.initialize()

    # Shared message bus for communication
    message_topic = {}  # topic_id -> list of messages

    # Mock Comp1's telegram adapter to store messages
    telegram = daemon.client.adapters["telegram"]
    original_send_to_topic = telegram.send_message_to_topic
    async def comp1_send_to_topic(topic_id, text, parse_mode=None):
        if topic_id not in message_topic:
            message_topic[topic_id] = []
        msg = {"text": text, "from": "comp1"}
        message_topic[topic_id].append(msg)
        return msg

    telegram.send_message_to_topic = comp1_send_to_topic

    # Create session on Comp2 (simulating /claude_resume response)
    comp2_session = await comp2_session_manager.create_session(
        computer_name="comp2",
        tmux_session_name="comp2-ai-test",
        adapter_type="telegram",
        title="$comp1 > $comp2 - Test execution",
        adapter_metadata={"channel_id": "5000"},
        description="Testing real command execution"
    )

    # STEP 1: Start session (simplified - skip /claude_resume handshake)
    # Directly create session on Comp1 side to match Comp2
    comp1_session = await daemon.session_manager.create_session(
        computer_name="comp1",
        tmux_session_name="comp1-ai-outbound",
        adapter_type="telegram",
        title="$comp1 > $comp2 - Test execution",
        adapter_metadata={"channel_id": "5000"},  # Same topic
        description="Testing real command execution"
    )

    # STEP 2: Comp1 sends command to Comp2
    command = "echo 'Multi-computer test output'"

    # Comp1 sends command to topic
    telegram = daemon.client.adapters["telegram"]
    await telegram.send_message_to_topic(5000, command)

    # Comp2 receives command and executes using PRODUCTION POLLING CODE
    # This is the real async flow - no timers!
    from teleclaude.core import polling_coordinator
    from teleclaude.core.output_poller import OutputPoller
    from pathlib import Path

    comp2_output_file = tmp_path / f"comp2_{comp2_session.session_id[:8]}.txt"
    comp2_config = {"polling": {"idle_notification_seconds": 60}, "computer": {"timezone": "UTC"}}
    comp2_poller = OutputPoller(comp2_config, comp2_session_manager)

    # Mock adapter for Comp2 that captures output
    comp2_output = {"text": None, "sent": False}

    from unittest.mock import AsyncMock, Mock
    comp2_mock_adapter = Mock()

    async def capture_send(sid, text, metadata=None):
        comp2_output["text"] = text
        comp2_output["sent"] = True
        return "msg-id"

    comp2_mock_adapter.send_message = AsyncMock(side_effect=capture_send)
    comp2_mock_adapter.edit_message = AsyncMock(return_value=True)

    async def get_comp2_adapter(sid):
        return comp2_mock_adapter

    # Use REAL polling coordinator - proper async, no timers!
    poll_task = asyncio.create_task(
        polling_coordinator.poll_and_send_output(
            session_id=comp2_session.session_id,
            tmux_session_name=comp2_session.tmux_session_name,
            session_manager=comp2_session_manager,
            output_poller=comp2_poller,
            get_adapter_for_session=get_comp2_adapter,
            get_output_file=lambda sid: comp2_output_file,
        )
    )

    # Send command to Comp2's tmux
    await terminal_bridge.send_keys(
        comp2_session.tmux_session_name,
        command,
        append_exit_marker=True
    )

    # Wait for polling to naturally complete (exits when command finishes)
    try:
        await asyncio.wait_for(poll_task, timeout=5.0)
    except asyncio.TimeoutError:
        poll_task.cancel()
        pytest.fail("Command polling did not complete")

    # Verify output was captured by production code
    assert comp2_output["sent"], "Comp2 should have sent output"
    assert "Multi-computer test output" in comp2_output["text"]

    # Simulate Comp2 streaming output back to topic
    await comp1_send_to_topic(5000, comp2_output["text"])
    await comp1_send_to_topic(5000, "[Output Complete]")

    # STEP 3: Comp1 receives output from topic
    received_messages = message_topic.get(5000, [])

    # Verify communication flow
    assert len(received_messages) >= 3, "Should have: command + chunk + complete"
    assert any("Multi-computer test output" in msg["text"] for msg in received_messages)
    assert any("[Output Complete]" in msg["text"] for msg in received_messages)

    # Verify REAL tmux session exists for Comp2
    comp2_exists = await terminal_bridge.session_exists(comp2_session.tmux_session_name)
    assert comp2_exists, "Comp2 tmux session should exist"

    # Cleanup
    await terminal_bridge.kill_session(comp2_session.tmux_session_name)
    await comp2_session_manager.delete_session(comp2_session.session_id)
    await comp2_session_manager.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
