# guard: no-companion
"""Tests that TodosDb mutation methods fire the _on_mutation callback.

Reproduces the bug: TUI todos pane shows stale data because no signal
is emitted after local DB mutations.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from teleclaude.core.next_machine.state_io import _get_todos_db_sync
from teleclaude.core.todos_db import TodosDb, _instances, get_todos_db, set_todos_mutation_hook

pytestmark = pytest.mark.asyncio


def _ensure_roadmap_sync(db: TodosDb, slug: str) -> None:
    """Insert a roadmap entry via raw SQL for sync test paths."""
    conn = db._sync_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO roadmap (id, slug, position, status, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, 0, 'active', '', '')",
            (str(uuid.uuid4()), slug),
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[TodosDb]:
    """Fresh TodosDb instance for each test."""
    database = TodosDb(str(tmp_path / "todos.db"))
    await database.initialize()
    try:
        yield database
    finally:
        await database.close()


async def test_write_state_fires_mutation_callback(db: TodosDb) -> None:
    """write_state calls _on_mutation after committing."""
    await db.add_to_roadmap("my-slug")
    cb = MagicMock()
    db._on_mutation = cb
    await db.write_state("my-slug", {"current": "pending"})
    cb.assert_called_once()


async def test_delete_state_fires_mutation_callback(db: TodosDb) -> None:
    """delete_state calls _on_mutation after committing."""
    await db.add_to_roadmap("my-slug")
    await db.write_state("my-slug", {"current": "pending"})
    cb = MagicMock()
    db._on_mutation = cb
    await db.delete_state("my-slug")
    cb.assert_called_once()


async def test_write_state_sync_fires_mutation_callback(db: TodosDb) -> None:
    """write_state_sync calls _on_mutation after committing (sync/worker thread path)."""
    await db.add_to_roadmap("my-slug")
    cb = MagicMock()
    db._on_mutation = cb
    db.write_state_sync("my-slug", {"current": "pending"})
    cb.assert_called_once()


async def test_add_to_roadmap_fires_mutation_callback(db: TodosDb) -> None:
    """add_to_roadmap calls _on_mutation after committing."""
    cb = MagicMock()
    db._on_mutation = cb
    await db.add_to_roadmap("my-slug")
    cb.assert_called_once()


async def test_deliver_fires_mutation_callback(db: TodosDb) -> None:
    """deliver calls _on_mutation after committing."""
    await db.add_to_roadmap("my-slug")
    await db.write_state("my-slug", {"current": "build"})
    cb = MagicMock()
    db._on_mutation = cb
    await db.deliver("my-slug")
    cb.assert_called_once()


async def test_deliver_sync_fires_mutation_callback(db: TodosDb) -> None:
    """deliver_sync calls _on_mutation after committing (sync/worker thread path)."""
    await db.add_to_roadmap("my-slug")
    await db.write_state("my-slug", {"current": "build"})
    cb = MagicMock()
    db._on_mutation = cb
    db.deliver_sync("my-slug")
    cb.assert_called_once()


async def test_write_artifact_fires_mutation_callback(db: TodosDb) -> None:
    """write_artifact calls _on_mutation after committing."""
    await db.add_to_roadmap("my-slug")
    cb = MagicMock()
    db._on_mutation = cb
    await db.write_artifact("my-slug", "notes", "content")
    cb.assert_called_once()


async def test_delete_artifacts_fires_mutation_callback(db: TodosDb) -> None:
    """delete_artifacts calls _on_mutation after committing."""
    await db.add_to_roadmap("my-slug")
    await db.write_artifact("my-slug", "notes", "content")
    cb = MagicMock()
    db._on_mutation = cb
    await db.delete_artifacts("my-slug")
    cb.assert_called_once()


async def test_remove_from_roadmap_fires_mutation_callback(db: TodosDb) -> None:
    """remove_from_roadmap calls _on_mutation after committing."""
    await db.add_to_roadmap("my-slug")
    cb = MagicMock()
    db._on_mutation = cb
    await db.remove_from_roadmap("my-slug")
    cb.assert_called_once()


async def test_freeze_fires_mutation_callback(db: TodosDb) -> None:
    """freeze calls _on_mutation when the row is found and updated."""
    await db.add_to_roadmap("my-slug")
    cb = MagicMock()
    db._on_mutation = cb
    await db.freeze("my-slug")
    cb.assert_called_once()


async def test_unfreeze_fires_mutation_callback(db: TodosDb) -> None:
    """unfreeze calls _on_mutation when the row is found and updated."""
    await db.add_to_roadmap("my-slug")
    await db.freeze("my-slug")
    cb = MagicMock()
    db._on_mutation = cb
    await db.unfreeze("my-slug")
    cb.assert_called_once()


async def test_set_deps_fires_mutation_callback(db: TodosDb) -> None:
    """set_deps calls _on_mutation after committing."""
    await db.add_to_roadmap("my-slug")
    await db.add_to_roadmap("dep-slug")
    cb = MagicMock()
    db._on_mutation = cb
    await db.set_deps("my-slug", after=["dep-slug"])
    cb.assert_called_once()


async def test_clean_dep_references_fires_mutation_callback(db: TodosDb) -> None:
    """clean_dep_references calls _on_mutation after committing."""
    await db.add_to_roadmap("my-slug")
    await db.add_to_roadmap("dep-slug")
    await db.set_deps("my-slug", after=["dep-slug"])
    cb = MagicMock()
    db._on_mutation = cb
    await db.clean_dep_references("dep-slug")
    cb.assert_called_once()


async def test_move_in_roadmap_fires_mutation_callback(db: TodosDb) -> None:
    """move_in_roadmap calls _on_mutation after committing."""
    await db.add_to_roadmap("slug-a")
    await db.add_to_roadmap("slug-b")
    cb = MagicMock()
    db._on_mutation = cb
    await db.move_in_roadmap("slug-a", after="slug-b")
    cb.assert_called_once()


async def test_set_todos_mutation_hook_applies_to_sync_get_todos_db_instance(tmp_path: Path) -> None:
    """Hook registered via set_todos_mutation_hook is applied to sync instances from state_io._get_todos_db_sync."""
    project_root = str(tmp_path)
    calls: list[str] = []

    def _hook(instance: TodosDb, root: str) -> None:
        instance._on_mutation = lambda event_hint: calls.append(root)

    set_todos_mutation_hook(_hook)
    try:
        # state_io imports _new_instance_hook at module load time — patch its
        # stale copy so _get_todos_db_sync sees the hook we just registered.
        with patch("teleclaude.core.next_machine.state_io._new_instance_hook", _hook):
            synced_db = _get_todos_db_sync(project_root)
            _ensure_roadmap_sync(synced_db, "my-slug")
            synced_db.write_state_sync("my-slug", {"current": "pending"})
        assert calls == [project_root]
    finally:
        set_todos_mutation_hook(None)


async def test_no_callback_by_default(db: TodosDb) -> None:
    """Default _on_mutation is a no-op — mutations complete without error."""
    await db.add_to_roadmap("my-slug")
    await db.write_state("my-slug", {"current": "pending"})
    result = await db.read_state("my-slug")
    assert result is not None


async def test_on_committed_invokes_mutation_callback(db: TodosDb) -> None:
    """on_committed is the public API for externally-managed transactions to trigger mutation notifications."""
    cb = MagicMock()
    db._on_mutation = cb
    db.on_committed("todo_removed")
    cb.assert_called_once_with("todo_removed")


async def test_set_todos_mutation_hook_applies_to_new_get_todos_db_instance(tmp_path: Path) -> None:
    """Hook registered via set_todos_mutation_hook is applied to instances created by get_todos_db."""
    project_root = str(tmp_path)
    db_path = str(tmp_path / ".teleclaude" / "todos.db")
    calls: list[str] = []

    def _hook(instance: TodosDb, root: str) -> None:
        instance._on_mutation = lambda event_hint: calls.append(root)

    # Create DB and add roadmap entry BEFORE setting hook (add_to_roadmap also fires mutation)
    pre_db = await get_todos_db(project_root)
    await pre_db.add_to_roadmap("my-slug")
    await pre_db.close()
    _instances.pop(db_path, None)

    set_todos_mutation_hook(_hook)
    created: TodosDb | None = None
    try:
        created = await get_todos_db(project_root)
        await created.write_state("my-slug", {"current": "pending"})
        assert calls == [project_root]
    finally:
        set_todos_mutation_hook(None)
        _instances.pop(db_path, None)
        if created is not None:
            await created.close()
