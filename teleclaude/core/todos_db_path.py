"""Canonical todos.db path resolution, kept ORM-free.

Lives outside the ``todos_db`` package so light callers — snippet validation and
doc distribution — can resolve the canonical path without importing the todos
ORM stack (sqlalchemy/sqlmodel) that ``todos_db/__init__`` eagerly loads. The
``todos_db`` package re-exports it, so existing ``from teleclaude.core.todos_db
import todos_db_path`` callers are unaffected.
"""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.checkout_roots import resolve_checkout_roots

_GITHUB_WORKING_COPY_FILENAME = "todos.github.db"


def todos_db_path(project_root_or_cwd: str | Path) -> Path:
    """Canonical todos.db path at the resolved state root — the single source of truth.

    Every todos.db access (getters, raw-sqlite readers, existence checks) routes
    through here. Constructing the path inline from a raw project root bypasses
    the checkout-root resolver and can materialize a stray db inside a git worktree.
    """
    roots = resolve_checkout_roots(project_root_or_cwd)
    return roots.workflow_state / ".teleclaude" / "todos.db"


def github_working_copy_path(project_root_or_cwd: str | Path) -> Path:
    """Return the disposable SQLite working-copy path beside the local store."""
    return todos_db_path(project_root_or_cwd).with_name(_GITHUB_WORKING_COPY_FILENAME)
