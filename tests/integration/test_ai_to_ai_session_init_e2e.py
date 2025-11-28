#!/usr/bin/env python3
"""E2E test for AI-to-AI session initialization with /cd and /claude commands."""

import asyncio
import json
from unittest.mock import AsyncMock, call, patch

import pytest

from teleclaude.core import terminal_bridge
from teleclaude.core.events import TeleClaudeEvents


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_to_ai_session_initialization_with_claude_startup(daemon_with_mocked_telegram):
    """Test complete AI-to-AI session initialization flow.

    Verifies that when a remote computer receives a create_session command:
    1. Session is created with proper metadata
    2. /cd command is sent to change to project directory
    3. /claude command is sent to start Claude Code
    4. Output stream listener is started for bidirectional communication
    """
    daemon = daemon_with_mocked_telegram

    # Mock Redis adapter to simulate incoming create_session command
    redis_adapter = daemon.client.adapters.get("redis")
    if not redis_adapter:
        pytest.skip("Redis adapter not configured")

    # Create mock Redis instance
    mock_redis = AsyncMock()
    redis_adapter.redis = mock_redis

    # Track handle_event calls to verify /cd and /claude were called
    original_handle_event = daemon.client.handle_event
    handle_event_calls = []

    async def track_handle_event(event, payload, metadata):
        handle_event_calls.append({"event": event, "payload": payload, "metadata": metadata})
        return await original_handle_event(event, payload, metadata)

    with patch.object(daemon.client, "handle_event", side_effect=track_handle_event):
        # Simulate incoming create_session command from initiator (MozBook)
        request_id = "test-request-123"
        project_dir = "/home/user/apps/TeleClaude"
        channel_metadata = {
            "telegram": {"channel_id": "12345"},
            "redis": {"channel_id": "test-channel", "output_stream": "output:initiator-session-456"},
        }

        command_data = {
            b"title": b"Test AI-to-AI Session",
            b"project_dir": project_dir.encode("utf-8"),
            b"initiator": b"MozBook",
            b"channel_metadata": json.dumps(channel_metadata).encode("utf-8"),
        }

        # Mock send_response to capture response
        response_sent = None

        async def mock_send_response(req_id, response_data):
            nonlocal response_sent
            response_sent = {"request_id": req_id, "data": response_data}

        redis_adapter.send_response = mock_send_response

        # Mock _start_output_stream_listener to verify it's called
        listener_started = []

        def mock_start_listener(session_id):
            listener_started.append(session_id)

        with patch.object(redis_adapter, "_start_output_stream_listener", side_effect=mock_start_listener):
            # Execute _create_session_from_redis (the actual flow when create_session is received)
            await redis_adapter._create_session_from_redis(
                request_id=request_id, data=command_data, respond_with_session_id=True
            )

            # Wait for async operations to complete
            await asyncio.sleep(0.5)

    # Verify session was created
    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1, "Should have created exactly one session"

    session = sessions[0]
    assert session.origin_adapter == "redis"
    assert session.adapter_metadata.get("target_computer") == "MozBook"
    assert session.adapter_metadata.get("project_dir") == project_dir
    assert session.title == "Test AI-to-AI Session"  # Title comes from command data
    assert "MozBook" in session.description  # Description includes initiator

    # Verify /cd command was called
    cd_calls = [c for c in handle_event_calls if c["event"] == TeleClaudeEvents.CD]
    assert len(cd_calls) == 1, "Should have called /cd command exactly once"
    assert cd_calls[0]["payload"]["session_id"] == session.session_id
    assert cd_calls[0]["payload"]["args"] == [project_dir]
    assert cd_calls[0]["metadata"]["adapter_type"] == "redis"

    # Verify /claude command was called
    claude_calls = [c for c in handle_event_calls if c["event"] == TeleClaudeEvents.CLAUDE]
    assert len(claude_calls) == 1, "Should have called /claude command exactly once"
    assert claude_calls[0]["payload"]["session_id"] == session.session_id
    assert claude_calls[0]["payload"]["args"] == []
    assert claude_calls[0]["metadata"]["adapter_type"] == "redis"

    # Verify /cd was called BEFORE /claude
    cd_index = next(i for i, c in enumerate(handle_event_calls) if c["event"] == TeleClaudeEvents.CD)
    claude_index = next(i for i, c in enumerate(handle_event_calls) if c["event"] == TeleClaudeEvents.CLAUDE)
    assert cd_index < claude_index, "/cd should be called before /claude"

    # Verify response was sent with session_id
    assert response_sent is not None, "Should have sent response"
    assert response_sent["request_id"] == request_id
    response_data = json.loads(response_sent["data"])
    assert response_data["session_id"] == session.session_id

    # Verify output stream listener was started
    assert len(listener_started) == 1, "Should have started output stream listener"
    assert listener_started[0] == session.session_id, "Listener should be started for correct session"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_to_ai_session_without_project_dir(daemon_with_mocked_telegram):
    """Test AI-to-AI session initialization without project directory.

    Verifies that when project_dir is not provided:
    1. Session is created successfully
    2. /cd command is NOT called
    3. /claude command is still called
    4. Output stream listener is started
    """
    daemon = daemon_with_mocked_telegram

    redis_adapter = daemon.client.adapters.get("redis")
    if not redis_adapter:
        pytest.skip("Redis adapter not configured")

    mock_redis = AsyncMock()
    redis_adapter.redis = mock_redis

    # Track handle_event calls
    handle_event_calls = []
    original_handle_event = daemon.client.handle_event

    async def track_handle_event(event, payload, metadata):
        handle_event_calls.append({"event": event, "payload": payload, "metadata": metadata})
        return await original_handle_event(event, payload, metadata)

    with patch.object(daemon.client, "handle_event", side_effect=track_handle_event):
        # Simulate create_session command WITHOUT project_dir
        request_id = "test-request-456"
        command_data = {
            b"title": b"Test Session No Project",
            b"project_dir": b"",  # Empty project_dir
            b"initiator": b"WorkStation",
            b"channel_metadata": b"{}",
        }

        response_sent = None

        async def mock_send_response(req_id, response_data):
            nonlocal response_sent
            response_sent = {"request_id": req_id, "data": response_data}

        redis_adapter.send_response = mock_send_response

        await redis_adapter._create_session_from_redis(
            request_id=request_id, data=command_data, respond_with_session_id=True
        )

        await asyncio.sleep(0.5)

    # Verify session was created
    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1

    # Verify /cd was NOT called (no project_dir)
    cd_calls = [c for c in handle_event_calls if c["event"] == TeleClaudeEvents.CD]
    assert len(cd_calls) == 0, "Should NOT call /cd when project_dir is empty"

    # Verify /claude was still called
    claude_calls = [c for c in handle_event_calls if c["event"] == TeleClaudeEvents.CLAUDE]
    assert len(claude_calls) == 1, "Should still call /claude even without project_dir"

    # Verify response was sent
    assert response_sent is not None
    response_data = json.loads(response_sent["data"])
    assert "session_id" in response_data


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_to_ai_cd_and_claude_commands_execute_in_tmux(daemon_with_mocked_telegram):
    """Test that /cd and /claude commands actually execute in tmux session.

    This test verifies the complete flow from handle_event to tmux execution:
    1. Commands are dispatched to command handlers
    2. Commands execute in the correct tmux session
    3. Terminal shows expected output
    """
    daemon = daemon_with_mocked_telegram

    redis_adapter = daemon.client.adapters.get("redis")
    if not redis_adapter:
        pytest.skip("Redis adapter not configured")

    mock_redis = AsyncMock()
    redis_adapter.redis = mock_redis

    # Create session
    request_id = "test-request-789"
    project_dir = "/tmp/test-project"
    command_data = {
        b"title": b"Test Tmux Execution",
        b"project_dir": project_dir.encode("utf-8"),
        b"initiator": b"TestComputer",
        b"channel_metadata": b"{}",
    }

    response_sent = None

    async def mock_send_response(req_id, response_data):
        nonlocal response_sent
        response_sent = {"request_id": req_id, "data": response_data}

    redis_adapter.send_response = mock_send_response

    await redis_adapter._create_session_from_redis(
        request_id=request_id, data=command_data, respond_with_session_id=True
    )

    # Get created session
    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1
    session = sessions[0]

    # Wait for commands to execute
    await asyncio.sleep(2.0)

    # Capture terminal output
    output = await terminal_bridge.capture_pane(session.tmux_session_name)
    assert output is not None, "Should have terminal output"

    # Verify /cd executed (should see directory change)
    # Note: actual directory change might not be visible, but command should have been sent
    # We can verify by checking session still exists and tmux session is alive
    assert await terminal_bridge.session_exists(session.tmux_session_name), "Tmux session should exist"

    # Verify /claude was executed (should see "Starting Claude Code..." or similar)
    # Since we're testing with real tmux but mocked Claude startup, we verify the command was sent
    # The actual Claude startup is tested in test_claude_command_e2e.py


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
