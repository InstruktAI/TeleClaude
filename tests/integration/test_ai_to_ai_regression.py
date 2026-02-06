"""Regression tests for AI-to-AI coordination.

Verifies fixes for:
1. ThinkingMode Enum validation in MCP handlers.
2. AI-to-AI session notification flow.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from teleclaude.core.models import ThinkingMode
from teleclaude.mcp_server import TeleClaudeMCPServer


@pytest.mark.asyncio
async def test_run_agent_command_enum_validation_fix(daemon_with_mocked_telegram):
    """Verify that run_agent_command correctly handles ThinkingMode strings and defaults."""
    daemon = daemon_with_mocked_telegram
    handlers = daemon.mcp_server

    # Mock project root
    project_path = "/tmp"

    # Mock create_session to succeed immediately
    with patch("teleclaude.daemon.tmux_bridge.ensure_tmux_session", new_callable=AsyncMock, return_value=True):
        with patch.object(daemon, "_handle_agent_then_message", new_callable=AsyncMock) as mock_handle:
            mock_handle.return_value = {"status": "success", "message": "Injected"}

            # 1. Test with string "med" (common from LLMs)
            result = await handlers.teleclaude__run_agent_command(
                computer="local",
                command="/next-review",
                args="test-slug",
                project=project_path,
                agent="claude",
                thinking_mode="med",  # Pass string
            )
            assert result["status"] == "success"

            # 2. Test with default (None in tool call results in ThinkingMode.SLOW)
            # We simulate the MCP layer passing a dict
            from teleclaude.core.models import RunAgentCommandArgs

            args = RunAgentCommandArgs.from_mcp(
                {
                    "computer": "local",
                    "command": "/next-review",
                    "args": "test-slug",
                    "project": project_path,
                    "agent": "claude",
                    # thinking_mode missing
                },
                caller_session_id=None,
            )
            assert args.thinking_mode == ThinkingMode.SLOW

            # 3. Test with 'deep' (new mode)
            result = await handlers.teleclaude__run_agent_command(
                computer="local",
                command="/next-review",
                args="test-slug",
                project=project_path,
                agent="codex",
                thinking_mode="deep",
            )
            assert result["status"] == "success"


@pytest.mark.asyncio
async def test_ai_to_ai_notification_delivery(daemon_with_mocked_telegram):
    """Verify that stop notifications are delivered to the initiator."""
    daemon = daemon_with_mocked_telegram
    db = daemon.db

    # Create Initiator session
    initiator = await db.create_session(
        computer_name="MozBook",
        tmux_session_name="initiator-tmux",
        last_input_origin="mcp",
        title="Initiator",
        project_path="/tmp",
    )

    # Create Worker session with initiator_session_id
    worker = await db.create_session(
        computer_name="MozBook",
        tmux_session_name="worker-tmux",
        last_input_origin="mcp",
        title="Worker",
        project_path="/tmp",
        initiator_session_id=initiator.session_id,
    )

    # Register listener (simulating what handlers do)
    from teleclaude.core.session_listeners import register_listener

    register_listener(
        target_session_id=worker.session_id,
        caller_session_id=initiator.session_id,
        caller_tmux_session=initiator.tmux_session_name,
    )

    # Mock deliver_listener_message to track calls
    with patch("teleclaude.core.tmux_delivery.deliver_listener_message", new_callable=AsyncMock) as mock_deliver:
        mock_deliver.return_value = True

        # Simulate Worker stopping
        from teleclaude.core.events import AgentEventContext, AgentHookEvents, build_agent_payload

        context = AgentEventContext(
            session_id=worker.session_id,
            event_type=AgentHookEvents.AGENT_STOP,
            data=build_agent_payload(AgentHookEvents.AGENT_STOP, {"session_id": "native-id"}),
        )

        await daemon.agent_coordinator.handle_stop(context)

        # Verify notification was delivered to initiator
        assert mock_deliver.called
        # Check arguments: session_id, tmux_session, message
        args, _kwargs = mock_deliver.call_args
        assert args[0] == initiator.session_id
        assert args[1] == initiator.tmux_session_name
        assert "[TeleClaude: Worker Stopped]" in args[2] or "Worker" in args[2]
