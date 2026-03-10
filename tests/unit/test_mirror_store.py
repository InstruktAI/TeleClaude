"""Unit tests for mirror store source-identity behavior."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import aiosqlite
import pytest

from teleclaude.mirrors.store import MirrorRecord, delete_mirror, get_mirror, upsert_mirror


def _load_migration(filename: str):
    migrations_dir = Path(__file__).resolve().parents[2] / "teleclaude" / "core" / "migrations"
    path = migrations_dir / filename
    assert path.exists(), f"missing migration: {filename}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _apply_migration(db_path: Path, *filenames: str) -> None:
    async with aiosqlite.connect(db_path) as conn:
        for filename in filenames:
            await _load_migration(filename).up(conn)


@pytest.mark.asyncio
async def test_mirror_source_identity_migration_is_reversible(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    await _apply_migration(db_path, "026_add_mirrors_table.py")

    metadata = json.dumps(
        {
            "agent": "claude",
            "transcript_path": str(tmp_path / ".claude" / "projects" / "team" / "session.jsonl"),
        }
    )
    async with aiosqlite.connect(db_path) as conn:
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
                "sess-1",
                "MozBook",
                "claude",
                "teleclaude",
                "Mirror title",
                "2026-03-01T10:00:00Z",
                "2026-03-01T10:00:01Z",
                "User: hello",
                1,
                metadata,
                "2026-03-01T10:00:00Z",
                "2026-03-01T10:00:01Z",
            ),
        )
        await conn.commit()

        migration = _load_migration("028_add_mirror_source_identity.py")
        await migration.up(conn)

        columns = [row[1] for row in await (await conn.execute("PRAGMA table_info(mirrors)")).fetchall()]
        row = await (await conn.execute("SELECT session_id, source_identity FROM mirrors")).fetchone()

        assert "source_identity" in columns
        assert row == ("sess-1", "claude:team/session.jsonl")

        await migration.down(conn)

        columns_after_down = [row[1] for row in await (await conn.execute("PRAGMA table_info(mirrors)")).fetchall()]
        assert "source_identity" not in columns_after_down


@pytest.mark.asyncio
async def test_mirror_source_identity_down_migration_deduplicates_duplicate_session_ids(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    await _apply_migration(db_path, "026_add_mirrors_table.py", "028_add_mirror_source_identity.py")

    async with aiosqlite.connect(db_path) as conn:
        await conn.executemany(
            """
            INSERT INTO mirrors (
                session_id,
                source_identity,
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
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "sess-1",
                    "claude:team/session-a.jsonl",
                    "MozBook",
                    "claude",
                    "teleclaude",
                    "Older row",
                    "2026-03-01T10:00:00Z",
                    "2026-03-01T10:00:01Z",
                    "User: hello",
                    1,
                    json.dumps({"transcript_path": str(tmp_path / "session-a.jsonl")}),
                    "2026-03-01T10:00:00Z",
                    "2026-03-01T10:00:01Z",
                ),
                (
                    "sess-1",
                    "claude:team/session-b.jsonl",
                    "MozBook",
                    "claude",
                    "teleclaude",
                    "Newer row",
                    "2026-03-01T10:05:00Z",
                    "2026-03-01T10:05:01Z",
                    "User: newer",
                    2,
                    json.dumps({"transcript_path": str(tmp_path / "session-b.jsonl")}),
                    "2026-03-01T10:05:00Z",
                    "2026-03-01T10:05:01Z",
                ),
            ],
        )
        await conn.commit()

        migration = _load_migration("028_add_mirror_source_identity.py")
        await migration.down(conn)

        rows = await (
            await conn.execute(
                "SELECT session_id, title, updated_at FROM mirrors ORDER BY updated_at DESC, session_id"
            )
        ).fetchall()

    assert rows == [("sess-1", "Newer row", "2026-03-01T10:05:01Z")]


def test_upsert_get_and_delete_mirror_by_source_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    import asyncio

    asyncio.run(_apply_migration(db_path, "026_add_mirrors_table.py", "028_add_mirror_source_identity.py"))

    initial = MirrorRecord(
        session_id="sess-1",
        source_identity="claude:team/session.jsonl",
        computer="MozBook",
        agent="claude",
        project="teleclaude",
        title="Initial title",
        timestamp_start="2026-03-01T10:00:00Z",
        timestamp_end="2026-03-01T10:00:01Z",
        conversation_text="User: initial",
        message_count=1,
        metadata={"transcript_path": str(tmp_path / ".claude" / "projects" / "team" / "session.jsonl")},
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:01Z",
    )
    updated = MirrorRecord(
        session_id="sess-1",
        source_identity="claude:team/session.jsonl",
        computer="MozBook",
        agent="claude",
        project="teleclaude",
        title="Updated title",
        timestamp_start="2026-03-01T10:00:00Z",
        timestamp_end="2026-03-01T10:05:00Z",
        conversation_text="User: updated",
        message_count=2,
        metadata={"transcript_path": str(tmp_path / ".claude" / "projects" / "team" / "session.jsonl")},
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:05:00Z",
    )

    upsert_mirror(initial, db=str(db_path))
    upsert_mirror(updated, db=str(db_path))

    mirror = get_mirror(source_identity="claude:team/session.jsonl", db=str(db_path))

    assert mirror is not None
    assert mirror.title == "Updated title"
    assert mirror.message_count == 2

    delete_mirror(source_identity="claude:team/session.jsonl", db=str(db_path))

    assert get_mirror(source_identity="claude:team/session.jsonl", db=str(db_path)) is None


def test_upsert_mirror_requires_source_identity(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    import asyncio

    asyncio.run(_apply_migration(db_path, "026_add_mirrors_table.py", "028_add_mirror_source_identity.py"))

    record = MirrorRecord(
        session_id="sess-1",
        source_identity=None,
        computer="MozBook",
        agent="claude",
        project="teleclaude",
        title="Missing key",
        timestamp_start="2026-03-01T10:00:00Z",
        timestamp_end="2026-03-01T10:00:01Z",
        conversation_text="User: hello",
        message_count=1,
        metadata={"transcript_path": str(tmp_path / "session.jsonl")},
        created_at="2026-03-01T10:00:00Z",
        updated_at="2026-03-01T10:00:01Z",
    )

    with pytest.raises(ValueError, match="source_identity"):
        upsert_mirror(record, db=str(db_path))
