"""Unit tests for TeleClaudeDaemon poller watch loop."""

from __future__ import annotations

import os
from pathlib import Path
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
    ):
        await service._poller_watch_iteration()

    service._client.ensure_ui_channels.assert_called_once()


@pytest.mark.asyncio
async def test_poller_watch_skips_missing_tmux_session_without_recovery():
    """Poller watch should not recreate missing tmux sessions in the background."""
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

    service._client.ensure_ui_channels = AsyncMock()

    with (
        patch("teleclaude.services.maintenance_service.db.get_active_sessions", new=AsyncMock(return_value=[session])),
        patch("teleclaude.services.maintenance_service.tmux_bridge.list_tmux_sessions", new=AsyncMock(return_value=[])),
        patch("teleclaude.services.maintenance_service.tmux_bridge.is_pane_dead", new=AsyncMock(return_value=False)),
        patch(
            "teleclaude.services.maintenance_service.polling_coordinator.is_polling", new=AsyncMock(return_value=False)
        ) as mock_is_polling,
        patch("teleclaude.services.maintenance_service.polling_coordinator.schedule_polling", new=AsyncMock()) as mock_schedule,
    ):
        await service._poller_watch_iteration()

    mock_is_polling.assert_awaited_once_with(session.session_id)
    mock_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_poller_watch_skips_dead_tmux_pane_without_recovery():
    """Poller watch should not recreate tmux when the pane is dead."""
    service = MaintenanceService(client=Mock(), output_poller=Mock(), poller_watch_interval_s=1.0)

    session = Session(
        session_id="sess-dead-pane",
        computer_name="test",
        tmux_session_name="tc_dead_pane",
        last_input_origin=InputOrigin.API.value,
        title="Dead Pane",
        adapter_metadata=SessionAdapterMetadata(),
        project_path="/tmp",
    )

    with (
        patch("teleclaude.services.maintenance_service.db.get_active_sessions", new=AsyncMock(return_value=[session])),
        patch(
            "teleclaude.services.maintenance_service.tmux_bridge.list_tmux_sessions",
            new=AsyncMock(return_value=[session.tmux_session_name]),
        ),
        patch("teleclaude.services.maintenance_service.tmux_bridge.is_pane_dead", new=AsyncMock(return_value=True)),
        patch(
            "teleclaude.services.maintenance_service.polling_coordinator.is_polling", new=AsyncMock(return_value=False)
        ),
        patch("teleclaude.services.maintenance_service.polling_coordinator.schedule_polling", new=AsyncMock()) as mock_schedule,
    ):
        await service._poller_watch_iteration()

    mock_schedule.assert_not_awaited()


@pytest.mark.asyncio
async def test_codex_transcript_watch_binds_missing_transcripts(tmp_path: Path):
    """Codex transcript watcher should bind missing native_log_file from native_session_id."""
    service = MaintenanceService(client=Mock(), output_poller=Mock(), poller_watch_interval_s=1.0)

    existing_log = tmp_path / "existing.jsonl"
    existing_log.write_text("{}", encoding="utf-8")

    sessions = [
        Session(
            session_id="codex-bind-1",
            computer_name="test",
            tmux_session_name="tc_bind_1",
            last_input_origin=InputOrigin.API.value,
            title="Codex Missing Transcript",
            active_agent="codex",
            native_session_id="native-bind-1",
            native_log_file=None,
        ),
        Session(
            session_id="codex-bind-2",
            computer_name="test",
            tmux_session_name="",
            last_input_origin=InputOrigin.TERMINAL.value,
            title="Codex Headless Missing Transcript",
            active_agent="codex",
            lifecycle_status="headless",
            native_session_id="native-bind-2",
            native_log_file=str(tmp_path / "missing-old.jsonl"),
        ),
        Session(
            session_id="codex-bind-3",
            computer_name="test",
            tmux_session_name="tc_bind_3",
            last_input_origin=InputOrigin.API.value,
            title="Codex Existing Transcript",
            active_agent="codex",
            native_session_id="native-bind-3",
            native_log_file=str(existing_log),
        ),
        Session(
            session_id="claude-bind-1",
            computer_name="test",
            tmux_session_name="tc_bind_4",
            last_input_origin=InputOrigin.API.value,
            title="Claude Session",
            active_agent="claude",
            native_session_id="native-claude",
            native_log_file=None,
        ),
    ]

    discovered = {
        "native-bind-1": str(tmp_path / "rollout-1-native-bind-1.jsonl"),
        "native-bind-2": str(tmp_path / "rollout-2-native-bind-2.jsonl"),
    }
    updates: list[tuple[str, str]] = []

    async def record_update(session_id: str, **kwargs: object) -> None:
        native_log_file = kwargs.get("native_log_file")
        updates.append((session_id, str(native_log_file) if native_log_file else ""))

    with (
        patch(
            "teleclaude.services.maintenance_service.db.list_sessions",
            new=AsyncMock(return_value=sessions),
        ) as mock_list_sessions,
        patch(
            "teleclaude.services.maintenance_service.db.update_session",
            new=AsyncMock(side_effect=record_update),
        ),
        patch(
            "teleclaude.services.maintenance_service.discover_codex_transcript_path",
            side_effect=lambda native_id: discovered.get(native_id),
        ),
    ):
        await service._codex_transcript_watch_iteration()

    mock_list_sessions.assert_awaited_once_with(include_headless=True)
    assert ("codex-bind-1", discovered["native-bind-1"]) in updates
    assert ("codex-bind-2", discovered["native-bind-2"]) in updates
    assert all(session_id != "codex-bind-3" for session_id, _ in updates)
    assert all(session_id != "claude-bind-1" for session_id, _ in updates)
