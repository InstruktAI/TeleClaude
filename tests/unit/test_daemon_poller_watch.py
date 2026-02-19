"""Unit tests for TeleClaudeDaemon poller watch loop."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, Mock, patch

import pytest

from teleclaude.core.origins import InputOrigin

os.environ.setdefault("TELECLAUDE_CONFIG_PATH", "tests/integration/config.yml")

from teleclaude.core.models import Session, SessionAdapterMetadata
from teleclaude.services.maintenance_service import MaintenanceService


@pytest.mark.asyncio
async def test_poller_watch_ensures_ui_channels_for_all_origins():
    """Poller watch should create UI channels for sessions without them, regardless of origin."""
    service = MaintenanceService(client=Mock(), output_poller=Mock(), poller_watch_interval_s=1.0)
    service._client.ensure_ui_channels = AsyncMock()

    session = Session(
        session_id="sess-123",
        computer_name="test",
        tmux_session_name="tc_sess",
        last_input_origin=InputOrigin.API.value,
        title="Test Session",
        adapter_metadata=SessionAdapterMetadata(),
        project_path="/tmp",
    )

    with (
        patch("teleclaude.services.maintenance_service.db.get_active_sessions", new=AsyncMock(return_value=[session])),
        patch(
            "teleclaude.services.maintenance_service.tmux_bridge.list_tmux_sessions",
            new=AsyncMock(return_value=["tc_sess"]),
        ),
        patch("teleclaude.services.maintenance_service.tmux_bridge.is_pane_dead", new=AsyncMock(return_value=False)),
        patch(
            "teleclaude.services.maintenance_service.polling_coordinator.is_polling", new=AsyncMock(return_value=False)
        ),
        patch("teleclaude.services.maintenance_service.polling_coordinator.schedule_polling", new=AsyncMock()),
        patch(
            "teleclaude.services.maintenance_service.get_display_title_for_session",
            new=AsyncMock(return_value="Test Session"),
        ),
    ):
        await service._poller_watch_iteration()

    service._client.ensure_ui_channels.assert_called_once()


@pytest.mark.asyncio
async def test_poller_watch_recreates_missing_tmux_session():
    """Ensure poller watch recreates missing tmux session before polling."""
    service = MaintenanceService(client=Mock(), output_poller=Mock(), poller_watch_interval_s=1.0)

    session = Session(
        session_id="sess-456",
        computer_name="test",
        tmux_session_name="tc_sess_456",
        last_input_origin=InputOrigin.API.value,
        title="Test Session 2",
        adapter_metadata=SessionAdapterMetadata(),
        active_agent="claude",
        project_path="/tmp",
    )

    captured: list[Session] = []

    async def record_ensure(session_arg: Session) -> bool:
        captured.append(session_arg)
        return True

    service.ensure_tmux_session = record_ensure

    service._client.ensure_ui_channels = AsyncMock()

    with (
        patch("teleclaude.services.maintenance_service.db.get_active_sessions", new=AsyncMock(return_value=[session])),
        patch("teleclaude.services.maintenance_service.tmux_bridge.list_tmux_sessions", new=AsyncMock(return_value=[])),
        patch("teleclaude.services.maintenance_service.tmux_bridge.is_pane_dead", new=AsyncMock(return_value=False)),
        patch(
            "teleclaude.services.maintenance_service.polling_coordinator.is_polling", new=AsyncMock(return_value=False)
        ),
        patch("teleclaude.services.maintenance_service.polling_coordinator.schedule_polling", new=AsyncMock()),
        patch(
            "teleclaude.services.maintenance_service.get_display_title_for_session",
            new=AsyncMock(return_value="Test Session 2"),
        ),
    ):
        await service._poller_watch_iteration()

    assert captured == [session]


@pytest.mark.asyncio
async def test_ensure_tmux_session_restores_agent_on_recreate():
    """Recreated tmux session should trigger agent restore when metadata available."""
    service = MaintenanceService(client=Mock(), output_poller=Mock(), poller_watch_interval_s=1.0)
    service._build_tmux_env_vars = AsyncMock(return_value={})

    session = Session(
        session_id="sess-789",
        computer_name="test",
        tmux_session_name="tc_sess_789",
        last_input_origin=InputOrigin.API.value,
        title="Restore Agent",
        adapter_metadata=SessionAdapterMetadata(),
        active_agent="gemini",
        native_session_id="native-123",
        thinking_mode="med",
    )

    sent: list[str] = []

    async def record_send_keys(*_args: object, **kwargs: object) -> bool:
        text = kwargs.get("text")
        if isinstance(text, str):
            sent.append(text)
        return True

    with (
        patch("teleclaude.services.maintenance_service.tmux_bridge.session_exists", new=AsyncMock(return_value=False)),
        patch(
            "teleclaude.services.maintenance_service.tmux_bridge.ensure_tmux_session", new=AsyncMock(return_value=True)
        ),
        patch("teleclaude.services.maintenance_service.tmux_bridge.send_keys", new=record_send_keys),
        patch("teleclaude.services.maintenance_service.resolve_working_dir", new=Mock(return_value="/tmp")),
        patch("teleclaude.services.maintenance_service.get_agent_command", new=Mock(return_value="agent resume cmd")),
    ):
        created = await service.ensure_tmux_session(session)

    assert created is True
    assert len(sent) == 1
