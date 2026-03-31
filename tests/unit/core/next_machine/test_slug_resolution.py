"""Characterization tests for slug resolution and readiness gating."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from teleclaude.core.next_machine.slug_resolution import (
    get_item_phase,
    is_ready_for_work,
    resolve_canonical_project_root,
)


def _write_state(todo_dir: Path, state: dict[object, object]) -> None:
    todo_dir.mkdir(parents=True, exist_ok=True)
    (todo_dir / "state.yaml").write_text(yaml.safe_dump(state), encoding="utf-8")


def test_is_ready_for_work_accepts_pending_item_with_completed_build(tmp_path: Path) -> None:
    _write_state(tmp_path / "todos" / "from-main-slug", {"schema_version": 2, "current": "prepared"})

    assert is_ready_for_work(str(tmp_path), "from-main-slug") is True


def test_resolve_canonical_project_root_falls_back_to_requested_cwd_on_git_error() -> None:
    with patch("subprocess.run", side_effect=Exception("git error")):
        root = resolve_canonical_project_root("/repo/trees/slug")

    assert root == "/repo/trees/slug"


def test_get_item_phase_returns_done_for_delivered_slug(tmp_path: Path) -> None:
    from teleclaude.core.todos_db import TodosDb

    db_path = tmp_path / ".teleclaude" / "todos.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = TodosDb(str(db_path))
    db.initialize_sync()
    conn = db._sync_conn()
    try:
        conn.execute(
            "INSERT INTO roadmap (slug, position, status, created_at, updated_at) VALUES (?, 0, 'delivered', '', '')",
            ("done-slug",),
        )
        conn.commit()
    finally:
        conn.close()
    _write_state(tmp_path / "todos" / "done-slug", {"schema_version": 2, "current": "input_assessment"})

    assert get_item_phase(str(tmp_path), "done-slug") == "done"
