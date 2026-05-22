"""Tests for the todos.db SQLModel table contract."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from teleclaude.core.todos_db import TodosDb
from teleclaude.core.todos_db._models import TodoRoadmap


def _roadmap_columns(db_path: str) -> set[str]:
    """Return the column names of the roadmap table on disk."""
    conn = sqlite3.connect(db_path)
    try:
        return {row[1] for row in conn.execute("PRAGMA table_info(roadmap)").fetchall()}
    finally:
        conn.close()


async def test_fresh_db_roadmap_has_tombstone_columns(tmp_path: Path) -> None:
    db_path = str(tmp_path / "todos.db")
    database = TodosDb(db_path)
    await database.initialize()
    await database.close()

    columns = _roadmap_columns(db_path)
    assert {"removed_at", "prev_status", "removed_deps", "pending_purge_paths"} <= columns


async def test_removed_and_live_rows_share_a_slug(todos_db: TodosDb) -> None:
    """A removed row and a live row may carry the same slug — the partial-unique
    predicate excludes removed, so the index does not collide."""
    await todos_db.add_to_roadmap("recycled")
    row_id = await todos_db.resolve_id("recycled")
    assert row_id is not None

    with todos_db._sync_session() as session:
        entry = session.get(TodoRoadmap, row_id)
        assert entry is not None
        entry.status = "removed"
        session.add(entry)
        session.add(
            TodoRoadmap(
                id="fresh-live-row",
                slug="recycled",
                status="active",
                created_at="2026-05-19T00:00:00+00:00",
                updated_at="2026-05-19T00:00:00+00:00",
            )
        )
        session.commit()  # no IntegrityError: removed row is outside the predicate

    with todos_db._sync_session() as session:
        statuses = {
            row.id: row.status
            for row in session.exec(select(TodoRoadmap).where(TodoRoadmap.slug == "recycled")).all()  # type: ignore[attr-defined]
        }
    assert statuses == {row_id: "removed", "fresh-live-row": "active"}


async def test_two_live_entries_same_slug_still_rejected(todos_db: TodosDb) -> None:
    await todos_db.add_to_roadmap("unique-slug")
    with todos_db._sync_session() as session:
        session.add(
            TodoRoadmap(
                id="forced-duplicate",
                slug="unique-slug",
                status="active",
                created_at="2026-05-19T00:00:00+00:00",
                updated_at="2026-05-19T00:00:00+00:00",
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()
