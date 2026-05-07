"""Helpers for logical todo artifact names and persistence delegation."""

from __future__ import annotations

from pathlib import Path

from teleclaude.core.todos_db import get_todos_db_sync


def artifact_display_filename(artifact_name: str) -> str:
    """Return the user-facing artifact name without inventing a file extension."""
    return artifact_name


def read_artifact_content(project_root: Path, slug: str, artifact_name: str) -> str:
    """Read a todo artifact through the TodosDb sync API."""
    return get_todos_db_sync(project_root).read_artifact_sync(slug, artifact_name)


def write_artifact_content(project_root: Path, slug: str, artifact_name: str, content: str) -> None:
    """Write a todo artifact through the TodosDb sync API and append version history."""
    get_todos_db_sync(project_root).write_artifact_sync(
        slug, artifact_name, content, updated_by="teleclaude.cli.editor"
    )
