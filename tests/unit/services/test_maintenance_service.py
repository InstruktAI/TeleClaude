"""Characterization tests for teleclaude.services.maintenance_service."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.models import Session
from teleclaude.services.maintenance_service import COMPACTION_IDLE_THRESHOLD_S, MaintenanceService


def _make_service() -> MaintenanceService:
    client = SimpleNamespace(
        adapters={},
    )
    return MaintenanceService(
        client=client,
        output_poller=SimpleNamespace(),
        poller_watch_interval_s=1.0,
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
        session.origin_metadata = {"telegram": {"topic_id": topic_id}}
    return session


class _FakeUiAdapter:
    def __init__(self, cleaned: int) -> None:
        self.cleaned = cleaned

    async def cleanup_stale_resources(self) -> int:
        return self.cleaned


class TestMaintenanceService:
    @pytest.mark.unit
    async def test_poller_watch_schedules_polling_without_lane_provisioning(self) -> None:
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

        schedule_mock.assert_awaited_once()

    @pytest.mark.unit
    async def test_poller_watch_restores_missing_tmux_session_once(self) -> None:
        """Schedules ``_restore_tmux_session`` exactly once and clears bookkeeping.

        Lets the real ``_restore_tmux_session`` run so the ``_restoring_sessions``
        ``finally`` cleanup is exercised; the inner work short-circuits via the
        ``session_exists`` early-return guard.
        """
        session = _make_session("session-2", topic_id=123)
        service = _make_service()
        scheduled_tasks: list[asyncio.Task[Any]] = []
        original_create_task = asyncio.create_task

        def _capturing_create_task(coro: Any, **kwargs: Any) -> asyncio.Task[Any]:
            task = original_create_task(coro, **kwargs)
            scheduled_tasks.append(task)
            return task

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
            patch(
                "teleclaude.services.maintenance_service.tmux_bridge.session_exists",
                new=AsyncMock(return_value=True),
            ) as exists_mock,
            patch("teleclaude.services.maintenance_service.asyncio.create_task", side_effect=_capturing_create_task),
        ):
            await service._poller_watch_iteration()
            assert len(scheduled_tasks) == 1
            await scheduled_tasks[0]

        exists_mock.assert_awaited_once()
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
            last_activity=now - timedelta(days=10),
            closed_at=now - timedelta(days=10),
            lifecycle_status="closed",
        )
        # Open inactive sessions are NOT auto-closed
        open_inactive = _make_session("inactive", last_activity=now - timedelta(days=10))
        service = _make_service()

        with (
            patch(
                "teleclaude.services.maintenance_service.db.list_sessions",
                new=AsyncMock(return_value=[normalize_only, purge_closed, open_inactive]),
            ),
            patch("teleclaude.services.maintenance_service.db.update_session", new=AsyncMock()) as update_mock,
            patch("teleclaude.services.maintenance_service.session_cleanup.terminate_session", new=AsyncMock()) as term,
        ):
            await service._cleanup_inactive_sessions()

        update_mock.assert_awaited_once_with("normalize", lifecycle_status="closed")
        # Only the closed session past 7 days gets purged; open sessions are left alone
        assert term.await_count == 1
        assert term.await_args_list[0].kwargs["reason"] == "closed_expired"
        assert term.await_args_list[0].kwargs["kill_tmux"] is False
        assert term.await_args_list[0].kwargs["delete_db"] is True

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
