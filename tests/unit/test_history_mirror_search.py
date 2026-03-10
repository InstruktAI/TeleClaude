"""Unit tests for mirror-backed history search and show flows."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.history.search import display_combined_history, show_transcript


def _create_mirror_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE mirrors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
                source_identity TEXT,
                computer TEXT NOT NULL,
                agent TEXT NOT NULL,
                project TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                timestamp_start TEXT,
                timestamp_end TEXT,
                conversation_text TEXT NOT NULL DEFAULT '',
                message_count INTEGER NOT NULL DEFAULT 0,
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE mirrors_fts USING fts5(
                title, conversation_text,
                content='mirrors',
                content_rowid='id'
            );
            CREATE TRIGGER mirrors_ai AFTER INSERT ON mirrors BEGIN
                INSERT INTO mirrors_fts(rowid, title, conversation_text)
                VALUES (new.id, new.title, new.conversation_text);
            END;
            CREATE TRIGGER mirrors_ad AFTER DELETE ON mirrors BEGIN
                INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
                VALUES('delete', old.id, old.title, old.conversation_text);
            END;
            CREATE TRIGGER mirrors_au AFTER UPDATE ON mirrors BEGIN
                INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
                VALUES('delete', old.id, old.title, old.conversation_text);
                INSERT INTO mirrors_fts(rowid, title, conversation_text)
                VALUES (new.id, new.title, new.conversation_text);
            END;
            """
        )


def _insert_mirror(db_path: Path, *, transcript_path: Path) -> None:
    now = "2026-03-01T10:00:00Z"
    metadata = json.dumps({"transcript_path": str(transcript_path)})
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO mirrors (
                session_id, source_identity, computer, agent, project, title, timestamp_start, timestamp_end,
                conversation_text, message_count, metadata, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "sess-1",
                "claude:session.jsonl",
                "MozBook",
                "claude",
                "teleclaude",
                "Mirror search rollout",
                now,
                now,
                "User: please ship the mirror search rollout\nAssistant: switching history search to FTS5 mirrors",
                2,
                metadata,
                now,
                now,
            ),
        )


def test_display_combined_history_reads_local_mirrors(tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "teleclaude.db"
    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text('{"hello":"world"}\n', encoding="utf-8")
    _create_mirror_schema(db_path)
    _insert_mirror(db_path, transcript_path=transcript_path)
    monkeypatch.setenv("TELECLAUDE_DB_PATH", str(db_path))

    display_combined_history([AgentName.CLAUDE], "mirror rollout", limit=5)

    out = capsys.readouterr().out
    assert "Search results for 'mirror rollout'" in out
    assert "sess-1" in out
    assert "teleclaude" in out


def test_show_transcript_renders_mirror_text_by_default(
    tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    db_path = tmp_path / "teleclaude.db"
    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text('{"raw":"transcript"}\n', encoding="utf-8")
    _create_mirror_schema(db_path)
    _insert_mirror(db_path, transcript_path=transcript_path)
    monkeypatch.setenv("TELECLAUDE_DB_PATH", str(db_path))

    show_transcript([AgentName.CLAUDE], "sess-1")

    out = capsys.readouterr().out
    assert "Mirror search rollout" in out
    assert "User: please ship the mirror search rollout" in out
    assert '{"raw":"transcript"}' not in out


def test_show_transcript_raw_reads_transcript_file(tmp_path: Path, monkeypatch, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "teleclaude.db"
    transcript_path = tmp_path / "session.jsonl"
    transcript_path.write_text('{"raw":"transcript"}\n', encoding="utf-8")
    _create_mirror_schema(db_path)
    _insert_mirror(db_path, transcript_path=transcript_path)
    monkeypatch.setenv("TELECLAUDE_DB_PATH", str(db_path))

    show_transcript([AgentName.CLAUDE], "sess-1", raw=True)

    out = capsys.readouterr().out
    assert '{"raw":"transcript"}' in out


def test_display_combined_history_renders_remote_results(
    monkeypatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def fake_remote_search(base_url: str, computer: str, search_term: str, agents, limit: int) -> dict:
        assert base_url == "http://remote.local:8420"
        assert computer == "RemoteBox"
        assert search_term == "mirror rollout"
        return {
            "computer": computer,
            "rows": [
                {
                    "session_id": "remote-1",
                    "agent": "claude",
                    "project": "teleclaude",
                    "timestamp": "2026-03-01 10:00",
                    "topic": "remote mirror rollout",
                }
            ],
        }

    monkeypatch.setattr(
        "teleclaude.history.search._resolve_remote_computer_urls",
        lambda computers: ({"RemoteBox": "http://remote.local:8420"}, {}),
    )
    monkeypatch.setattr("teleclaude.history.search._remote_search", fake_remote_search)

    display_combined_history([AgentName.CLAUDE], "mirror rollout", limit=5, computers=["RemoteBox"])

    out = capsys.readouterr().out
    assert "RemoteBox" in out
    assert "remote-1" in out
