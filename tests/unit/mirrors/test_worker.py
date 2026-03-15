from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude.core.agents import AgentName
from teleclaude.mirrors import worker as worker_module
from teleclaude.utils.transcript_discovery import TranscriptCandidate

pytestmark = pytest.mark.unit


def _prepare_worker_db(path: Path) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE mirrors (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                source_identity TEXT UNIQUE,
                agent TEXT,
                metadata TEXT
            );
            CREATE TABLE mirror_tombstones (
                source_identity TEXT PRIMARY KEY,
                agent TEXT,
                transcript_path TEXT,
                file_size INTEGER,
                file_mtime TEXT,
                created_at TEXT
            );
            """
        )
        conn.commit()


class TestMirrorWorker:
    async def test_run_once_offloads_reconcile_sync_to_thread(self, monkeypatch: pytest.MonkeyPatch) -> None:
        expected = worker_module.ReconcileResult(
            discovered=1,
            processed=1,
            failed=0,
            skipped_unchanged=0,
            duration_s=0.5,
        )
        thread_calls: list[object] = []

        async def fake_to_thread(func: object) -> worker_module.ReconcileResult:
            thread_calls.append(func)
            return expected

        monkeypatch.setattr(worker_module.asyncio, "to_thread", fake_to_thread)

        worker = worker_module.MirrorWorker(db="mirrors.sqlite")
        result = await worker.run_once()

        assert result == expected
        assert thread_calls == [worker._reconcile_sync]

    def test_backfill_sync_removes_rows_without_source_identity_or_noncanonical_transcript(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "mirrors.sqlite"
        _prepare_worker_db(db_path)

        with sqlite3.connect(db_path) as conn:
            conn.executemany(
                "INSERT INTO mirrors (id, session_id, source_identity, agent, metadata) VALUES (?, ?, ?, ?, ?)",
                [
                    (1, "session-1", None, "claude", "{}"),
                    (2, "session-2", "claude:/tmp/drop.jsonl", "claude", '{"transcript_path":"/tmp/drop.jsonl"}'),
                    (3, "session-3", "claude:/tmp/keep.jsonl", "claude", '{"transcript_path":"/tmp/keep.jsonl"}'),
                ],
            )
            conn.commit()

        expected = worker_module.ReconcileResult(
            discovered=0,
            processed=0,
            failed=0,
            skipped_unchanged=0,
            duration_s=0.0,
        )
        monkeypatch.setattr(worker_module, "in_session_root", lambda path, agent: path == "/tmp/keep.jsonl")
        monkeypatch.setattr(worker_module.MirrorWorker, "_reconcile_sync", lambda self: expected)

        worker = worker_module.MirrorWorker(db=str(db_path))
        result = worker.backfill_sync()

        assert result == expected
        with sqlite3.connect(db_path) as conn:
            remaining_ids = [row[0] for row in conn.execute("SELECT id FROM mirrors ORDER BY id").fetchall()]
        assert remaining_ids == [3]

    def test_reconcile_sync_records_tombstones_for_empty_transcripts(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "mirrors.sqlite"
        _prepare_worker_db(db_path)

        session_dir = tmp_path / "team-alpha"
        session_dir.mkdir()
        transcript_one = session_dir / "session-1.jsonl"
        transcript_two = session_dir / "session-2.jsonl"
        transcript_one.write_text("one", encoding="utf-8")
        transcript_two.write_text("two", encoding="utf-8")

        candidates = [
            TranscriptCandidate(path=transcript_one, agent=AgentName.CLAUDE, mtime=transcript_one.stat().st_mtime),
            TranscriptCandidate(path=transcript_two, agent=AgentName.CLAUDE, mtime=transcript_two.stat().st_mtime),
        ]

        monkeypatch.setattr(worker_module, "get_mirror_state_by_transcript", lambda db: {})
        monkeypatch.setattr(worker_module, "_discover_transcripts", lambda: candidates)
        monkeypatch.setattr(
            worker_module,
            "generate_mirror_sync",
            lambda session_id, source_identity, transcript_path, agent_name, computer, project, db: (
                transcript_path.endswith("session-1.jsonl")
            ),
        )

        worker = worker_module.MirrorWorker(db=str(db_path))
        monkeypatch.setattr(worker, "_should_skip_tombstoned_transcript", lambda source_identity, candidate: False)
        monkeypatch.setattr(worker, "_log_reconcile_result", lambda result, wal_before_kb, wal_after_kb: None)

        result = worker._reconcile_sync()

        assert result.discovered == 2
        assert result.processed == 2
        assert result.failed == 0
        assert result.skipped_unchanged == 0

        with sqlite3.connect(db_path) as conn:
            tombstones = conn.execute(
                "SELECT transcript_path FROM mirror_tombstones ORDER BY transcript_path"
            ).fetchall()
        assert tombstones == [(str(transcript_two),)]
