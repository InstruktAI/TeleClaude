"""Functional tests for snippet validation's todo status map.

`build_todo_status_map` reads the live substrate directly (no bootstrap). It must
see live slugs on a DB that still predates the roadmap->todo rename, otherwise a
same-slug remove could orphan a snippet.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude.core.todos_db import todos_db_path
from teleclaude.resource_validation._snippet import build_todo_status_map

pytestmark = pytest.mark.functional

_SLUG = "alpha"
_ACTIVE = "active"


def _seed_db(db_path: Path, owner_table: str) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            f"CREATE TABLE {owner_table} ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, status TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE todo_state ("
            "id TEXT PRIMARY KEY, slug TEXT NOT NULL, state TEXT NOT NULL, "
            "created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            f"INSERT INTO {owner_table} (id, slug, status, created_at, updated_at) VALUES ('id-1', ?, ?, 'now', 'now')",
            (_SLUG, _ACTIVE),
        )
        conn.execute(
            "INSERT INTO todo_state (id, slug, state, created_at, updated_at) VALUES ('id-1', ?, '{}', 'now', 'now')",
            (_SLUG,),
        )
        conn.commit()
    finally:
        conn.close()


def test_status_map_reads_renamed_todo_db(tmp_path: Path) -> None:
    """The status map reads the renamed `todo` table on a migrated DB."""
    project_root = tmp_path / "project"
    _seed_db(todos_db_path(project_root), "todo")

    result = build_todo_status_map(project_root)

    assert result.get(_SLUG) == _ACTIVE


def test_status_map_falls_back_to_legacy_roadmap_db(tmp_path: Path) -> None:
    """On a pre-rename DB (only `roadmap` exists), live slugs are still seen."""
    project_root = tmp_path / "project"
    _seed_db(todos_db_path(project_root), "roadmap")

    result = build_todo_status_map(project_root)

    assert result.get(_SLUG) == _ACTIVE
