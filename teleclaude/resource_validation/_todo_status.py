"""Live todo status map for snippet validation and purge reconciliation.

Reads the todos.db substrate directly (no ORM bootstrap) to resolve which slugs
are live deliverers. Kept in its own module so the snippet validator stays under
the module-size guardrail.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from teleclaude.constants import TodoStatus
from teleclaude.core.todos_db_path import todos_db_path

_TODO_STATUS_VALUES = (
    TodoStatus.ACTIVE,
    TodoStatus.ICEBOX,
    TodoStatus.DELIVERED,
    TodoStatus.REMOVED,
)
_TODO_STATUS_PRIORITY = {
    TodoStatus.REMOVED: -1,
    TodoStatus.DELIVERED: 0,
    TodoStatus.ACTIVE: 1,
    TodoStatus.ICEBOX: 1,
}


def _read_status_rows(conn: sqlite3.Connection, owner_table: str) -> list[tuple[object, object]]:
    """Read (slug, status) for live deliverers from the substrate owner table.

    A real todo exists in ``todo_state``; the owner table (``todo`` post-rename,
    legacy ``roadmap`` on un-migrated DBs) also retains delivered/removed status
    rows that lack a ``todo_state`` row, until ``v2-workflow-drop-roadmap``
    migrates the v1 substrate. Join so orphaned owner rows with no real todo are
    excluded — otherwise a phantom slug would read as a live deliverer.
    """
    return conn.execute(
        f"SELECT r.slug, r.status FROM {owner_table} r "  # guard: raw-sql - owner table resolved by caller
        "JOIN todo_state ts ON ts.slug = r.slug "
        "WHERE r.status IN (?, ?, ?, ?)",
        _TODO_STATUS_VALUES,
    ).fetchall()


def build_todo_status_map(project_root: Path) -> dict[str, str]:
    """Read todo slug status once for snippet validation/reconciliation.

    Falls back to the canonical state root (main repo) when invoked from a
    git worktree where ``.teleclaude/todos.db`` is not present. On a DB that
    still predates the substrate rename, reads the legacy ``roadmap`` table.
    """
    db_path = todos_db_path(project_root)
    if not db_path.exists():
        return {}
    conn = sqlite3.connect(db_path)
    try:
        try:
            rows = _read_status_rows(conn, "todo")
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise
            # The DB exists but predates the roadmap->todo substrate rename and
            # has not been bootstrapped/migrated yet. Read the legacy ``roadmap``
            # table directly so live pending slugs are seen instead of treated as
            # missing (which would let a same-slug remove orphan a snippet).
            try:
                rows = _read_status_rows(conn, "roadmap")
            except sqlite3.OperationalError as legacy_exc:
                if "no such table" in str(legacy_exc):
                    return {}
                raise
    finally:
        conn.close()

    status_map: dict[str, str] = {}
    for slug, raw_status in rows:
        if not isinstance(slug, str) or not isinstance(raw_status, str):
            continue
        try:
            status = TodoStatus(raw_status)
        except ValueError:
            continue
        if status not in _TODO_STATUS_VALUES:
            continue
        current_raw = status_map.get(slug)
        if current_raw is None:
            status_map[slug] = status.value
            continue
        current = TodoStatus(current_raw)
        if _TODO_STATUS_PRIORITY[status] > _TODO_STATUS_PRIORITY[current]:
            status_map[slug] = status.value
    return status_map
