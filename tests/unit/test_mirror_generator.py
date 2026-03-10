"""Unit tests for mirror generation and migration."""

from __future__ import annotations

import importlib.util
import json
import sqlite3
from pathlib import Path

import aiosqlite
import pytest

from teleclaude.core.agents import AgentName

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _load_mirror_migration():
    migrations_dir = Path(__file__).resolve().parents[2] / "teleclaude" / "core" / "migrations"
    candidates = sorted(migrations_dir.glob("*_add_mirrors_table.py"))
    assert candidates, "mirror migration file is missing"
    path = candidates[0]
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration(filename: str):
    migrations_dir = Path(__file__).resolve().parents[2] / "teleclaude" / "core" / "migrations"
    path = migrations_dir / filename
    assert path.exists(), f"missing migration: {filename}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _apply_mirror_runtime_migrations(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as conn:
        for filename in (
            "026_add_mirrors_table.py",
            "028_add_mirror_source_identity.py",
            "029_add_mirror_tombstones.py",
        ):
            await _load_migration(filename).up(conn)


def _write_jsonl(path: Path, entries: list[dict[str, JsonValue]]) -> str:
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")
    return str(path)


@pytest.mark.asyncio
async def test_mirror_migration_up_and_down(tmp_path: Path) -> None:
    migration = _load_mirror_migration()
    db_path = tmp_path / "teleclaude.db"

    async with aiosqlite.connect(db_path) as conn:
        await migration.up(conn)

        names = {
            row[0]
            for row in await (await conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'mirrors%'")).fetchall()
        }
        assert "mirrors" in names
        assert "mirrors_fts" in names

        triggers = {
            row[0]
            for row in await (
                await conn.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'mirrors_%'")
            ).fetchall()
        }
        assert triggers == {"mirrors_ad", "mirrors_ai", "mirrors_au"}

        await migration.down(conn)
        remaining = await (
            await conn.execute("SELECT name FROM sqlite_master WHERE name LIKE 'mirrors%' OR name LIKE 'idx_mirrors_%'")
        ).fetchall()
        assert remaining == []


@pytest.mark.asyncio
async def test_generate_mirror_strips_system_reminders_and_tool_noise(tmp_path: Path) -> None:
    from teleclaude.mirrors.generator import generate_mirror

    db_path = tmp_path / "teleclaude.db"
    await _apply_mirror_runtime_migrations(db_path)

    transcript_path = _write_jsonl(
        tmp_path / "session.jsonl",
        [
            {
                "type": "human",
                "timestamp": "2026-03-01T10:00:00Z",
                "message": {
                    "role": "user",
                    "content": (
                        "<system-reminder>internal</system-reminder>\n"
                        "Need the daemon search to use mirrors instead of scans."
                    ),
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-01T10:00:05Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": "I will switch the search path to FTS5 mirrors."}],
                },
            },
            {
                "type": "assistant",
                "timestamp": "2026-03-01T10:00:06Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "history.py"}}],
                },
            },
        ],
    )

    await generate_mirror(
        session_id="sess-1",
        source_identity="claude:session.jsonl",
        transcript_path=transcript_path,
        agent_name=AgentName.CLAUDE,
        computer="MozBook",
        project="teleclaude",
        db=str(db_path),
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT title, conversation_text, message_count, agent, computer, project FROM mirrors WHERE session_id = ?",
            ("sess-1",),
        ).fetchone()

    assert row is not None
    assert row[0] == "Need the daemon search to use mirrors instead of scans."
    assert "<system-reminder>" not in row[1]
    assert "tool_use" not in row[1]
    assert "Read" not in row[1]
    assert "Need the daemon search to use mirrors instead of scans." in row[1]
    assert "I will switch the search path to FTS5 mirrors." in row[1]
    assert row[2] == 2
    assert row[3:] == ("claude", "MozBook", "teleclaude")


@pytest.mark.asyncio
async def test_generate_mirror_skips_tool_only_transcript(tmp_path: Path) -> None:
    from teleclaude.mirrors.generator import generate_mirror

    db_path = tmp_path / "teleclaude.db"
    await _apply_mirror_runtime_migrations(db_path)

    transcript_path = _write_jsonl(
        tmp_path / "tool-only.jsonl",
        [
            {
                "type": "assistant",
                "timestamp": "2026-03-01T10:00:00Z",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "foo.py"}}],
                },
            },
            {
                "type": "human",
                "timestamp": "2026-03-01T10:00:01Z",
                "message": {
                    "role": "user",
                    "content": [{"type": "tool_result", "content": "print('hello')"}],
                },
            },
        ],
    )

    await generate_mirror(
        session_id="sess-2",
        source_identity="claude:tool-only.jsonl",
        transcript_path=transcript_path,
        agent_name=AgentName.CLAUDE,
        computer="MozBook",
        project="teleclaude",
        db=str(db_path),
    )

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM mirrors WHERE session_id = ?", ("sess-2",)).fetchone()[0]

    assert count == 0


@pytest.mark.asyncio
async def test_generate_mirror_offloads_sync_work(monkeypatch: pytest.MonkeyPatch) -> None:
    from teleclaude.mirrors import generator

    expected = True
    calls: list[object] = []

    def fake_generate_mirror_sync(**kwargs):
        assert kwargs["session_id"] == "sess-3"
        assert kwargs["source_identity"] == "claude:session.jsonl"
        return expected

    async def fake_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return func(*args, **kwargs)

    monkeypatch.setattr(generator, "generate_mirror_sync", fake_generate_mirror_sync)
    monkeypatch.setattr(generator.asyncio, "to_thread", fake_to_thread)

    result = await generator.generate_mirror(
        session_id="sess-3",
        source_identity="claude:session.jsonl",
        transcript_path="/tmp/session.jsonl",
        agent_name=AgentName.CLAUDE,
        computer="MozBook",
        project="teleclaude",
        db="/tmp/teleclaude.db",
    )

    assert result is expected
    assert calls == [fake_generate_mirror_sync]
