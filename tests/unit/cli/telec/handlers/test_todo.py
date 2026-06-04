"""Tests for telec todo create/remove/split and other CLI handlers (DB-backed)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import select
from syrupy.assertion import SnapshotAssertion

from teleclaude.cli.telec.handlers.todo import (
    _handle_todo_create,
    _handle_todo_deliver,
    _handle_todo_design,
    _handle_todo_freeze,
    _handle_todo_reconcile,
    _handle_todo_remove,
    _handle_todo_rename,
    _handle_todo_split,
    _handle_todo_stamp,
    _handle_todo_unfreeze,
)
from teleclaude.constants import RoadmapStatus
from teleclaude.core.db import Db
from teleclaude.core.operations.service import OperationsService
from teleclaude.core.todos_db import TodosDb, close_todos_db_instances, get_todos_db
from teleclaude.core.todos_db._models import TodoRoadmap

_MODULE = "teleclaude.cli.telec.handlers.todo"
_RENAME_RESULT = "renamed old-slug->new-slug (todos.db, delivered_by:1, worktree)"


_KIND_TODO = "todo"
_EVENTS_EMIT_PATH = "/events/emit"
_ACTIVE_SLUG = "active-item"
_DEPENDENCY_SLUG = "dependency-item"
_COMMIT_HASH = "abc123"
_READY_SINCE = "2026-05-20T00:00:00+00:00"
_TODO_STATE = {"schema_version": 2, "kind": "todo", "phase": "in_progress", "lifecycle_phase": "prepared"}


def _make_worktree(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "main"
    worktree = tmp_path / "trees" / "sample"
    gitdir = repo_root / ".git" / "worktrees" / "sample"
    gitdir.mkdir(parents=True)
    worktree.mkdir(parents=True)
    (worktree / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
    return repo_root, worktree


def _make_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    return project


def _database(project: Path) -> TodosDb:
    return TodosDb(str(project / ".teleclaude" / "todos.db"))


def _entry_status(database: TodosDb, slug: str) -> tuple[str, str | None]:
    with database._sync_session() as session:
        entry = session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == slug).limit(1)).one()
        return entry.status, entry.ready_since


_TODO_CONTENT = "Implement the feature"
_TODO_SLUG = "my-slug"
_API_DUMP_PATH = "/todos/dump"


class _StoredTask:
    def __init__(self) -> None:
        self._done = False

    def done(self) -> bool:
        return self._done


class _DeferredTaskRegistry:
    def __init__(self) -> None:
        self._coros: list[Awaitable[object]] = []

    def spawn(self, coro: Awaitable[object], *, name: str) -> _StoredTask:
        _ = name
        self._coros.append(coro)
        return _StoredTask()

    async def drain(self) -> None:
        while self._coros:
            coro = self._coros.pop(0)
            await coro


class TestHandleTodoCreate:
    """telec todo create <slug> <content> --kind <kind> [--silent] [--after deps]."""

    def test_create_with_kind_and_content_routes_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[dict] = []
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        monkeypatch.setattr(
            f"{_MODULE}.tool_api_request",
            lambda method, path, **kw: captured.append(kw.get("json_body", {})) or {"status": "ok"},
        )
        _handle_todo_create([_TODO_SLUG, _TODO_CONTENT, "--kind", "feature"])
        assert captured
        assert captured[0].get("content") == _TODO_CONTENT

    def test_create_without_kind_fails_with_usage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api_calls: list = []
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        monkeypatch.setattr(
            f"{_MODULE}.tool_api_request",
            lambda *a, **kw: api_calls.append(a),
        )
        with pytest.raises(SystemExit):
            _handle_todo_create([_TODO_SLUG, _TODO_CONTENT])
        assert not api_calls

    def test_create_without_content_fails_clearly_and_writes_nothing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        api_calls: list = []
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        monkeypatch.setattr(
            f"{_MODULE}.tool_api_request",
            lambda *a, **kw: api_calls.append(a),
        )
        with pytest.raises(SystemExit):
            _handle_todo_create([_TODO_SLUG])
        assert not api_calls

    def test_create_silent_forwards_silent_true_to_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[dict] = []
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        monkeypatch.setattr(
            f"{_MODULE}.tool_api_request",
            lambda method, path, **kw: captured.append(kw.get("json_body", {})) or {"status": "ok"},
        )
        _handle_todo_create([_TODO_SLUG, _TODO_CONTENT, "--kind", "feature", "--silent"])
        assert captured
        assert captured[0].get("silent") is True


class TestHandleTodoDesign:
    """telec todo design [<slug>]."""

    def test_design_delegates_to_tool_command(self) -> None:
        with patch(f"{_MODULE}.handle_todo_design") as mock_design:
            _handle_todo_design(["my-slug"])

        mock_design.assert_called_once_with(["my-slug"])


class TestHandleTodoReconcile:
    """telec todo reconcile <slug> [--stage prepare|work]."""

    def test_success_prints_confirmation(
        self, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        with patch(
            f"{_MODULE}.reconcile_phase_state",
            return_value={"lifecycle_phase": "plan_review"},
        ) as mock_reconcile:
            _handle_todo_reconcile(["my-slug"])

        assert "Reconciled my-slug lifecycle_phase=plan_review" in capsys.readouterr().out
        mock_reconcile.assert_called_once_with("/repo", "my-slug", None)

    def test_passes_explicit_stage(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        with patch(
            f"{_MODULE}.reconcile_phase_state",
            return_value={"lifecycle_phase": "build_complete"},
        ) as mock_reconcile:
            _handle_todo_reconcile(["my-slug", "--stage", "work"])

        mock_reconcile.assert_called_once_with("/repo", "my-slug", "work")

    def test_unknown_stage_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_reconcile(["my-slug", "--stage", "elsewhere"])


class TestHandleTodoRemove:
    """telec todo remove <slug>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        receipt = {"operation_id": "op-1", "kind": "todo_remove", "state": "queued", "poll_after_ms": 250}
        completed = {"operation_id": "op-1", "kind": "todo_remove", "state": "completed", "result": "removed my-slug"}

        with (
            patch(f"{_MODULE}.tool_api_call", return_value=receipt),
            patch(f"{_MODULE}.poll_operation", return_value=completed),
        ):
            _handle_todo_remove(["my-slug"])

        assert "Removed todo: my-slug" in capsys.readouterr().out

    def test_remove_refusal_renders_structured_payload(
        self,
        capsys: pytest.CaptureFixture[str],
        snapshot: SnapshotAssertion,
    ) -> None:
        receipt = {"operation_id": "op-1", "kind": "todo_remove", "state": "queued", "poll_after_ms": 250}
        failed = {
            "operation_id": "op-1",
            "kind": "todo_remove",
            "state": "failed",
            "error": "RemoveRefused",
            "error_payload": {
                "kind": "remove_refused_orphan",
                "blocking_snippets": [
                    {
                        "path": "/repo/docs/project/spec/snippet.md",
                        "slug_role": "sole",
                        "live_deliverer_count": 0,
                        "other_removed_deliverers": [],
                    }
                ],
            },
        }

        with (
            patch(f"{_MODULE}.tool_api_call", return_value=receipt),
            patch(f"{_MODULE}.poll_operation", return_value=failed),
            pytest.raises(SystemExit),
        ):
            _handle_todo_remove(["my-slug"])

        assert capsys.readouterr().err == snapshot

    def test_remove_refusal_round_trips_through_operation_layer(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
        cluster_event_bus: None,
    ) -> None:
        _ = cluster_event_bus

        async def setup() -> tuple[Db, OperationsService, _DeferredTaskRegistry]:
            project_root = tmp_path / "project"
            project_root.mkdir()
            monkeypatch.setenv("TELEC_INVOCATION_CWD", str(project_root))
            snippet_path = project_root / "docs" / "project" / "spec" / "snippet.md"
            snippet_path.parent.mkdir(parents=True, exist_ok=True)
            snippet_path.write_text(
                "---\n"
                "id: project/spec/snippet\n"
                "type: spec\n"
                "scope: project\n"
                "description: Snippet\n"
                "status: target\n"
                "delivered_by: [my-slug]\n"
                "---\n"
                "# Snippet\n\n"
                "## What it is\n"
                "A snippet.\n\n"
                "## Canonical fields\n"
                "Fields.\n",
                encoding="utf-8",
            )
            todos_db = await get_todos_db(project_root)
            await todos_db.add_to_roadmap(_TODO_SLUG)

            database = Db(str(project_root / ".teleclaude" / "main.db"))
            await database.initialize()
            registry = _DeferredTaskRegistry()
            return database, OperationsService(db=database, task_registry=registry), registry

        database, service, registry = asyncio.run(setup())

        def submit_remove(method: str, path: str, **kwargs: object) -> object:
            assert method == "POST"
            assert path == "/todos/remove"
            body = kwargs["json_body"]
            assert isinstance(body, dict)
            return asyncio.run(
                service.submit_todo_remove(
                    slug=str(body["slug"]),
                    cwd=str(body["cwd"]),
                    caller_session_id="caller-123",
                    client_request_id=str(body["client_request_id"]),
                )
            )

        def drain_and_poll(receipt: object, *, estimated_timeout_ms: int) -> object:
            _ = estimated_timeout_ms
            assert isinstance(receipt, dict)

            async def run() -> object:
                await registry.drain()
                return await service.get_operation_for_caller(
                    operation_id=str(receipt["operation_id"]),
                    caller_session_id="caller-123",
                    human_role=None,
                )

            return asyncio.run(run())

        try:
            with (
                patch(f"{_MODULE}.tool_api_call", side_effect=submit_remove),
                patch(f"{_MODULE}.poll_operation", side_effect=drain_and_poll),
                pytest.raises(SystemExit),
            ):
                _handle_todo_remove([_TODO_SLUG])
        finally:
            asyncio.run(database.close())
            asyncio.run(close_todos_db_instances())

        assert capsys.readouterr().err == (
            "Remove refused; blocking snippets:\n"
            f"- path={tmp_path}/project/docs/project/spec/snippet.md "
            "slug_role=sole live_deliverer_count=0\n"
            "Refused: my-slug would orphan 1 snippet(s); see structured error above.\n"
        )

    def test_missing_slug_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_remove([])


