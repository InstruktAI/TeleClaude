"""RED specs for receipt-backed todo rename."""

from __future__ import annotations

import importlib
import json
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import TypedDict, cast

import frontmatter
import pytest
from syrupy.assertion import SnapshotAssertion

from teleclaude.constants import ARTIFACT_INPUT, ARTIFACT_REQUIREMENTS, CacheEvent
from teleclaude.core.db import Db
from teleclaude.core.todos_db import TodosDb

pytestmark = pytest.mark.asyncio

_OLD_SLUG = "old-slug"
_NEW_SLUG = "new-slug"
_SIBLING_SLUG = "sibling"
_UPSTREAM_SLUG = "upstream"
_DOWNSTREAM_SLUG = "downstream"
_REQUIREMENTS_V1 = "requirements-v1"
_REQUIREMENTS_V2 = "requirements-v2"
_DELIVERED_INPUT = "delivered input"
_SUCCESS_SURFACES = ["todos.db", "delivered_by:1"]
_RenameExecutor = Callable[[Db, str, str, str], Awaitable[str]]


class _RoadmapSnapshotRoadmapRow(TypedDict):
    slug: str
    group_slug: str | None
    status: str
    children: str | None


class _RoadmapSnapshotDepRow(TypedDict):
    slug: str
    depends_on: str


class _RoadmapSnapshot(TypedDict):
    roadmap: list[_RoadmapSnapshotRoadmapRow]
    deps: list[_RoadmapSnapshotDepRow]


def _rename_executor() -> _RenameExecutor:
    module = importlib.import_module("teleclaude.core.next_machine.rename")
    return cast(_RenameExecutor, module.execute_todo_rename)


async def _main_db(tmp_path: Path) -> Db:
    database = Db(str(tmp_path / "main.db"))
    await database.initialize()
    return database


async def _todos_db(project_root: Path) -> TodosDb:
    database = TodosDb(str(project_root / ".teleclaude" / "todos.db"))
    await database.initialize()
    return database


def _write_target_snippet(project_root: Path, slug: str = _OLD_SLUG) -> Path:
    snippet_path = project_root / "docs" / "project" / "spec" / "rename-contract.md"
    snippet_path.parent.mkdir(parents=True, exist_ok=True)
    snippet_path.write_text(
        (
            "---\n"
            "id: project/spec/rename-contract\n"
            "type: spec\n"
            "scope: project\n"
            "description: Rename contract\n"
            "status: target\n"
            f"delivered_by: [{slug}]\n"
            "---\n"
            "# Rename Contract\n"
            "## What it is\n"
            "Contract body mentioning old-slug as prose.\n"
            "## Canonical fields\n"
            "Fields stay stable.\n"
        ),
        encoding="utf-8",
    )
    return snippet_path


async def _seed_active_todo(todos_db: TodosDb, old_slug: str = _OLD_SLUG) -> None:
    await todos_db.add_to_roadmap(_UPSTREAM_SLUG)
    await todos_db.add_to_roadmap(old_slug, after=[_UPSTREAM_SLUG])
    await todos_db.add_to_roadmap(_DOWNSTREAM_SLUG, after=[old_slug])
    await todos_db.write_state(
        old_slug,
        {
            "kind": "feature",
            "lifecycle_phase": "prepared",
            "breakdown": {"assessed": True, "todos": [old_slug, _SIBLING_SLUG]},
        },
    )
    await todos_db.write_artifact(old_slug, ARTIFACT_INPUT, "input-v1")
    await todos_db.write_artifact(old_slug, ARTIFACT_REQUIREMENTS, _REQUIREMENTS_V1)
    await todos_db.write_artifact(old_slug, ARTIFACT_REQUIREMENTS, _REQUIREMENTS_V2)


async def _run_rename(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    project_root: Path,
    todos_db: TodosDb,
    old_slug: str = _OLD_SLUG,
    new_slug: str = _NEW_SLUG,
) -> str:
    module = importlib.import_module("teleclaude.core.next_machine.rename")

    async def _get_todos_db(_cwd: str) -> TodosDb:
        return todos_db

    monkeypatch.setattr(module, "get_todos_db", _get_todos_db, raising=False)
    executor = cast(_RenameExecutor, module.execute_todo_rename)
    database = await _main_db(tmp_path)
    try:
        return await executor(database, old_slug, new_slug, str(project_root))
    finally:
        await database.close()


def _roadmap_snapshot_row(row: tuple[object, ...]) -> _RoadmapSnapshotRoadmapRow:
    return {
        "slug": str(row[0]),
        "group_slug": str(row[1]) if row[1] is not None else None,
        "status": str(row[2]),
        "children": str(row[3]) if row[3] is not None else None,
    }


def _roadmap_snapshot_dep_row(row: tuple[object, ...]) -> _RoadmapSnapshotDepRow:
    return {"slug": str(row[0]), "depends_on": str(row[1])}


