"""Canonical todos.db path resolution, kept ORM-free.

Lives outside the ``todos_db`` package so light callers — snippet validation and
doc distribution — can resolve the canonical path without importing the todos
ORM stack (sqlalchemy/sqlmodel) that ``todos_db/__init__`` eagerly loads. The
``todos_db`` package re-exports it, so existing ``from teleclaude.core.todos_db
import todos_db_path`` callers are unaffected.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.project_root import resolve_state_root


def todos_db_path(project_root_or_cwd: str | Path) -> Path:
    """Canonical todos.db path at the resolved state root — the single source of truth.

    Every todos.db access (getters, raw-sqlite readers, existence checks) routes
    through here. Constructing the path inline from a raw project root bypasses
    ``resolve_state_root`` and can materialize a stray db inside a git worktree.
    """
    return resolve_state_root(project_root_or_cwd) / ".teleclaude" / "todos.db"