class TestHandleTodoRename:
    """telec todo rename <old-slug> <new-slug>."""

    def test_success_prints_confirmation(
        self,
        capsys: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
        snapshot: SnapshotAssertion,
    ) -> None:
        monkeypatch.setenv("TELEC_INVOCATION_CWD", "/repo")
        receipt = {"operation_id": "op-1", "kind": "todo_rename", "state": "queued", "poll_after_ms": 250}
        completed = {"operation_id": "op-1", "kind": "todo_rename", "state": "completed", "result": _RENAME_RESULT}

        with (
            patch(f"{_MODULE}.uuid.uuid4", return_value="req-1"),
            patch(f"{_MODULE}.tool_api_call", return_value=receipt) as api_call,
            patch(f"{_MODULE}.poll_operation", return_value=completed),
        ):
            _handle_todo_rename(["old-slug", "new-slug"])

        assert capsys.readouterr().out == snapshot
        api_call.assert_called_once_with(
            "POST",
            "/todos/rename",
            json_body={
                "old_slug": "old-slug",
                "new_slug": "new-slug",
                "cwd": "/repo",
                "client_request_id": "req-1",
            },
        )

    def test_missing_target_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_rename(["old-slug"])


class TestHandleTodoSplit:
    """telec todo split <slug> --into <child>."""

    def test_success_prints_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        with patch(f"{_MODULE}.tool_api_request", return_value={"status": "ok"}):
            _handle_todo_split(["parent", "--into", "child-a", "--into", "child-b"])

        output = capsys.readouterr().out
        assert "child-a" in output
        assert "child-b" in output

    def test_missing_children_exits(self) -> None:
        with pytest.raises(SystemExit):
            _handle_todo_split(["parent"])


