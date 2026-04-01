"""Characterization tests for slug resolution and readiness gating."""
# pylint: disable=missing-function-docstring

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

from teleclaude.core.next_machine.slug_resolution import (
    get_item_phase,
    is_ready_for_work,
    resolve_canonical_project_root,
)


def _write_state_db(tmp_path: Path, slug: str, state: dict[object, object]) -> None:
    """Write state to todos.db so read_phase_state can find it."""
    from teleclaude.core.todos_db import TodosDb  # pylint: disable=import-outside-toplevel

    db_path = tmp_path / ".teleclaude" / "todos.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = TodosDb(str(db_path))
    db.initialize_sync()
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        roadmap_id = str(uuid.uuid4())
        conn.execute(
            "INSERT OR IGNORE INTO roadmap (id, slug, position, status, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, 0, 'active', '', '')",
            (roadmap_id, slug),
        )
        row = conn.execute(
            "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered'",  # guard: raw-sql
            (slug,),
        ).fetchone()
        if row:
            conn.execute(
                "INSERT OR REPLACE INTO todo_state (id, slug, state, created_at, updated_at) "  # guard: raw-sql
                "VALUES (?, ?, ?, datetime('now'), datetime('now'))",
                (row[0], slug, json.dumps(state)),
            )
        conn.commit()
    finally:
        conn.close()


def test_is_ready_for_work_accepts_pending_item_with_completed_build(tmp_path: Path) -> None:
    _write_state_db(tmp_path, "from-main-slug", {"schema_version": 2, "current": "prepared"})

    assert is_ready_for_work(str(tmp_path), "from-main-slug") is True


def test_resolve_canonical_project_root_falls_back_to_requested_cwd_on_git_error() -> None:
    with patch("subprocess.run", side_effect=Exception("git error")):
        root = resolve_canonical_project_root("/repo/trees/slug")

    assert root == "/repo/trees/slug"


def test_get_item_phase_returns_done_for_delivered_slug(tmp_path: Path) -> None:
    from teleclaude.core.todos_db import TodosDb  # pylint: disable=import-outside-toplevel

    db_path = tmp_path / ".teleclaude" / "todos.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = TodosDb(str(db_path))
    db.initialize_sync()
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        conn.execute(
            "INSERT INTO roadmap (id, slug, position, status, created_at, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, 0, 'delivered', '', '')",
            (str(uuid.uuid4()), "done-slug"),
        )
        conn.commit()
    finally:
        conn.close()

    assert get_item_phase(str(tmp_path), "done-slug") == "done"
