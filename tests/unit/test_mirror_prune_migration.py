"""Unit tests for pruning non-canonical mirror rows."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import aiosqlite
import pytest


def _load_migration(filename: str):
    migrations_dir = Path(__file__).resolve().parents[2] / "teleclaude" / "core" / "migrations"
    path = migrations_dir / filename
    assert path.exists(), f"missing migration: {filename}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _seed_mirror(
    conn: aiosqlite.Connection,
    *,
    session_id: str,
    agent: str,
    transcript_path: str,
    title: str,
) -> None:
    payload = json.dumps({"transcript_path": transcript_path, "agent": agent})
    await conn.execute(
        """
        INSERT INTO mirrors (
            session_id,
            computer,
            agent,
            project,
            title,
            timestamp_start,
            timestamp_end,
            conversation_text,
            message_count,
            metadata,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            session_id,
            "MozBook",
            agent,
            "teleclaude",
            title,
            "2026-03-01T10:00:00Z",
            "2026-03-01T10:00:01Z",
            f"User: {title}",
            1,
            payload,
            "2026-03-01T10:00:00Z",
            "2026-03-01T10:00:01Z",
        ),
    )


@pytest.mark.asyncio
async def test_prune_non_canonical_mirror_migration_removes_only_non_canonical_rows(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    mirrors_migration = _load_migration("026_add_mirrors_table.py")
    prune_migration = _load_migration("027_prune_non_canonical_mirrors.py")

    async with aiosqlite.connect(db_path) as conn:
        await mirrors_migration.up(conn)
        await _seed_mirror(
            conn,
            session_id="claude-1",
            agent="claude",
            transcript_path=str(tmp_path / "claude" / "projects" / "team" / "session.jsonl"),
            title="canonical claude",
        )
        await _seed_mirror(
            conn,
            session_id="claude-2",
            agent="claude",
            transcript_path=str(
                tmp_path / "claude" / "projects" / "team" / "subagents" / "worker" / "session.jsonl"
            ),
            title="subagent claude",
        )
        await _seed_mirror(
            conn,
            session_id="codex-1",
            agent="codex",
            transcript_path=str(tmp_path / "codex" / "sessions" / "session.jsonl"),
            title="canonical codex",
        )
        await _seed_mirror(
            conn,
            session_id="codex-2",
            agent="codex",
            transcript_path=str(tmp_path / ".codex" / ".history" / "sessions" / "session.jsonl"),
            title="history codex",
        )
        await conn.commit()

        await prune_migration.up(conn)

        rows = await (
            await conn.execute("SELECT session_id, title FROM mirrors ORDER BY session_id")
        ).fetchall()
        fts_rows = await (
            await conn.execute("SELECT rowid FROM mirrors_fts WHERE mirrors_fts MATCH 'canonical OR subagent OR history'")
        ).fetchall()

    assert [(row[0], row[1]) for row in rows] == [
        ("claude-1", "canonical claude"),
        ("codex-1", "canonical codex"),
    ]
    assert len(fts_rows) == 2