class TestHandleTodoStampPrepareV2:
    """telec todo stamp v2 prepare flags."""

    def test_prd_approved_posts_stamp(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--prd-approved"])

        mock_stamp.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="prd_approved",
            value="true",
            phase=None,
            caller_session_id="sess-1",
        )

    def test_skip_flag_posts_reason(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--architecture-skipped", "single file"])

        mock_stamp.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="architecture_skipped",
            value="single file",
            phase=None,
            caller_session_id="sess-1",
        )

    def test_drift_reviewed_posts_json_payload(self) -> None:
        with (
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})) as mock_stamp,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--drift-reviewed", "prd", "cosmetic", "comments"])

        kwargs = mock_stamp.await_args.kwargs
        assert kwargs["stamp_type"] == "drift_reviewed"
        assert kwargs["value"] == '{"artifact": "prd", "verdict": "cosmetic", "reason": "comments"}'


class TestHandleTodoStampEnsureProducer:
    """Lazy event-producer setup is opt-in at the CLI boundary for finalize_ready only."""

    def test_finalize_ready_initializes_producer_before_applying_stamp(self) -> None:
        """ensure_event_producer must run before apply_todo_stamp and the stamp must still flow through."""
        order: list[str] = []

        def _record_ensure() -> None:
            order.append("ensure")

        async def _record_apply(**_: object) -> dict[str, str]:
            order.append("apply")
            return {"status": "ok"}

        with (
            patch(f"{_MODULE}.ensure_event_producer", side_effect=_record_ensure),
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(side_effect=_record_apply)) as mock_apply,
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--finalize-ready"])

        assert order == ["ensure", "apply"]
        mock_apply.assert_awaited_once_with(
            cwd="/repo",
            slug="my-slug",
            stamp_type="finalize_ready",
            value="",
            phase=None,
            caller_session_id="sess-1",
        )

    def test_build_complete_does_not_initialize_producer(self) -> None:
        """Stamps that do not emit events must not pay the Redis-connect cost."""
        with (
            patch(f"{_MODULE}.ensure_event_producer") as mock_ensure,
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})),
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--build-complete"])

        mock_ensure.assert_not_called()

    def test_verdict_stamp_does_not_initialize_producer(self) -> None:
        """Verdict stamps mutate state only — no event emission, no producer needed."""
        with (
            patch(f"{_MODULE}.ensure_event_producer") as mock_ensure,
            patch(f"{_MODULE}.apply_todo_stamp", new=AsyncMock(return_value={"status": "ok"})),
            patch(f"{_MODULE}.resolve_invocation_cwd", return_value=Path("/repo")),
            patch(f"{_MODULE}.get_session_id", return_value="sess-1"),
        ):
            _handle_todo_stamp(["my-slug", "--verdict", "approve", "--phase", "build"])

        mock_ensure.assert_not_called()


