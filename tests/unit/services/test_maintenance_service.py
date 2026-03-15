"""Characterization tests for teleclaude.services.maintenance_service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.models import Session
from teleclaude.core.models._adapter import TelegramAdapterMetadata
from teleclaude.services.maintenance_service import COMPACTION_IDLE_THRESHOLD_S, MaintenanceService


def _make_service() -> MaintenanceService:
    client = SimpleNamespace(
        adapters={},
        ensure_ui_channels=AsyncMock(),
    )
    return MaintenanceService(
        client=client,
        output_poller=SimpleNamespace(),
        poller_watch_interval_s=1.0,
        codex_transcript_watch_interval_s=1.0,
    )


def _make_session(
    session_id: str,
    *,
    active_agent: str = "claude",
    native_session_id: str | None = None,
    native_log_file: str | None = None,
    last_activity: datetime | None = None,
    closed_at: datetime | None = None,
    lifecycle_status: str = "active",
    human_role: str | None = None,
    last_memory_extraction_at: datetime | None = None,
    topic_id: int | None = None,
    project_path: str | None = "/tmp/project",
) -> Session:
    session = Session(
        session_id=session_id,
        computer_name="local",
        tmux_session_name=f"tmux-{session_id}",
        title=f"Session {session_id}",
        active_agent=active_agent,
        native_session_id=native_session_id,
        native_log_file=native_log_file,
        last_activity=last_activity,
        closed_at=closed_at,
        lifecycle_status=lifecycle_status,
        human_role=human_role,
        last_memory_extraction_at=last_memory_extraction_at,
        project_path=project_path,
    )
    if topic_id is not None:
        session.adapter_metadata.get_ui()._telegram = TelegramAdapterMetadata(topic_id=topic_id)
    return session


class _FakeUiAdapter:
    def __init__(self, cleaned: int) -> None:
        self.cleaned = cleaned

    async def cleanup_stale_resources(self) -> int:
        return self.cleaned


class TestMaintenanceService:
    @pytest.mark.unit
    async def test_codex_transcript_watch_binds_missing_logs(self, tmp_path: Path) -> None:
        existing_log = tmp_path / "existing.log"
        existing_log.write_text("existing", encoding="utf-8")
        target = _make_session("target", active_agent="codex", native_session_id="native-1")
        skipped = _make_session(
            "skipped",
            active_agent="codex",
            native_session_id="native-2",
            native_log_file=str(existing_log),
        )
        service = _make_service()

        with (
            patch(
                "teleclaude.services.maintenance_service.db.list_sessions",
                new=AsyncMock(return_value=[target, skipped]),
            ),
            patch(
                "teleclaude.services.maintenance_service.discover_codex_transcript_path",
                side_effect=["/tmp/discovered.log", None],
            ),
            patch("teleclaude.services.maintenance_service.db.update_session", new=AsyncMock()) as update_mock,
        ):
            await service._codex_transcript_watch_iteration()

        update_mock.assert_awaited_once_with("target", native_log_file="/tmp/discovered.log")

    @pytest.mark.unit
    async def test_poller_watch_ensures_channels_and_schedules_polling(self) -> None:
        session = _make_session("session-1", topic_id=None)
        service = _make_service()

        with (
            patch(
                "teleclaude.services.maintenance_service.db.get_active_sessions",
                new=AsyncMock(return_value=[session]),
            ),
            patch(
                "teleclaude.services.maintenance_service.polling_coordinator.is_polling",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "teleclaude.services.maintenance_service.tmux_bridge.list_tmux_sessions",
                new=AsyncMock(return_value=[session.tmux_session_name]),
            ),
            patch(
                "teleclaude.services.maintenance_service.tmux_bridge.is_pane_dead",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "teleclaude.services.maintenance_service.polling_coordinator.schedule_polling",
                new=AsyncMock(),
            ) as schedule_mock,
        ):
            await service._poller_watch_iteration()

        service._client.ensure_ui_channels.assert_awaited_once_with(session)
        schedule_mock.assert_awaited_once()

    @pytest.mark.unit
    async def test_poller_watch_restores_missing_tmux_session_once(self) -> None:
        session = _make_session("session-2", topic_id=123)
        service = _make_service()

        with (
            patch(
                "teleclaude.services.maintenance_service.db.get_active_sessions",
                new=AsyncMock(return_value=[session]),
            ),
            patch(
                "teleclaude.services.maintenance_service.polling_coordinator.is_polling",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "teleclaude.services.maintenance_service.tmux_bridge.list_tmux_sessions",
                new=AsyncMock(return_value=[]),
            ),
            patch.object(service, "ensure_tmux_session", new=AsyncMock(return_value=True)) as ensure_mock,
        ):
            await service._poller_watch_iteration()
            await asyncio.sleep(0)

        ensure_mock.assert_awaited_once_with(session)
        assert service._restoring_sessions == set()

    @pytest.mark.unit
    async def test_cleanup_inactive_sessions_normalizes_and_terminates_old_entries(self) -> None:
        now = datetime.now(UTC)
        normalize_only = _make_session(
            "normalize",
            last_activity=now - timedelta(hours=1),
            closed_at=now - timedelta(hours=1),
            lifecycle_status="active",
        )
        purge_closed = _make_session(
            "purge",
            last_activity=now - timedelta(hours=80),
            closed_at=now - timedelta(hours=80),
            lifecycle_status="closed",
        )
        purge_inactive = _make_session("inactive", last_activity=now - timedelta(hours=80))
        service = _make_service()

        with (
            patch(
                "teleclaude.services.maintenance_service.db.list_sessions",
                new=AsyncMock(return_value=[normalize_only, purge_closed, purge_inactive]),
            ),
            patch("teleclaude.services.maintenance_service.db.update_session", new=AsyncMock()) as update_mock,
            patch("teleclaude.services.maintenance_service.session_cleanup.terminate_session", new=AsyncMock()) as term,
        ):
            await service._cleanup_inactive_sessions()

        update_mock.assert_awaited_once_with("normalize", lifecycle_status="closed")
        assert term.await_count == 2
        assert term.await_args_list[0].kwargs["reason"] == "closed_expired"
        assert term.await_args_list[0].kwargs["kill_tmux"] is False
        assert term.await_args_list[0].kwargs["delete_db"] is True
        assert term.await_args_list[1].kwargs["reason"] == "inactive_72h"

    @pytest.mark.unit
    async def test_check_idle_compaction_marks_only_eligible_sessions(self) -> None:
        now = datetime.now(UTC)
        eligible = _make_session(
            "eligible",
            last_activity=now - timedelta(seconds=COMPACTION_IDLE_THRESHOLD_S + 5),
            human_role="customer",
        )
        recent = _make_session(
            "recent",
            last_activity=now - timedelta(seconds=COMPACTION_IDLE_THRESHOLD_S - 5),
            human_role="customer",
        )
        already_marked = _make_session(
            "already",
            last_activity=now - timedelta(seconds=COMPACTION_IDLE_THRESHOLD_S + 5),
            human_role="customer",
            last_memory_extraction_at=now - timedelta(seconds=10),
        )
        service = _make_service()

        with (
            patch(
                "teleclaude.services.maintenance_service.db.get_active_sessions",
                new=AsyncMock(return_value=[eligible, recent, already_marked]),
            ),
            patch("teleclaude.services.maintenance_service.db.update_session", new=AsyncMock()) as update_mock,
        ):
            await service._check_idle_compaction()

        update_mock.assert_awaited_once()
        assert update_mock.await_args.args[0] == "eligible"
        assert "last_memory_extraction_at" in update_mock.await_args.kwargs

    @pytest.mark.unit
    async def test_cleanup_adapter_resources_only_runs_ui_adapters(self) -> None:
        service = _make_service()
        service._client.adapters = cast(Any, {"telegram": _FakeUiAdapter(2), "other": object()})

        with patch("teleclaude.services.maintenance_service.UiAdapter", _FakeUiAdapter):
            await service._cleanup_adapter_resources()

    @pytest.mark.unit
    async def test_ensure_tmux_session_recreates_and_restores_agent(self, tmp_path: Path) -> None:
        session = _make_session(
            "restore",
            native_session_id="native-9",
            project_path=str(tmp_path),
        )
        service = _make_service()

        with (
            patch.object(service, "_build_tmux_env_vars", new=AsyncMock(return_value={"OPENAI_VOICE": "nova"})),
            patch(
                "teleclaude.services.maintenance_service.tmux_bridge.session_exists",
                new=AsyncMock(return_value=False),
            ),
            patch(
                "teleclaude.services.maintenance_service.tmux_bridge.ensure_tmux_session",
                new=AsyncMock(return_value=True),
            ),
            patch(
                "teleclaude.services.maintenance_service.get_agent_command",
                return_value="echo hello && exit",
            ),
            patch(
                "teleclaude.services.maintenance_service.tmux_bridge.send_keys",
                new=AsyncMock(return_value=True),
            ) as send_keys_mock,
        ):
            created = await service.ensure_tmux_session(session)

        assert created is True
        assert send_keys_mock.await_args.kwargs["session_name"] == session.tmux_session_name
        assert send_keys_mock.await_args.kwargs["text"].startswith("\u001b[200~")
