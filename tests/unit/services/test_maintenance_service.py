"""Characterization tests for teleclaude.services.maintenance_service."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from teleclaude.core.models import Session
from teleclaude.services import maintenance_service
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

    @pytest.mark.unit
    async def test_periodic_cleanup_runs_session_map_pruning(self) -> None:
        service = _make_service()
        to_thread = AsyncMock(return_value=1)
        cleanup_inbound = AsyncMock()
        cleanup_orphan_inbound = AsyncMock()
        cleanup_terminal_operations = AsyncMock()
        cleanup_webhook_outbox = AsyncMock()
        cleanup_hook_outbox = AsyncMock()
        cleanup_orphan_session_tokens = AsyncMock()
        cleanup_orphan_session_listeners = AsyncMock()
        compact_runtime_databases_if_needed = AsyncMock()
        event_db = SimpleNamespace(cleanup_runtime_events=AsyncMock())

        with (
            patch(
                "teleclaude.services.maintenance_service.asyncio.sleep",
                new=AsyncMock(side_effect=asyncio.CancelledError),
            ),
            patch("teleclaude.services.maintenance_service.asyncio.to_thread", new=to_thread),
            patch(
                "teleclaude.services.maintenance_service.session_cleanup.emit_recently_closed_session_events",
                new=AsyncMock(),
            ),
            patch(
                "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_tmux_sessions",
                new=AsyncMock(),
            ),
            patch(
                "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_workspaces",
                new=AsyncMock(),
            ),
            patch(
                "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_session_tmpdirs",
                new=AsyncMock(),
            ),
            patch("teleclaude.services.maintenance_service.db.cleanup_stale_voice_assignments", new=AsyncMock()),
            patch("teleclaude.services.maintenance_service.db.cleanup_inbound", new=cleanup_inbound),
            patch("teleclaude.services.maintenance_service.db.cleanup_orphan_inbound", new=cleanup_orphan_inbound),
            patch(
                "teleclaude.services.maintenance_service.db.cleanup_terminal_operations",
                new=cleanup_terminal_operations,
            ),
            patch("teleclaude.services.maintenance_service.db.cleanup_webhook_outbox", new=cleanup_webhook_outbox),
            patch("teleclaude.services.maintenance_service.db.cleanup_hook_outbox", new=cleanup_hook_outbox),
            patch(
                "teleclaude.services.maintenance_service.db.cleanup_orphan_session_tokens",
                new=cleanup_orphan_session_tokens,
            ),
            patch(
                "teleclaude.services.maintenance_service.db.cleanup_orphan_session_listeners",
                new=cleanup_orphan_session_listeners,
            ),
            patch(
                "teleclaude.services.maintenance_service.db.compact_runtime_databases_if_needed",
                new=compact_runtime_databases_if_needed,
            ),
            patch("teleclaude.services.maintenance_service.get_operations_service") as operations_factory,
            patch("teleclaude.services.maintenance_service.get_event_db", new=AsyncMock(return_value=event_db)),
            patch.object(service, "_cleanup_inactive_sessions", new=AsyncMock()),
            patch.object(service, "_check_idle_compaction", new=AsyncMock()),
            patch.object(service, "_cleanup_adapter_resources", new=AsyncMock()),
        ):
            operations_factory.return_value.expire_stale_operations = AsyncMock()

            await service.periodic_cleanup()

        to_thread.assert_awaited_once()
        assert to_thread.await_args.args == (maintenance_service.prune_session_map,)
        cleanup_inbound.assert_awaited_once()
        cleanup_orphan_inbound.assert_awaited_once()
        cleanup_terminal_operations.assert_awaited_once()
        cleanup_webhook_outbox.assert_awaited_once()
        cleanup_hook_outbox.assert_awaited_once()
        cleanup_orphan_session_tokens.assert_awaited_once()
        cleanup_orphan_session_listeners.assert_awaited_once()
        event_db.cleanup_runtime_events.assert_awaited_once()
        compact_runtime_databases_if_needed.assert_awaited_once()

    @pytest.mark.unit
    async def test_periodic_cleanup_surfaces_runtime_maintenance_failures_as_warnings(self) -> None:
        service = _make_service()
        event_db = SimpleNamespace(cleanup_runtime_events=AsyncMock(side_effect=RuntimeError("event cleanup failed")))

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "teleclaude.services.maintenance_service.asyncio.sleep",
                    new=AsyncMock(side_effect=asyncio.CancelledError),
                )
            )
            stack.enter_context(patch("teleclaude.services.maintenance_service.asyncio.to_thread", new=AsyncMock()))
            stack.enter_context(
                patch(
                    "teleclaude.services.maintenance_service.session_cleanup.emit_recently_closed_session_events",
                    new=AsyncMock(),
                )
            )
            stack.enter_context(
                patch(
                    "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_tmux_sessions",
                    new=AsyncMock(),
                )
            )
            stack.enter_context(
                patch(
                    "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_workspaces",
                    new=AsyncMock(),
                )
            )
            stack.enter_context(
                patch(
                    "teleclaude.services.maintenance_service.session_cleanup.cleanup_orphan_session_tmpdirs",
                    new=AsyncMock(),
                )
            )
            for target in (
                "db.cleanup_stale_voice_assignments",
                "db.cleanup_inbound",
                "db.cleanup_orphan_inbound",
                "db.cleanup_terminal_operations",
                "db.cleanup_webhook_outbox",
                "db.cleanup_hook_outbox",
                "db.cleanup_orphan_session_tokens",
                "db.cleanup_orphan_session_listeners",
            ):
                stack.enter_context(patch(f"teleclaude.services.maintenance_service.{target}", new=AsyncMock()))
            stack.enter_context(
                patch(
                    "teleclaude.services.maintenance_service.db.compact_runtime_databases_if_needed",
                    new=AsyncMock(side_effect=RuntimeError("compaction failed")),
                )
            )
            operations_factory = stack.enter_context(
                patch("teleclaude.services.maintenance_service.get_operations_service")
            )
            stack.enter_context(
                patch("teleclaude.services.maintenance_service.get_event_db", new=AsyncMock(return_value=event_db))
            )
            warning_mock = stack.enter_context(patch("teleclaude.services.maintenance_service.logger.warning"))
            debug_mock = stack.enter_context(patch("teleclaude.services.maintenance_service.logger.debug"))
            stack.enter_context(patch.object(service, "_cleanup_inactive_sessions", new=AsyncMock()))
            stack.enter_context(patch.object(service, "_check_idle_compaction", new=AsyncMock()))
            stack.enter_context(patch.object(service, "_cleanup_adapter_resources", new=AsyncMock()))
            operations_factory.return_value.expire_stale_operations = AsyncMock()

            await service.periodic_cleanup()

        assert warning_mock.call_count == 2
        debug_mock.assert_not_called()
