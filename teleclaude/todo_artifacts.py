"""Helpers for logical todo artifact names and persistence delegation."""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.todos_db import get_todos_db_sync


def artifact_display_filename(artifact_name: str) -> str:
    """Return the user-facing artifact name without inventing a file extension."""
    return artifact_name


def _require_todos_db(project_root: Path) -> Path:
    """Refuse silent DB creation: artifact ops require the project DB to exist."""
    db_path = project_root / ".teleclaude" / "todos.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Todos DB not found: {db_path}")
    return db_path


def read_artifact_content(project_root: Path, slug: str, artifact_name: str) -> str:
    """Read a todo artifact through the TodosDb sync API."""
    _require_todos_db(project_root)
    return get_todos_db_sync(project_root).read_artifact_sync(slug, artifact_name)


def write_artifact_content(project_root: Path, slug: str, artifact_name: str, content: str) -> None:
    """Write a todo artifact through the TodosDb sync API and append version history."""
    _require_todos_db(project_root)
    get_todos_db_sync(project_root).write_artifact_sync(
        slug, artifact_name, content, updated_by="teleclaude.cli.editor"
    )
