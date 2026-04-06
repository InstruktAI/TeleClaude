"""Helpers for logical todo artifact names and lightweight DB persistence."""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


def _resolve_artifact_row_id(conn: sqlite3.Connection, slug: str) -> str:
    """Resolve a todo slug to the current roadmap row id used by artifact tables."""
    row = conn.execute(
        "SELECT id FROM roadmap WHERE slug = ? AND status != 'delivered' LIMIT 1",  # guard: raw-sql
        (slug,),
    ).fetchone()
    return row[0] if row else slug


def artifact_display_filename(artifact_name: str) -> str:
    """Return the user-facing artifact name without inventing a file extension."""
    return artifact_name


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def read_artifact_content(project_root: Path, slug: str, artifact_name: str) -> str:
    """Read a todo artifact directly from todos.db without importing the full TodosDb stack."""
    db_path = project_root / ".teleclaude" / "todos.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Todos DB not found: {db_path}")
    conn = sqlite3.connect(db_path)
    try:
        row_id = _resolve_artifact_row_id(conn, slug)
        row = conn.execute(
            "SELECT content FROM todo_artifacts WHERE id = ? AND name = ?",  # guard: raw-sql
            (row_id, artifact_name),
        ).fetchone()
        return "" if row is None else str(row[0])
    finally:
        conn.close()


def write_artifact_content(project_root: Path, slug: str, artifact_name: str, content: str) -> None:
    """Write a todo artifact directly to todos.db and append version history."""
    db_path = project_root / ".teleclaude" / "todos.db"
    if not db_path.exists():
        raise FileNotFoundError(f"Todos DB not found: {db_path}")
    now = datetime.now(UTC).isoformat()
    digest = _sha256(content)
    conn = sqlite3.connect(db_path)
    try:
        row_id = _resolve_artifact_row_id(conn, slug)
        conn.execute(
            "INSERT INTO todo_artifact_versions "  # guard: raw-sql
            "(id, slug, name, content, digest, updated_by, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (row_id, slug, artifact_name, content, digest, "teleclaude.cli.editor", now),
        )
        conn.execute(
            "INSERT INTO todo_artifacts "
            "(id, slug, name, content, digest, updated_by, updated_at) "  # guard: raw-sql
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(id, name) DO UPDATE SET "
            "content = excluded.content, digest = excluded.digest, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (row_id, slug, artifact_name, content, digest, "teleclaude.cli.editor", now),
        )
        conn.commit()
    finally:
        conn.close()