class TestHandleTodoRoadmapVerbs:
    """telec todo freeze/unfreeze/deliver mutate roadmap status."""

    def test_freeze_unfreeze_round_trip(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        project = _make_project(tmp_path)
        monkeypatch.setenv("TELEC_INVOCATION_CWD", str(project))
        monkeypatch.chdir(project)
        database = _database(project)
        asyncio.run(database.initialize())
        try:
            asyncio.run(database.add_to_roadmap(_ACTIVE_SLUG))
            asyncio.run(database.write_state(_ACTIVE_SLUG, _TODO_STATE))

            _handle_todo_freeze([_ACTIVE_SLUG])
            assert _entry_status(database, _ACTIVE_SLUG)[0] == RoadmapStatus.ICEBOX

            _handle_todo_unfreeze([_ACTIVE_SLUG])
            assert _entry_status(database, _ACTIVE_SLUG)[0] == RoadmapStatus.ACTIVE
        finally:
            asyncio.run(database.close())

    def test_deliver_calls_cleanup_delivered_slug(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        db_called: list[tuple[Path, str, str]] = []
        repo_root, worktree = _make_worktree(tmp_path)
        monkeypatch.setenv("TELEC_INVOCATION_CWD", str(worktree))
        monkeypatch.chdir(worktree)
        monkeypatch.setattr(
            f"{_MODULE}._run_db",
            lambda project_root, slug, method, **_kw: db_called.append((project_root, slug, method)) or True,
        )

        with patch(f"{_MODULE}.cleanup_delivered_slug") as cleanup:
            _handle_todo_deliver([_ACTIVE_SLUG, "--commit", _COMMIT_HASH])

        assert db_called[0] == (repo_root, _ACTIVE_SLUG, "deliver")
        cleanup.assert_called_once_with(str(repo_root), _ACTIVE_SLUG)

    def test_deliver_marks_delivered_and_clears_ready_since(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        project = _make_project(tmp_path)
        monkeypatch.setenv("TELEC_INVOCATION_CWD", str(project))
        monkeypatch.chdir(project)
        database = _database(project)
        asyncio.run(database.initialize())
        try:
            asyncio.run(database.add_to_roadmap(_ACTIVE_SLUG, after=[_DEPENDENCY_SLUG]))
            asyncio.run(database.write_state(_ACTIVE_SLUG, _TODO_STATE))
            database.stamp_ready_since_if_null_sync(_ACTIVE_SLUG, _READY_SINCE)

            with patch(f"{_MODULE}.cleanup_delivered_slug"):
                _handle_todo_deliver([_ACTIVE_SLUG, "--commit", _COMMIT_HASH])

            assert _entry_status(database, _ACTIVE_SLUG) == (RoadmapStatus.DELIVERED, None)
        finally:
            asyncio.run(database.close())
