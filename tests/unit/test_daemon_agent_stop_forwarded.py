"""Unit tests for forwarded agent stop handling."""

from unittest.mock import AsyncMock, MagicMock

import pytest


@pytest.mark.asyncio
async def test_process_agent_stop_forwarded_skips_summary(monkeypatch):
    """Forwarded stop events should skip summarization and just notify listeners."""
    import teleclaude.daemon as daemon_module
    from teleclaude.core.events import AgentEventContext, AgentHookEvents, AgentStopPayload
    from teleclaude.daemon import TeleClaudeDaemon

    daemon = TeleClaudeDaemon.__new__(TeleClaudeDaemon)
    daemon._last_stop_time = {}
    daemon._stop_debounce_seconds = 0.0
    daemon.agent_coordinator = MagicMock()
    calls = []

    async def record_handle_stop(ctx):
        calls.append(ctx)

    daemon.agent_coordinator.handle_stop = record_handle_stop

    monkeypatch.setattr(
        daemon_module,
        "summarize",
        AsyncMock(side_effect=AssertionError("summarize should not be called")),
    )

    mock_db = MagicMock()
    mock_db.get_ux_state = AsyncMock(side_effect=AssertionError("db.get_ux_state should not be called"))
    monkeypatch.setattr(daemon_module, "db", mock_db)

    payload = AgentStopPayload(
        session_id="sess-123",
        source_computer="RemotePC",
    )
    context = AgentEventContext(
        session_id="sess-123",
        event_type=AgentHookEvents.AGENT_STOP,
        data=payload,
    )

    await daemon._process_agent_stop(context)

    assert calls == [context]
