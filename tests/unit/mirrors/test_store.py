from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.mirrors import store as store_module

pytestmark = pytest.mark.unit


def _prepare_store_db(path: Path) -> None:
    """Trigger schema auto-creation via _connect_rw, then add a sessions table for context lookups."""
    from teleclaude.mirrors.store import _connect_rw  # pylint: disable=import-outside-toplevel

    with _connect_rw(str(path)) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT,
                computer_name TEXT,
                active_agent TEXT,
                project_path TEXT,
                native_log_file TEXT,
                human_email TEXT,
                visibility TEXT,
                last_input_origin TEXT,
                adapter_metadata TEXT,
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
    """No-op — FTS triggers auto-index on insert/update."""
    _ = (path, record)


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


class TestHistoryRoleAwareSpecs:
    def test_list_mirrors_matches_source_identity_or_human_email(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mirrors.sqlite"
        _prepare_store_db(db_path)

        email_record = cast(Any, store_module.MirrorRecord)(
            session_id="session-email",
            source_identity="claude:alpha/session-email.jsonl",
            computer="mac",
            agent="claude",
            project="alpha",
            title="email-backed",
            timestamp_start="2025-01-01T00:00:00+00:00",
            timestamp_end="2025-01-01T00:01:00+00:00",
            conversation_text="User: hello",
            message_count=1,
            summary="Email summary",
            human_email="customer@example.com",
            visibility="private",
            metadata={"transcript_path": str(tmp_path / "session-email.jsonl")},
            created_at="2025-01-01T00:00:00+00:00",
            updated_at="2025-01-01T00:01:00+00:00",
        )
        key_record = cast(Any, store_module.MirrorRecord)(
            session_id="session-key",
            source_identity="telegram:1285425702",
            computer="mac",
            agent="claude",
            project="alpha",
            title="channel-backed",
            timestamp_start="2025-01-02T00:00:00+00:00",
            timestamp_end="2025-01-02T00:01:00+00:00",
            conversation_text="User: ping",
            message_count=1,
            summary="Channel summary",
            human_email=None,
            visibility="private",
            metadata={"transcript_path": str(tmp_path / "session-key.jsonl")},
            created_at="2025-01-02T00:00:00+00:00",
            updated_at="2025-01-02T00:01:00+00:00",
        )

        store_module.upsert_mirror(email_record, db=str(db_path))
        store_module.upsert_mirror(key_record, db=str(db_path))

        email_results = cast(Any, store_module).list_mirrors(identity="customer@example.com", db=str(db_path))
        key_results = cast(Any, store_module).list_mirrors(identity="telegram:1285425702", db=str(db_path))

        assert [row.session_id for row in email_results] == ["session-email"]
        assert [row.session_id for row in key_results] == ["session-key"]

    def test_get_mirror_allows_member_owned_or_shared_records(self, tmp_path: Path) -> None:
        db_path = tmp_path / "mirrors.sqlite"
        _prepare_store_db(db_path)

        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO mirrors (
                    session_id, source_identity, computer, agent, project, title, timestamp_start,
                    timestamp_end, conversation_text, message_count, summary, human_email, visibility,
                    metadata, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "shared-session",
                    "claude:alpha/shared-session.jsonl",
                    "mac",
                    "claude",
                    "alpha",
                    "Shared",
                    "2025-01-01T00:00:00+00:00",
                    "2025-01-01T00:05:00+00:00",
                    "body",
                    1,
                    "summary",
                    "owner@example.com",
                    "shared",
                    "{}",
                    "2025-01-01T00:00:00+00:00",
                    "2025-01-01T00:05:00+00:00",
                ),
            )
            conn.commit()

        mirror = cast(Any, store_module.get_mirror)(
            "shared-session",
            caller_email="member@example.com",
            caller_role="member",
            db=str(db_path),
        )

        assert mirror is not None
        assert mirror.session_id == "shared-session"
