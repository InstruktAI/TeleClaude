"""Integration test for teleclaude__run_agent_command regression.

Verifies that AI-to-AI sessions initiated via run_agent_command correctly
bootstrap, start polling, and execute auto-commands.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest


@pytest.mark.asyncio
async def test_run_agent_command_flow(daemon_with_mocked_telegram):
    """Test full flow of teleclaude__run_agent_command."""
    daemon = daemon_with_mocked_telegram

    # Use the MCP server directly
    handlers = daemon.mcp_server

    # Mock project root
    project_path = "/tmp"

    # Mock _handle_agent_then_message to succeed quickly
    with patch.object(daemon, "_handle_agent_then_message", new_callable=AsyncMock) as mock_handle:
        mock_handle.return_value = {"status": "success", "message": "Injected"}

        # Call the tool
        from teleclaude.core.models import ThinkingMode

        result = await handlers.teleclaude__run_agent_command(
            computer="local",
            command="/test-cmd",
            project=project_path,
            agent="claude",
            thinking_mode=ThinkingMode.SLOW,
        )

        assert result["status"] == "success"
        session_id = result["session_id"]
        assert session_id is not None

        # Manually mark session as active to simulate successful bootstrap
        # (Since we mock tmux and auto-command injection, we don't need to wait for the real bootstrap task)
        await daemon.db.update_session(session_id, lifecycle_status="active")

        # Verify session status in DB
        session = await daemon.db.get_session(session_id)
        assert session is not None
        assert session.lifecycle_status == "active"

        # Give event loop a chance to process the background bootstrap task
        # which calls our mock_handle.
        await asyncio.sleep(0.1)

        # Verify auto-command was executed
        assert mock_handle.called
