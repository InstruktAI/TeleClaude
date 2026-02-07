"""Unit tests for forwarded agent stop handling."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_process_agent_stop_forwarded_skips_forward():
    """Forwarded stop events should not re-forward to initiator."""
    from teleclaude.core.agent_coordinator import AgentCoordinator
    from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload

    coordinator = AgentCoordinator(
        client=MagicMock(),
        tts_manager=MagicMock(),
        headless_snapshot_service=MagicMock(),
    )
    coordinator._notify_session_listener = AsyncMock()
    coordinator._forward_stop_to_initiator = AsyncMock()
    coordinator._extract_user_input_for_codex = AsyncMock()
    coordinator.tts_manager.speak = AsyncMock()

    payload = AgentStopPayload(
        session_id="sess-123",
        source_computer="RemotePC",
        raw={"agent_name": "claude"},
        transcript_path="/tmp/native.jsonl",
    )
    context = AgentEventContext(
        session_id="sess-123",
        event_type=AgentHookEvents.AGENT_STOP,
        data=payload,
    )

    session = MagicMock()
    session.active_agent = "claude"
    session.native_log_file = "/tmp/native.jsonl"

    with (
        patch("teleclaude.core.agent_coordinator.db.get_session", new=AsyncMock(return_value=session)),
        patch("teleclaude.core.agent_coordinator.db.update_session", new=AsyncMock()),
        patch("teleclaude.core.agent_coordinator.extract_last_agent_message", return_value="raw output"),
        patch(
            "teleclaude.core.agent_coordinator.summarize_agent_output", new_callable=AsyncMock, return_value=("t", "s")
        ),
        patch("teleclaude.core.agent_coordinator.config") as mock_config,
    ):
        mock_config.computer.name = "LocalPC"
        await coordinator.handle_agent_stop(context)

    coordinator._forward_stop_to_initiator.assert_not_awaited()