def _roadmap_snapshot(todos_db: TodosDb) -> _RoadmapSnapshot:
    conn = todos_db._sync_conn()  # pylint: disable=protected-access
    try:
        roadmap = [
            _roadmap_snapshot_row(row)
            for row in conn.execute(
                "SELECT slug, group_slug, status, children FROM roadmap ORDER BY status, slug"  # guard: raw-sql
            ).fetchall()
        ]
        deps = [
            _roadmap_snapshot_dep_row(row)
            for row in conn.execute(
                "SELECT slug, depends_on FROM roadmap_deps ORDER BY slug, depends_on"  # guard: raw-sql
            ).fetchall()
        ]
    finally:
        conn.close()
    return {"roadmap": roadmap, "deps": deps}


def _snippet_delivered_by(snippet_path: Path) -> list[str]:
    metadata = frontmatter.load(snippet_path).metadata
    return cast(list[str], metadata["delivered_by"])


async def test_execute_todo_rename_rekeys_todo_db_and_snippet_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    snippet_path = _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)

    try:
        await _run_rename(tmp_path, monkeypatch, project_root=project_root, todos_db=todos_db)

        assert await todos_db.read_state(_OLD_SLUG) is None
        state = await todos_db.read_state(_NEW_SLUG)
        assert state is not None
        assert state["breakdown"]["todos"] == [_NEW_SLUG, _SIBLING_SLUG]  # type: ignore[index]
        assert await todos_db.read_artifact(_NEW_SLUG, ARTIFACT_REQUIREMENTS) == _REQUIREMENTS_V2
        assert [row["content"] for row in await todos_db.artifact_versions(_NEW_SLUG, ARTIFACT_REQUIREMENTS)] == [
            _REQUIREMENTS_V2,
            _REQUIREMENTS_V1,
        ]
        assert await todos_db.load_deps() == {_DOWNSTREAM_SLUG: [_NEW_SLUG], _NEW_SLUG: [_UPSTREAM_SLUG]}
        assert _snippet_delivered_by(snippet_path) == [_NEW_SLUG]
    finally:
        await todos_db.close()


async def test_execute_todo_rename_emits_renamed_event_with_surface_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)
    events: list[tuple[str, Mapping[str, object] | None]] = []

    def _record_event(event_hint: str, event_data: Mapping[str, object] | None = None) -> None:
        events.append((event_hint, event_data))

    monkeypatch.setattr(todos_db, "_on_mutation", _record_event)

    try:
        await _run_rename(tmp_path, monkeypatch, project_root=project_root, todos_db=todos_db)

        assert len(events) == 1
        event_hint, event_data = events[0]
        assert event_hint == CacheEvent.TODO_RENAMED.value
        assert event_data is not None
        assert event_data["old_slug"] == _OLD_SLUG
        assert event_data["new_slug"] == _NEW_SLUG
        assert event_data["surfaces_moved"] == _SUCCESS_SURFACES
    finally:
        await todos_db.close()


async def test_execute_todo_rename_preserves_delivered_history_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await todos_db.add_to_roadmap(_OLD_SLUG)
    await todos_db.write_state(_OLD_SLUG, {"lifecycle_phase": "finalize_ready"})
    await todos_db.write_artifact(_OLD_SLUG, ARTIFACT_INPUT, _DELIVERED_INPUT)
    await todos_db.deliver(_OLD_SLUG, commit="abc123", children=[_OLD_SLUG])
    await _seed_active_todo(todos_db)

    try:
        await _run_rename(tmp_path, monkeypatch, project_root=project_root, todos_db=todos_db)

        delivered = await todos_db.list_roadmap(include_delivered=True)
        delivered_rows = [row for row in delivered if row["status"] == "delivered"]
        assert len(delivered_rows) == 1
        assert delivered_rows[0]["slug"] == _OLD_SLUG
        assert delivered_rows[0]["children"] == [_OLD_SLUG]
        assert await todos_db.read_artifact(_OLD_SLUG, ARTIFACT_INPUT) == _DELIVERED_INPUT
    finally:
        await todos_db.close()


async def test_execute_todo_rename_refuses_existing_non_removed_target_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    snippet_path = _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)
    await todos_db.add_to_roadmap(_NEW_SLUG)
    before = (_roadmap_snapshot(todos_db), snippet_path.read_bytes())

    try:
        result = await _run_rename(tmp_path, monkeypatch, project_root=project_root, todos_db=todos_db)

        assert result == snapshot
        assert (_roadmap_snapshot(todos_db), snippet_path.read_bytes()) == before
    finally:
        await todos_db.close()


async def test_execute_todo_rename_refuses_target_held_by_delivered_history_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    snippet_path = _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)
    await todos_db.add_to_roadmap(_NEW_SLUG)
    await todos_db.deliver(_NEW_SLUG, commit="abc123")
    before = (_roadmap_snapshot(todos_db), snippet_path.read_bytes())

    try:
        result = await _run_rename(tmp_path, monkeypatch, project_root=project_root, todos_db=todos_db)

        assert result == snapshot
        assert (_roadmap_snapshot(todos_db), snippet_path.read_bytes()) == before
    finally:
        await todos_db.close()


