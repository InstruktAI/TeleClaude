"""Live todo status map for snippet validation and purge reconciliation.

Reads the todos.db substrate directly (no ORM bootstrap) to resolve which slugs
are live deliverers. Kept in its own module so the snippet validator stays under
the module-size guardrail.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from teleclaude.constants import TodoStatus
from teleclaude.core.todos_db_path import todos_db_path
from teleclaude.git import GitCommandError, Repo

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
_REV_PARSE_VERIFY = "--verify"
_REV_PARSE_QUIET = "--quiet"
_COMMIT_REVISION_SUFFIX = "^{commit}"


@dataclass(frozen=True)
class TodoStatusFact:
    """Validation-relevant state for one todo slug."""

    status: TodoStatus
    delivered_commit: str | None


def _read_status_rows(conn: sqlite3.Connection, owner_table: str) -> list[tuple[object, object, object]]:
    """Read todo facts for live deliverers from the substrate owner table.

    A real todo exists in ``todo_state``; the owner table (``todo`` post-rename,
    legacy ``roadmap`` on un-migrated DBs) also retains delivered/removed status
    rows that lack a ``todo_state`` row, until ``v2-workflow-drop-roadmap``
    migrates the v1 substrate. Join so orphaned owner rows with no real todo are
    excluded — otherwise a phantom slug would read as a live deliverer.
    """
    return conn.execute(
        f"SELECT r.slug, r.status, r.delivered_commit FROM {owner_table} r "  # guard: raw-sql - owner table resolved by caller
        "JOIN todo_state ts ON ts.slug = r.slug "
        "WHERE r.status IN (?, ?, ?, ?)",
        _TODO_STATUS_VALUES,
    ).fetchall()


def build_todo_status_facts(project_root: Path) -> dict[str, TodoStatusFact]:
    """Read todo facts once for checkout-aware snippet validation.

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

    facts: dict[str, TodoStatusFact] = {}
    for slug, raw_status, raw_delivered_commit in rows:
        if not isinstance(slug, str) or not isinstance(raw_status, str):
            continue
        try:
            status = TodoStatus(raw_status)
        except ValueError:
            continue
        if status not in _TODO_STATUS_VALUES:
            continue
        delivered_commit = raw_delivered_commit if isinstance(raw_delivered_commit, str) else None
        current = facts.get(slug)
        if current is None or _TODO_STATUS_PRIORITY[status] > _TODO_STATUS_PRIORITY[current.status]:
            facts[slug] = TodoStatusFact(status=status, delivered_commit=delivered_commit)
    return facts


def build_todo_status_map(project_root: Path) -> dict[str, str]:
    """Read todo slug status once for reconciliation consumers."""
    return {slug: fact.status.value for slug, fact in build_todo_status_facts(project_root).items()}


def is_pending_marker_stale(
    slug: str,
    todo_status_facts: Mapping[str, TodoStatusFact],
    project_root: Path,
) -> bool:
    """Return whether a delivered marker should already be folded in this checkout."""
    fact = todo_status_facts.get(slug)
    if fact is None or fact.status is not TodoStatus.DELIVERED or fact.delivered_commit is None:
        return False
    repository = Repo(project_root)
    try:
        repository.git.rev_parse(_REV_PARSE_VERIFY, _REV_PARSE_QUIET, fact.delivered_commit + _COMMIT_REVISION_SUFFIX)
    except GitCommandError as exc:
        if exc.status == 1:
            return False
        raise
    delivered_commit = repository.commit(fact.delivered_commit)
    return repository.is_ancestor(delivered_commit, repository.head.commit)
