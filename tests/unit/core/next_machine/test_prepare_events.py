"""Characterization tests for prepare events and invalidation."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from unittest.mock import patch

from teleclaude.core.next_machine._types import PreparePhase, RoadmapEntry
from teleclaude.core.next_machine.prepare_events import (
    _has_test_spec_artifacts,
    invalidate_stale_preparations,
)
from teleclaude.core.next_machine.roadmap import save_roadmap


def _write_state_db(tmp_path: Path, slug: str, state: dict[object, object]) -> None:
    """Write state to todos.db for invalidation tests."""
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


def test_has_test_spec_artifacts_detects_xfail_marked_tests_in_worktree(tmp_path: Path) -> None:
    worktree = tmp_path / "trees" / "slug-a" / "tests"
    worktree.mkdir(parents=True)
    (worktree / "test_example.py").write_text("import pytest\n\npytestmark = pytest.mark.xfail\n", encoding="utf-8")

    assert _has_test_spec_artifacts(str(tmp_path), "slug-a") is True


def test_invalidate_stale_preparations_marks_only_overlapping_grounding_as_invalid(tmp_path: Path) -> None:
    save_roadmap(
        str(tmp_path),
        [
            RoadmapEntry(slug="slug-c", group=None, after=[], description=None),
            RoadmapEntry(slug="slug-d", group=None, after=[], description=None),
        ],
    )
    _write_state_db(
        tmp_path,
        "slug-c",
        {"grounding": {"referenced_paths": ["src/app.py"], "valid": True}},
    )
    _write_state_db(
        tmp_path,
        "slug-d",
        {"grounding": {"referenced_paths": ["src/other.py"], "valid": True}},
    )

    with patch("teleclaude.core.next_machine.prepare_events._emit_prepare_event") as emit_event:
        result = invalidate_stale_preparations(str(tmp_path), ["src/app.py"])

    # Verify DB state was updated (read back from DB)
    from teleclaude.core.todos_db import TodosDb  # pylint: disable=import-outside-toplevel

    db = TodosDb(str(tmp_path / ".teleclaude" / "todos.db"))
    db.initialize_sync()
    conn = db._sync_conn()  # pylint: disable=protected-access
    try:
        row_c = conn.execute(
            "SELECT ts.state FROM todo_state ts JOIN roadmap r ON ts.id = r.id "  # guard: raw-sql
            "WHERE r.slug = 'slug-c'",
        ).fetchone()
        row_d = conn.execute(
            "SELECT ts.state FROM todo_state ts JOIN roadmap r ON ts.id = r.id "  # guard: raw-sql
            "WHERE r.slug = 'slug-d'",
        ).fetchone()
    finally:
        conn.close()

    invalidated_state = json.loads(row_c[0])
    untouched_state = json.loads(row_d[0])
    assert result == {"invalidated": ["slug-c"]}
    assert invalidated_state["grounding"]["valid"] is False
    assert invalidated_state["current"] == PreparePhase.GROUNDING_CHECK.value
    assert untouched_state["grounding"]["valid"] is True
    assert emit_event.call_args.args[0] == "domain.software-development.prepare.grounding_invalidated"
