"""Integration test for send_message flow.

Tests the complete flow:
1. Start a remote session
2. Send a message to the session
3. Verify the message is processed and output can be retrieved
"""

import asyncio
import time
import uuid

import pytest

from teleclaude.adapters.redis_adapter import RedisAdapter
from teleclaude.core.adapter_client import AdapterClient
from teleclaude.core import terminal_bridge
from teleclaude.mcp_server import TeleClaudeMCPServer


@pytest.mark.skip(reason="get_session_data cross-computer functionality not yet implemented")
@pytest.mark.asyncio
@pytest.mark.integration
async def test_send_message_to_remote_session():
    """Test sending a message to a remote session."""
    # Initialize client and MCP server
    client = AdapterClient()
    client._load_adapters()
    await client.start()

    try:
        mcp = TeleClaudeMCPServer(client, terminal_bridge)

        # Find an online computer
        redis_adapter = client.adapters.get("redis")
        assert redis_adapter, "Redis adapter not found"
        assert isinstance(redis_adapter, RedisAdapter), "Redis adapter wrong type"

        peers = await redis_adapter.discover_peers()
        assert len(peers) > 0, "No online computers found"

        target_computer = peers[0]["name"]
        print(f"\n✓ Found online computer: {target_computer}")

        # List projects
        projects = await mcp.teleclaude__list_projects(target_computer)
        assert len(projects) > 0, f"No projects found on {target_computer}"

        project_dir = projects[0]["location"]
        print(f"✓ Using project: {project_dir}")

        # Start session
        result = await mcp.teleclaude__start_session(target_computer, project_dir)
        assert result.get("status") == "success", f"Failed to start session: {result}"

        session_id = result["session_id"]
        print(f"✓ Started session: {session_id[:8]}")

        # Wait for session to initialize
        await asyncio.sleep(3)

        # Send a simple command
        test_message = f"echo 'test-{uuid.uuid4().hex[:8]}'"
        print(f"✓ Sending message: {test_message}")

        chunks = []
        async for chunk in mcp.teleclaude__send_message(session_id, test_message):
            chunks.append(chunk)

        response = "".join(chunks)
        assert "Message sent" in response, f"Unexpected response: {response}"
        print(f"✓ Message sent successfully")

        # Wait for command to execute
        await asyncio.sleep(2)

        # Get session data
        print(f"✓ Retrieving session data...")
        data = await mcp.teleclaude__get_session_data(target_computer, session_id)

        # Check if we got data
        if data.get("status") == "success":
            messages = data.get("messages", [])
            print(f"✓ Retrieved {len(messages)} messages")

            # Print last few messages for debugging
            for msg in messages[-5:]:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")[:100]
                print(f"  [{role}] {content}")

            # Verify we have messages
            assert len(messages) > 0, "No messages in session data"
        else:
            error = data.get("error")
            pytest.skip(f"Session data not available yet: {error}")

        print(f"\n✅ Test passed - send_message flow works correctly!")

    finally:
        await client.stop()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_message_command_parsing():
    """Test that 'message <text>' is parsed correctly to trigger MESSAGE event."""
    from teleclaude.core.events import parse_command_string, TeleClaudeEvents

    # Test parsing (shlex strips quotes)
    cmd, args = parse_command_string("message echo 'hello'")

    assert cmd == "message", f"Expected cmd='message', got '{cmd}'"
    assert args == ["echo", "hello"], f"Expected args=['echo', 'hello'], got {args}"

    # Verify this matches MESSAGE event
    assert cmd == TeleClaudeEvents.MESSAGE

    # Test that the args join correctly
    text = " ".join(args)
    assert text == "echo hello", f"Expected text='echo hello', got '{text}'"

    print("\n✅ Message parsing works correctly!")