async def test_execute_todo_rename_refuses_operation_bound_old_slug_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    snippet_path = _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)
    database = await _main_db(tmp_path)
    await database.create_operation(
        operation_id="op-bound",
        kind="todo_work",
        caller_session_id="caller",
        client_request_id=None,
        cwd=str(project_root),
        slug=_OLD_SLUG,
        payload_json=json.dumps({"slug": _OLD_SLUG}),
        state="queued",
    )
    try:
        module = importlib.import_module("teleclaude.core.next_machine.rename")

        async def _get_todos_db(_cwd: str) -> TodosDb:
            return todos_db

        monkeypatch.setattr(module, "get_todos_db", _get_todos_db, raising=False)
        before = (_roadmap_snapshot(todos_db), snippet_path.read_bytes())

        result = await _rename_executor()(database, _OLD_SLUG, _NEW_SLUG, str(project_root))

        assert result == snapshot
        assert (_roadmap_snapshot(todos_db), snippet_path.read_bytes()) == before
    finally:
        await todos_db.close()
        await database.close()


async def test_execute_todo_rename_refuses_same_cwd_nullable_slug_operation_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    snippet_path = _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)
    database = await _main_db(tmp_path)
    await database.create_operation(
        operation_id="op-same-cwd",
        kind="todo_prepare",
        caller_session_id="caller",
        client_request_id=None,
        cwd=str(project_root),
        slug=None,
        payload_json=json.dumps({"cwd": str(project_root)}),
        state="running",
    )
    try:
        module = importlib.import_module("teleclaude.core.next_machine.rename")

        async def _get_todos_db(_cwd: str) -> TodosDb:
            return todos_db

        monkeypatch.setattr(module, "get_todos_db", _get_todos_db, raising=False)
        before = (_roadmap_snapshot(todos_db), snippet_path.read_bytes())

        result = await _rename_executor()(database, _OLD_SLUG, _NEW_SLUG, str(project_root))

        assert result == snapshot
        assert (_roadmap_snapshot(todos_db), snippet_path.read_bytes()) == before
    finally:
        await todos_db.close()
        await database.close()


async def test_execute_todo_rename_refuses_session_working_slug_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    snippet_path = _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)
    database = await _main_db(tmp_path)
    await database.create_session(
        "local",
        "teleclaude-bound",
        "telegram",
        "Bound session",
        session_id="teleclaude-bound",
        project_path=str(project_root),
        working_slug=_OLD_SLUG,
        emit_session_started=False,
    )
    try:
        module = importlib.import_module("teleclaude.core.next_machine.rename")

        async def _get_todos_db(_cwd: str) -> TodosDb:
            return todos_db

        monkeypatch.setattr(module, "get_todos_db", _get_todos_db, raising=False)
        before = (_roadmap_snapshot(todos_db), snippet_path.read_bytes())

        result = await _rename_executor()(database, _OLD_SLUG, _NEW_SLUG, str(project_root))

        assert result == snapshot
        assert (_roadmap_snapshot(todos_db), snippet_path.read_bytes()) == before
    finally:
        await todos_db.close()
        await database.close()


async def test_execute_todo_rename_refuses_session_worktree_subdir_without_mutating(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    snippet_path = _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)
    database = await _main_db(tmp_path)
    await database.create_session(
        "local",
        "teleclaude-bound-subdir",
        "telegram",
        "Bound subdir session",
        session_id="teleclaude-bound-subdir",
        project_path=str(project_root),
        subdir=f"trees/{_OLD_SLUG}",
        emit_session_started=False,
    )
    try:
        module = importlib.import_module("teleclaude.core.next_machine.rename")

        async def _get_todos_db(_cwd: str) -> TodosDb:
            return todos_db

        monkeypatch.setattr(module, "get_todos_db", _get_todos_db, raising=False)
        before = (_roadmap_snapshot(todos_db), snippet_path.read_bytes())

        result = await _rename_executor()(database, _OLD_SLUG, _NEW_SLUG, str(project_root))

        assert result == snapshot
        assert (_roadmap_snapshot(todos_db), snippet_path.read_bytes()) == before
    finally:
        await todos_db.close()
        await database.close()


async def test_execute_todo_rename_success_summary_names_moved_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    snapshot: SnapshotAssertion,
) -> None:
    project_root = tmp_path / "project"
    _write_target_snippet(project_root)
    todos_db = await _todos_db(project_root)
    await _seed_active_todo(todos_db)

    try:
        result = await _run_rename(tmp_path, monkeypatch, project_root=project_root, todos_db=todos_db)

        assert result == snapshot
    finally:
        await todos_db.close()
