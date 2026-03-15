from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.mirrors import store as store_module

pytestmark = pytest.mark.unit


def _prepare_store_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE mirrors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                source_identity TEXT UNIQUE,
                computer TEXT,
                agent TEXT,
                project TEXT,
                title TEXT,
                timestamp_start TEXT,
                timestamp_end TEXT,
                conversation_text TEXT,
                message_count INTEGER,
                metadata TEXT,
                created_at TEXT,
                updated_at TEXT
            );
            CREATE VIRTUAL TABLE mirrors_fts USING fts5(title, conversation_text);
            CREATE TABLE mirror_tombstones (
                source_identity TEXT PRIMARY KEY,
                agent TEXT,
                transcript_path TEXT,
                file_size INTEGER,
                file_mtime TEXT,
                created_at TEXT
            );
            CREATE TABLE sessions (
                session_id TEXT,
                computer_name TEXT,
                active_agent TEXT,
                project_path TEXT,
                native_log_file TEXT,
                created_at TEXT
            );
            """
        )
        conn.commit()


def _mirror_record(transcript_path: str, session_id: str = "session-1") -> store_module.MirrorRecord:
    return store_module.MirrorRecord(
        session_id=session_id,
        source_identity=f"claude:{transcript_path}",
        computer="mac",
        agent="claude",
        project="alpha",
        title="hello mirror",
        timestamp_start="2025-01-01T00:00:00+00:00",
        timestamp_end="2025-01-01T00:01:00+00:00",
        conversation_text="User: hello\n\nAssistant: hi",
        message_count=2,
        metadata={"transcript_path": transcript_path},
        created_at="2025-01-01T00:00:00+00:00",
        updated_at="2025-01-01T00:01:00+00:00",
    )


def _index_mirror_for_search(path: Path, record: store_module.MirrorRecord) -> None:
    with sqlite3.connect(path) as conn:
        row = conn.execute("SELECT id FROM mirrors WHERE source_identity = ?", (record.source_identity,)).fetchone()
        assert row is not None
        conn.execute(
            "INSERT INTO mirrors_fts(rowid, title, conversation_text) VALUES (?, ?, ?)",
            (int(row[0]), record.title, record.conversation_text),
        )
        conn.commit()


class TestResolveDbPath:
    def test_resolve_db_path_supports_path_string_and_db_like_objects(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mirrors.sqlite"

        assert store_module.resolve_db_path(db_path) == str(db_path)
        assert store_module.resolve_db_path(str(db_path)) == str(db_path)
        assert store_module.resolve_db_path(SimpleNamespace(db_path=db_path)) == str(db_path)


class TestMirrorStore:
    def test_upsert_get_and_delete_mirror_round_trip(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mirrors.sqlite"
        _prepare_store_db(db_path)
        record = _mirror_record(str(tmp_path / "session-1.jsonl"))

        store_module.upsert_mirror(record, db=str(db_path))

        fetched = store_module.get_mirror(source_identity=record.source_identity, db=str(db_path))
        fetched_by_prefix = store_module.get_mirror(session_id="session", db=str(db_path))

        assert fetched is not None
        assert fetched.title == record.title
        assert fetched.metadata["transcript_path"] == record.metadata["transcript_path"]
        assert fetched_by_prefix is not None
        assert fetched_by_prefix.session_id == "session-1"

        store_module.delete_mirror(source_identity=record.source_identity, db=str(db_path))

        assert store_module.get_mirror(source_identity=record.source_identity, db=str(db_path)) is None

    def test_search_mirrors_reads_from_fts_index_and_parses_metadata(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mirrors.sqlite"
        _prepare_store_db(db_path)
        record = _mirror_record(str(tmp_path / "session-1.jsonl"))

        store_module.upsert_mirror(record, db=str(db_path))
        _index_mirror_for_search(db_path, record)

        results = store_module.search_mirrors("hello", [AgentName.CLAUDE], limit=5, db=str(db_path))

        assert len(results) == 1
        assert results[0].session_id == "session-1"
        assert results[0].agent == "claude"
        assert results[0].metadata["transcript_path"] == record.metadata["transcript_path"]
        assert results[0].topic != ""

    def test_state_tombstones_and_session_context_round_trip(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mirrors.sqlite"
        transcript_path = str(tmp_path / "session-1.jsonl")
        _prepare_store_db(db_path)
        record = _mirror_record(transcript_path)

        store_module.upsert_mirror(record, db=str(db_path))

        state = store_module.get_mirror_state_by_transcript(str(db_path))
        assert state == {transcript_path: (record.source_identity, record.updated_at)}

        tombstone = store_module.MirrorTombstoneRecord(
            source_identity=record.source_identity or "",
            agent="claude",
            transcript_path=transcript_path,
            file_size=10,
            file_mtime="123456789",
            created_at="2025-01-01T00:02:00+00:00",
        )
        store_module.upsert_mirror_tombstone(tombstone, db=str(db_path))
        assert store_module.get_mirror_tombstone(tombstone.source_identity, db=str(db_path)) == tombstone

        store_module.delete_mirror_tombstone(tombstone.source_identity, db=str(db_path))
        assert store_module.get_mirror_tombstone(tombstone.source_identity, db=str(db_path)) is None

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO sessions (
                    session_id, computer_name, active_agent, project_path, native_log_file, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("session-1", "mac", "claude", "alpha", transcript_path, "2025-01-01T00:00:00+00:00"),
            )
            conn.commit()

        context = store_module.get_session_context(session_id="session-1", db=str(db_path))

        assert context is not None
        assert context.computer == "mac"
        assert context.project == "alpha"
        assert context.transcript_path == transcript_path
