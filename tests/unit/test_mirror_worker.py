"""Unit tests for mirror worker reconciliation."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.mirrors.worker import MirrorWorker, TranscriptCandidate


def _create_mirror_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE mirrors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL UNIQUE,
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


def _write_jsonl(path: Path) -> None:
    entries = [
        {
            "type": "human",
            "timestamp": "2026-03-01T10:00:00Z",
            "message": {"role": "user", "content": "Need mirror reconciliation."},
        },
        {
            "type": "assistant",
            "timestamp": "2026-03-01T10:00:05Z",
            "message": {"role": "assistant", "content": [{"type": "text", "text": "Worker will rebuild it."}]},
        },
    ]
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


@pytest.mark.asyncio
async def test_mirror_worker_processes_new_transcript_and_skips_unchanged(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "teleclaude.db"
    transcript_path = tmp_path / "session.jsonl"
    _create_mirror_schema(db_path)
    _write_jsonl(transcript_path)

    monkeypatch.setattr(
        "teleclaude.mirrors.worker._discover_transcripts",
        lambda: [TranscriptCandidate(path=transcript_path, agent=AgentName.CLAUDE)],
    )

    worker = MirrorWorker(db=str(db_path), interval_s=1)
    processed_first = await worker.run_once()
    processed_second = await worker.run_once()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT session_id, message_count FROM mirrors WHERE conversation_text LIKE '%mirror reconciliation%'"
        ).fetchone()

    assert processed_first == 1
    assert processed_second == 0
    assert row is not None
    assert row[1] == 2
