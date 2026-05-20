"""Characterization tests for teleclaude.services.maintenance_service."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import frontmatter
import pytest

from teleclaude.config import TrustedDir
from teleclaude.constants import RoadmapStatus
from teleclaude.core.models import Session
from teleclaude.core.todos_db import TodosDb, _instances
from teleclaude.core.todos_db._models import TodoRoadmap
from teleclaude.docs_reconcile import SnippetWriteResult
from teleclaude.git import Repo
from teleclaude.services import maintenance_service
from teleclaude.services.maintenance_service import COMPACTION_IDLE_THRESHOLD_S, MaintenanceService

_PURGED_SLUG = "purged-slug"
_LIVE_SLUG = "live-slug"
_SNIPPET_RELPATH = "docs/project/spec/snippet.md"
_ROW_PURGE = "row-purge"
_ROW_LIVE = "row-live"
_ORDER_SET = "set"
_ORDER_WRITE = "write"
_ORDER_CLEAR = "clear"
_ORDER_PURGE = "purge"


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


# ---------------------------------------------------------------------------
# Removed-todo retention sweep
# ---------------------------------------------------------------------------


async def _seed_project_with_removed_rows(
    tmp_path: Path,
    *,
    rows: list[tuple[str, str, str, datetime | None]],
) -> Path:
    """Create a project layout with a populated todos.db.

    Each `rows` tuple is (id, slug, status, removed_at). When status='removed'
    and removed_at is provided, the row gets a real tombstone; when removed_at
    is None for status='removed', it simulates a legacy partial row.
    """
    project = tmp_path / "project"
    (project / ".teleclaude").mkdir(parents=True)
    db = TodosDb(str(project / ".teleclaude" / "todos.db"))
    await db.initialize()
    try:
        with db._sync_session() as session:
            for idx, (row_id, slug, status, removed_at) in enumerate(rows):
                session.add(
                    TodoRoadmap(
                        id=row_id,
                        slug=slug,
                        position=idx,
                        status=status,
                        removed_at=removed_at.isoformat() if removed_at else None,
                        created_at="2026-04-01T00:00:00+00:00",
                        updated_at="2026-04-01T00:00:00+00:00",
                    )
                )
            session.commit()
    finally:
        await db.close()
    # Drop the cached instance so the maintenance service opens a fresh one.
    _instances.pop(str(project / ".teleclaude" / "todos.db"), None)
    return project


def _patch_trusted_dirs(monkeypatch: pytest.MonkeyPatch, paths: list[Path]) -> None:
    dirs = [TrustedDir(name=f"d{i}", desc="", path=str(p)) for i, p in enumerate(paths)]
    monkeypatch.setattr(
        "teleclaude.services.maintenance_service.config.computer.get_all_trusted_dirs",
        lambda: dirs,
    )


def _write_purge_snippet(project: Path, *, delivered_by: list[str]) -> Path:
    snippet_path = project / _SNIPPET_RELPATH
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            "id: project/spec/snippet\n"
            "type: spec\n"
            "scope: project\n"
            "description: Snippet\n"
            "status: target\n"
            f"delivered_by: {delivered_by}\n"
            "---\n"
            "# Snippet\n\n"
            "## What it is\n"
            "A snippet.\n\n"
            "## Canonical fields\n"
            "Fields.\n"
        ),
        encoding="utf-8",
    )
    return snippet_path


def _snippet_deliverers(path: Path) -> list[str]:
    raw = frontmatter.load(path).metadata.get("delivered_by")
    assert isinstance(raw, list)
    return [str(item) for item in raw]


async def _set_removed_row_pending(project: Path, row_id: str, paths: list[str]) -> None:
    db = TodosDb(str(project / ".teleclaude" / "todos.db"))
    await db.initialize()
    try:
        await db.set_pending_purge_paths(row_id, paths)
    finally:
        await db.close()
    _instances.pop(str(project / ".teleclaude" / "todos.db"), None)


def _fake_git_for_success(path: str, *, pre_staged: set[str] | None = None) -> Callable[..., tuple[int, str, str]]:
    staged = set(pre_staged or set())

    def fake_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        _ = cwd, timeout
        if args == ["status", "--porcelain", "--", path]:
            return 0, "", ""
        if args == ["diff", "--cached", "--name-only"]:
            return 0, "\n".join(sorted(staged)) + ("\n" if staged else ""), ""
        if args == ["add", "--", path]:
            staged.add(path)
            return 0, "", ""
        if args[:3] == ["commit", "-m", f"chore(roadmap): purge {_PURGED_SLUG}; reconcile delivered_by in 1 snippets"]:
            staged.discard(path)
            return 0, "", ""
        if args == ["status", "--porcelain"]:
            return 0, "", ""
        return 1, "", f"unexpected git args: {args}"

    return fake_git


@pytest.mark.unit
async def test_cleanup_removed_todos_purges_only_rows_past_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    inside = now - (maintenance_service.RETENTION_WINDOW - timedelta(hours=1))
    outside = now - (maintenance_service.RETENTION_WINDOW + timedelta(hours=1))
    project = await _seed_project_with_removed_rows(
        tmp_path,
        rows=[
            ("row-keep", "kept-slug", "removed", inside),
            ("row-purge", "purged-slug", "removed", outside),
            ("row-live", "live-slug", "active", None),
        ],
    )
    _patch_trusted_dirs(monkeypatch, [project])

    service = _make_service()
    await service._cleanup_removed_todos()

    db = TodosDb(str(project / ".teleclaude" / "todos.db"))
    db.initialize_sync()
    try:
        conn = db._sync_conn()
        try:
            rows = {
                str(row[0]): str(row[1])
                for row in conn.execute("SELECT id, status FROM roadmap").fetchall()  # guard: raw-sql
            }
        finally:
            conn.close()
    finally:
        await db.close()
    assert rows == {"row-keep": "removed", "row-live": "active"}


@pytest.mark.unit
async def test_cleanup_removed_todos_cascades_to_state_artifacts_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FK ON DELETE CASCADE handles state/artifacts/versions; the purge runs
    strictly row-id-addressed and performs no slug-keyed work."""
    now = datetime.now(UTC)
    outside = now - (maintenance_service.RETENTION_WINDOW + timedelta(hours=1))
    project = tmp_path / "project"
    (project / ".teleclaude").mkdir(parents=True)
    db = TodosDb(str(project / ".teleclaude" / "todos.db"))
    await db.initialize()
    try:
        await db.add_to_roadmap("doomed")
        await db.write_state("doomed", {"kind": "todo", "lifecycle_phase": "prepared"})
        await db.write_artifact("doomed", "prd", "v1")
        await db.write_artifact("doomed", "prd", "v2")
        row_id = await db.resolve_id("doomed")
        assert row_id is not None
        with db._sync_session() as session:
            entry = session.get(TodoRoadmap, row_id)
            assert entry is not None
            entry.status = "removed"
            entry.removed_at = outside.isoformat()
            entry.prev_status = "active"
            session.add(entry)
            session.commit()
    finally:
        await db.close()
    _instances.pop(str(project / ".teleclaude" / "todos.db"), None)
    _patch_trusted_dirs(monkeypatch, [project])

    service = _make_service()
    with patch("teleclaude.services.maintenance_service.logger.info") as logger_info:
        await service._cleanup_removed_todos()

    conn = sqlite3.connect(str(project / ".teleclaude" / "todos.db"))
    try:
        roadmap_rows = conn.execute("SELECT COUNT(*) FROM roadmap").fetchone()[0]
        state_rows = conn.execute("SELECT COUNT(*) FROM todo_state").fetchone()[0]
        artifact_rows = conn.execute("SELECT COUNT(*) FROM todo_artifacts").fetchone()[0]
        version_rows = conn.execute("SELECT COUNT(*) FROM todo_artifact_versions").fetchone()[0]
    finally:
        conn.close()
    assert (roadmap_rows, state_rows, artifact_rows, version_rows) == (0, 0, 0, 0)
    purge_log = next(call for call in logger_info.call_args_list if "removed_age_seconds" in call.kwargs)
    assert purge_log.kwargs["removed_age_seconds"] >= maintenance_service.RETENTION_WINDOW.total_seconds()


