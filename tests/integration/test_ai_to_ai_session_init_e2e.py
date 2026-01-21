#!/usr/bin/env python3
"""E2E test for AI-to-AI session initialization via Redis transport."""

import asyncio
import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.constants import MAIN_MODULE

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_to_ai_session_initialization_with_claude_startup(daemon_with_mocked_telegram, tmp_path):
    """Test complete AI-to-AI session initialization flow.

    Verifies that when a remote computer receives a create_session command:
    1. Session is created with proper metadata
    2. Response is returned to the initiator
    """
    daemon = daemon_with_mocked_telegram

    # Mock Redis adapter to simulate incoming create_session command
    redis_transport = daemon.client.adapters.get("redis")
    if not redis_transport:
        pytest.skip("Redis adapter not configured")

    # Create mock Redis instance
    mock_redis = AsyncMock()
    redis_transport.redis = mock_redis

    with patch("teleclaude.core.event_bus.event_bus.emit", new_callable=AsyncMock):
        # Simulate incoming create_session command from initiator (MozBook)
        request_id = "test-request-123"
        project_path = tmp_path / "apps" / "TeleClaude"
        project_path.mkdir(parents=True, exist_ok=True)
        project_path = str(project_path)
        channel_metadata = {
            "telegram": {"channel_id": "12345"},
            "redis": {"channel_id": "test-channel"},
        }

        initiator_computer = "WorkstationA"
        {
            b"title": b"Test AI-to-AI Session",
            b"project_path": project_path.encode("utf-8"),
            b"initiator": initiator_computer.encode("utf-8"),
            b"channel_metadata": json.dumps(channel_metadata).encode("utf-8"),
        }

        # Mock send_response to capture response
        response_sent = None

        async def mock_send_response(req_id, response_data):
            nonlocal response_sent
            response_sent = {"request_id": req_id, "data": response_data}

        redis_transport.send_response = mock_send_response

        # Simulate incoming /new_session message through Redis stream
        # This is the standardized flow after refactoring
        message_data = {
            b"request_id": request_id.encode("utf-8"),
            b"session_id": request_id.encode("utf-8"),  # Used as request_id in protocol
            b"command": b"/new_session Test AI-to-AI Session",  # Title passed as command arg
            b"project_path": project_path.encode("utf-8"),
            b"initiator": initiator_computer.encode("utf-8"),
            b"channel_metadata": json.dumps(channel_metadata).encode("utf-8"),
            b"origin": b"telegram",
        }

        # Call _handle_incoming_message (the real entry point for Redis messages)
        await redis_transport._handle_incoming_message(request_id, message_data)

        # Wait for async operations to complete
        await asyncio.sleep(0.01)

    # Verify session was created
    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 1, "Should have created exactly one session"

    session = sessions[0]
    assert session.last_input_origin == "telegram"
    # Title format: {project}: $initiator > $computer - custom title
    # (Agent info not yet known at session creation - will be updated when agent starts)
    assert session.title.startswith(f"TeleClaude: ${initiator_computer} > ${session.computer_name} -")
    assert "Test AI-to-AI Session" in session.title
    # Description is optional, just verify session was created

    # NOTE: Command orchestration (agent start, etc.) is handled by MCP client flow.

    # Verify response was sent with session_id
    assert response_sent is not None, "Should have sent response"
    assert response_sent["request_id"] == request_id
    envelope = json.loads(response_sent["data"])
    assert envelope["status"] == "success", f"Response should have success status, got: {envelope}"
    assert envelope.get("data") is not None, f"Response should have data, got envelope: {envelope}"
    assert envelope["data"]["session_id"] == session.session_id

    # Output streaming is not used; MCP retrieves output via get_session_data polling.


@pytest.mark.asyncio
@pytest.mark.integration
async def test_ai_to_ai_session_without_project_path_rejected(daemon_with_mocked_telegram):
    """Test AI-to-AI session initialization without project directory is rejected."""
    daemon = daemon_with_mocked_telegram

    redis_transport = daemon.client.adapters.get("redis")
    if not redis_transport:
        pytest.skip("Redis adapter not configured")

    mock_redis = AsyncMock()
    redis_transport.redis = mock_redis

    with patch("teleclaude.core.event_bus.event_bus.emit", new_callable=AsyncMock):
        # Simulate create_session command WITHOUT project_path
        request_id = "test-request-456"

        response_sent = None

        async def mock_send_response(req_id, response_data):
            nonlocal response_sent
            response_sent = {"request_id": req_id, "data": response_data}

        redis_transport.send_response = mock_send_response

        # Simulate incoming /new_session message through Redis stream
        message_data = {
            b"request_id": request_id.encode("utf-8"),
            b"session_id": request_id.encode("utf-8"),
            b"command": b"/new_session",
            b"title": b"Test Session No Project",
            b"project_path": b"",
            b"initiator": b"WorkStation",
            b"channel_metadata": b"{}",
            b"origin": b"telegram",
        }

        await redis_transport._handle_incoming_message(request_id, message_data)

        await asyncio.sleep(0.01)

    # Verify no session was created
    sessions = await daemon.db.list_sessions()
    assert len(sessions) == 0, "Should not create session without project_path"

    # Verify response was sent
    assert response_sent is not None
    envelope = json.loads(response_sent["data"])
    assert envelope["status"] == "error", f"Response should have error status, got: {envelope}"


if __name__ == MAIN_MODULE:
    pytest.main([__file__, "-v"])