@pytest.mark.unit
async def test_cleanup_removed_todos_purges_removed_row_while_preserving_same_slug_live_twin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A reused slug must keep its own roadmap_deps and resources intact when the
    sweep sees a tombstoned twin — proves zero slug-keyed operations at purge time."""
    now = datetime.now(UTC)
    outside = now - (maintenance_service.RETENTION_WINDOW + timedelta(hours=1))
    project = tmp_path / "project"
    (project / ".teleclaude").mkdir(parents=True)
    db = TodosDb(str(project / ".teleclaude" / "todos.db"))
    await db.initialize()
    try:
        # Removed twin past the retention window
        with db._sync_session() as session:
            session.add(
                TodoRoadmap(
                    id="row-removed",
                    slug="reused",
                    position=0,
                    status="removed",
                    removed_at=outside.isoformat(),
                    prev_status="active",
                    created_at="2026-04-01T00:00:00+00:00",
                    updated_at="2026-04-01T00:00:00+00:00",
                )
            )
            session.commit()
        # Live row with the same slug, plus an outgoing edge
        await db.add_to_roadmap("upstream")
        await db.add_to_roadmap("reused")
        await db.set_deps("reused", after=["upstream"])
    finally:
        await db.close()
    resource_sentinel = project / "workspace" / "reused" / "sentinel.txt"
    resource_sentinel.parent.mkdir(parents=True)
    resource_sentinel.write_text("live resource", encoding="utf-8")
    _instances.pop(str(project / ".teleclaude" / "todos.db"), None)
    _patch_trusted_dirs(monkeypatch, [project])
    cleanup = MagicMock(side_effect=AssertionError("purge must not run slug-keyed cleanup"))
    monkeypatch.setattr("teleclaude.core.todos_db._roadmap.cleanup_delivered_slug", cleanup, raising=False)

    service = _make_service()
    await service._cleanup_removed_todos()

    db2 = TodosDb(str(project / ".teleclaude" / "todos.db"))
    db2.initialize_sync()
    try:
        live_deps = await db2.get_deps("reused")
        conn = db2._sync_conn()
        try:
            statuses = {
                str(row[0]): str(row[1])
                for row in conn.execute("SELECT id, status FROM roadmap").fetchall()  # guard: raw-sql
            }
        finally:
            conn.close()
    finally:
        await db2.close()
    assert "row-removed" not in statuses
    assert live_deps == ["upstream"]  # live row's edges untouched
    assert resource_sentinel.exists()
    cleanup.assert_not_called()


@pytest.mark.unit
def test_paths_match_head_handles_files_with_trailing_newline(tmp_path: Path) -> None:
    Repo.init(tmp_path)
    repo = Repo(tmp_path)
    repo.git.config("user.email", "test@example.com")
    repo.git.config("user.name", "Test User")
    snippet_path = tmp_path / _SNIPPET_RELPATH
    snippet_path.parent.mkdir(parents=True)
    snippet_path.write_text("content with final newline\n", encoding="utf-8")
    repo.index.add([_SNIPPET_RELPATH])
    repo.index.commit("initial")

    assert maintenance_service._paths_match_head(tmp_path, [_SNIPPET_RELPATH]) is True


@pytest.mark.unit
async def test_cleanup_removed_todos_reconciles_snippets_before_purging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    outside = now - (maintenance_service.RETENTION_WINDOW + timedelta(hours=1))
    project = await _seed_project_with_removed_rows(
        tmp_path,
        rows=[
            (_ROW_PURGE, _PURGED_SLUG, RoadmapStatus.REMOVED, outside),
            (_ROW_LIVE, _LIVE_SLUG, RoadmapStatus.ACTIVE, None),
        ],
    )
    snippet_path = _write_purge_snippet(project, delivered_by=[_PURGED_SLUG, _LIVE_SLUG])
    _patch_trusted_dirs(monkeypatch, [project])
    git_calls: list[list[str]] = []
    success_git = _fake_git_for_success(_SNIPPET_RELPATH)

    def fake_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        git_calls.append(args)
        return success_git(args, cwd=cwd, timeout=timeout)

    order: list[str] = []
    original_set_pending = TodosDb.set_pending_purge_paths
    original_clear_pending = TodosDb.clear_pending_purge_paths
    original_purge_one = TodosDb.purge_one_removed
    original_write_plans = maintenance_service._write_snippet_plans  # pylint: disable=protected-access

    async def record_set_pending(self: TodosDb, row_id: str, paths: list[str]) -> None:
        order.append(_ORDER_SET)
        await original_set_pending(self, row_id, paths)

    async def record_clear_pending(self: TodosDb, row_id: str) -> None:
        order.append(_ORDER_CLEAR)
        await original_clear_pending(self, row_id)

    async def record_purge_one(self: TodosDb, row_id: str) -> Any:
        order.append(_ORDER_PURGE)
        return await original_purge_one(self, row_id)

    def record_write_plans(plans: list[SnippetWriteResult]) -> None:
        order.append(_ORDER_WRITE)
        original_write_plans(plans)

    monkeypatch.setattr("teleclaude.services.maintenance_service._run_git_cmd", fake_git)
    monkeypatch.setattr(TodosDb, "set_pending_purge_paths", record_set_pending)
    monkeypatch.setattr(TodosDb, "clear_pending_purge_paths", record_clear_pending)
    monkeypatch.setattr(TodosDb, "purge_one_removed", record_purge_one)
    monkeypatch.setattr("teleclaude.services.maintenance_service._write_snippet_plans", record_write_plans)

    service = _make_service()
    await service._cleanup_removed_todos()

    conn = sqlite3.connect(str(project / ".teleclaude" / "todos.db"))
    try:
        remaining_ids = {
            str(row[0])
            for row in conn.execute("SELECT id FROM roadmap").fetchall()  # guard: raw-sql
        }
    finally:
        conn.close()
    assert _ROW_PURGE not in remaining_ids
    assert _snippet_deliverers(snippet_path) == [_LIVE_SLUG]
    assert order == [_ORDER_SET, _ORDER_WRITE, _ORDER_CLEAR, _ORDER_PURGE]
    assert ["add", "--", _SNIPPET_RELPATH] in git_calls
    assert any(
        call[:3] == ["commit", "-m", f"chore(roadmap): purge {_PURGED_SLUG}; reconcile delivered_by in 1 snippets"]
        for call in git_calls
    )


@pytest.mark.unit
async def test_cleanup_removed_todos_skips_fresh_pass_when_candidate_path_is_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    outside = now - (maintenance_service.RETENTION_WINDOW + timedelta(hours=1))
    project = await _seed_project_with_removed_rows(
        tmp_path,
        rows=[
            (_ROW_PURGE, _PURGED_SLUG, RoadmapStatus.REMOVED, outside),
            (_ROW_LIVE, _LIVE_SLUG, RoadmapStatus.ACTIVE, None),
        ],
    )
    snippet_path = _write_purge_snippet(project, delivered_by=[_PURGED_SLUG, _LIVE_SLUG])
    before = snippet_path.read_text(encoding="utf-8")
    _patch_trusted_dirs(monkeypatch, [project])

    def fake_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        _ = cwd, timeout
        if args == ["status", "--porcelain", "--", _SNIPPET_RELPATH]:
            return 0, f" M {_SNIPPET_RELPATH}\n", ""
        return 1, "", f"unexpected git args: {args}"

    monkeypatch.setattr("teleclaude.services.maintenance_service._run_git_cmd", fake_git)
    logger_info = MagicMock()
    monkeypatch.setattr("teleclaude.services.maintenance_service.logger.info", logger_info)

    service = _make_service()
    await service._cleanup_removed_todos()

    conn = sqlite3.connect(str(project / ".teleclaude" / "todos.db"))
    try:
        row = conn.execute(
            f"SELECT pending_purge_paths FROM roadmap WHERE id = '{_ROW_PURGE}'"  # guard: raw-sql
        ).fetchone()
    finally:
        conn.close()
    assert row == (None,)
    assert snippet_path.read_text(encoding="utf-8") == before
    assert any(
        call.kwargs.get("reason") == maintenance_service.PURGE_REASON_FOREIGN_EDIT_ON_FRESH_PASS
        for call in logger_info.call_args_list
    )


@pytest.mark.unit
async def test_cleanup_removed_todos_retry_match_head_skips_add_commit_and_finalizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    outside = now - (maintenance_service.RETENTION_WINDOW + timedelta(hours=1))
    project = await _seed_project_with_removed_rows(
        tmp_path,
        rows=[(_ROW_PURGE, _PURGED_SLUG, RoadmapStatus.REMOVED, outside)],
    )
    _write_purge_snippet(project, delivered_by=[_LIVE_SLUG])
    await _set_removed_row_pending(project, _ROW_PURGE, [_SNIPPET_RELPATH])
    _patch_trusted_dirs(monkeypatch, [project])
    git_calls: list[list[str]] = []

    def fake_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        _ = cwd, timeout
        git_calls.append(args)
        if args == ["diff", "--quiet", "HEAD", "--", _SNIPPET_RELPATH]:
            return 0, "", ""
        if args == ["diff", "--cached", "--name-only"] or args == ["status", "--porcelain"]:
            return 0, "", ""
        return 1, "", f"unexpected git args: {args}"

    monkeypatch.setattr("teleclaude.services.maintenance_service._run_git_cmd", fake_git)

    service = _make_service()
    await service._cleanup_removed_todos()

    conn = sqlite3.connect(str(project / ".teleclaude" / "todos.db"))
    try:
        row = conn.execute(f"SELECT id FROM roadmap WHERE id = '{_ROW_PURGE}'").fetchone()  # guard: raw-sql
    finally:
        conn.close()
    assert row is None
    assert not any(call and call[0] == "add" for call in git_calls)
    assert not any(call and call[0] == "commit" for call in git_calls)


@pytest.mark.unit
async def test_cleanup_removed_todos_commit_failure_retains_pending_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    outside = now - (maintenance_service.RETENTION_WINDOW + timedelta(hours=1))
    project = await _seed_project_with_removed_rows(
        tmp_path,
        rows=[
            (_ROW_PURGE, _PURGED_SLUG, RoadmapStatus.REMOVED, outside),
            (_ROW_LIVE, _LIVE_SLUG, RoadmapStatus.ACTIVE, None),
        ],
    )
    snippet_path = _write_purge_snippet(project, delivered_by=[_PURGED_SLUG, _LIVE_SLUG])
    await _set_removed_row_pending(project, _ROW_PURGE, [_SNIPPET_RELPATH])
    _patch_trusted_dirs(monkeypatch, [project])
    staged: set[str] = set()

    def fake_git(args: list[str], *, cwd: str, timeout: float = 30) -> tuple[int, str, str]:
        _ = cwd, timeout
        if args == ["diff", "--quiet", "HEAD", "--", _SNIPPET_RELPATH]:
            return 1, "", ""
        if args == ["diff", "--cached", "--name-only"]:
            return 0, "\n".join(sorted(staged)) + ("\n" if staged else ""), ""
        if args == ["add", "--", _SNIPPET_RELPATH]:
            staged.add(_SNIPPET_RELPATH)
            return 0, "", ""
        if args and args[0] == "commit":
            return 1, "", "commit failed"
        return 1, "", f"unexpected git args: {args}"

    logger_info = MagicMock()
    monkeypatch.setattr("teleclaude.services.maintenance_service._run_git_cmd", fake_git)
    monkeypatch.setattr("teleclaude.services.maintenance_service.logger.info", logger_info)

    service = _make_service()
    await service._cleanup_removed_todos()

    conn = sqlite3.connect(str(project / ".teleclaude" / "todos.db"))
    try:
        row = conn.execute(
            f"SELECT pending_purge_paths FROM roadmap WHERE id = '{_ROW_PURGE}'"  # guard: raw-sql
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert json.loads(row[0]) == [_SNIPPET_RELPATH]
    assert _snippet_deliverers(snippet_path) == [_LIVE_SLUG]
    assert any(
        call.kwargs.get("reason") == maintenance_service.PURGE_REASON_COMMIT_FAILURE
        for call in logger_info.call_args_list
    )


@pytest.mark.unit
async def test_cleanup_removed_todos_defensive_runtime_error_uses_project_error_handler(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    now = datetime.now(UTC)
    outside = now - (maintenance_service.RETENTION_WINDOW + timedelta(hours=1))
    project = await _seed_project_with_removed_rows(
        tmp_path,
        rows=[(_ROW_PURGE, _PURGED_SLUG, RoadmapStatus.REMOVED, outside)],
    )
    _patch_trusted_dirs(monkeypatch, [project])
    monkeypatch.setattr(
        "teleclaude.services.maintenance_service.reconcile_snippets_for_purged_slugs",
        MagicMock(side_effect=RuntimeError("defensive purge failure")),
    )
    warning = MagicMock()
    monkeypatch.setattr("teleclaude.services.maintenance_service.logger.warning", warning)

    service = _make_service()
    await service._cleanup_removed_todos()

    conn = sqlite3.connect(str(project / ".teleclaude" / "todos.db"))
    try:
        row = conn.execute(
            f"SELECT status, pending_purge_paths FROM roadmap WHERE id = '{_ROW_PURGE}'"  # guard: raw-sql
        ).fetchone()
    finally:
        conn.close()
    assert row == (RoadmapStatus.REMOVED, None)
    warning.assert_called_once()
    assert warning.call_args.kwargs["project_root"] == str(project)
    assert warning.call_args.kwargs["exc_info"] is True


@pytest.mark.unit
async def test_cleanup_removed_todos_self_heals_legacy_partial_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = await _seed_project_with_removed_rows(
        tmp_path,
        rows=[("legacy-id", "legacy-slug", "removed", None)],
    )
    _patch_trusted_dirs(monkeypatch, [project])

    service = _make_service()
    await service._cleanup_removed_todos()

    conn = sqlite3.connect(str(project / ".teleclaude" / "todos.db"))
    try:
        row = conn.execute(
            "SELECT status, removed_at FROM roadmap WHERE id = 'legacy-id'"  # guard: raw-sql
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "removed"
    assert row[1] is not None  # self-healed timestamp


@pytest.mark.unit
async def test_cleanup_removed_todos_skips_directories_without_todos_db(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discovery silently skips trusted directories that are not project roots."""
    bare_dir = tmp_path / "bare"
    bare_dir.mkdir()
    nonexistent = tmp_path / "does-not-exist"
    _patch_trusted_dirs(monkeypatch, [bare_dir, nonexistent])

    service = _make_service()
    await service._cleanup_removed_todos()  # must not raise


@pytest.mark.unit
def test_retention_window_is_shared_between_session_and_todo_cleanup() -> None:
    """A single module-level constant governs both retention sweeps so the
    operator can never accidentally let the two windows drift apart."""
    assert maintenance_service.RETENTION_WINDOW == timedelta(days=7)
