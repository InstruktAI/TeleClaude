"""Unit tests for mirror worker reconciliation."""

from __future__ import annotations

import importlib.util
import asyncio
import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import aiosqlite
import pytest

from teleclaude.core.agents import AgentName
from teleclaude.mirrors.worker import MirrorWorker, ReconcileResult, TranscriptCandidate

JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _load_migration(filename: str):
    migrations_dir = Path(__file__).resolve().parents[2] / "teleclaude" / "core" / "migrations"
    path = migrations_dir / filename
    assert path.exists(), f"missing migration: {filename}"
    spec = importlib.util.spec_from_file_location(path.stem, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def _apply_mirror_migrations(db_path: Path) -> None:
    async with aiosqlite.connect(db_path) as conn:
        for filename in (
            "026_add_mirrors_table.py",
            "027_prune_non_canonical_mirrors.py",
            "028_add_mirror_source_identity.py",
            "029_add_mirror_tombstones.py",
        ):
            await _load_migration(filename).up(conn)


def _create_sessions_table(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                computer_name TEXT NOT NULL,
                active_agent TEXT,
                project_path TEXT,
                native_log_file TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _insert_session_context(
    db_path: Path,
    *,
    session_id: str,
    transcript_path: Path,
    agent: str = "claude",
    project: str = "teleclaude",
    computer: str = "MozBook",
) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id,
                computer_name,
                active_agent,
                project_path,
                native_log_file,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                computer,
                agent,
                project,
                str(transcript_path),
                "2026-03-01T10:00:00Z",
            ),
        )
        conn.commit()


def _write_jsonl(path: Path, entries: list[dict[str, JsonValue]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(json.dumps(entry) + "\n")


def _conversation_entries() -> list[dict[str, JsonValue]]:
    return [
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


def _tool_only_entries() -> list[dict[str, JsonValue]]:
    return [
        {
            "type": "assistant",
            "timestamp": "2026-03-01T10:00:00Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "foo.py"}}],
            },
        }
    ]


@pytest.mark.asyncio
async def test_run_once_offloads_reconciliation_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = MirrorWorker(db="/tmp/teleclaude.db", interval_s=1)
    expected = ReconcileResult(
        discovered=1,
        processed=1,
        failed=0,
        skipped_unchanged=0,
        skipped_no_context=0,
        duration_s=0.01,
    )
    calls: list[object] = []

    async def fake_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return expected

    monkeypatch.setattr("teleclaude.mirrors.worker.asyncio.to_thread", fake_to_thread)

    result = await worker.run_once()

    assert result == expected
    assert calls == [worker._reconcile_sync]


@pytest.mark.asyncio
async def test_run_cancels_cleanly_while_waiting_for_the_next_cycle(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = MirrorWorker(db="/tmp/teleclaude.db", interval_s=1)
    sleep_started = asyncio.Event()

    async def fake_sleep(_seconds: int) -> None:
        sleep_started.set()
        await asyncio.Future()

    run_once = AsyncMock(
        return_value=ReconcileResult(
            discovered=0,
            processed=0,
            failed=0,
            skipped_unchanged=0,
            skipped_no_context=0,
            duration_s=0.0,
        )
    )

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr("teleclaude.mirrors.worker.asyncio.sleep", fake_sleep)

    task = asyncio.create_task(worker.run())
    await sleep_started.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    run_once.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_logs_cycle_failures_and_continues(monkeypatch: pytest.MonkeyPatch) -> None:
    worker = MirrorWorker(db="/tmp/teleclaude.db", interval_s=1)
    sleep_calls = 0
    cycle_error = RuntimeError("db locked")

    async def fake_sleep(_seconds: int) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise asyncio.CancelledError

    run_once = AsyncMock(
        side_effect=[
            cycle_error,
            ReconcileResult(
                discovered=0,
                processed=0,
                failed=0,
                skipped_unchanged=0,
                skipped_no_context=0,
                duration_s=0.0,
            ),
        ]
    )
    logger_error = Mock()

    monkeypatch.setattr(worker, "run_once", run_once)
    monkeypatch.setattr("teleclaude.mirrors.worker.asyncio.sleep", fake_sleep)
    monkeypatch.setattr("teleclaude.mirrors.worker.logger.error", logger_error)

    with pytest.raises(asyncio.CancelledError):
        await worker.run()

    assert run_once.await_count == 2
    logger_error.assert_called_once_with("Mirror reconciliation cycle failed: %s", cycle_error, exc_info=True)


def test_reconcile_sync_processes_transcripts_reports_metrics_and_converges(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    transcript_path = tmp_path / ".claude" / "projects" / "teleclaude" / "session.jsonl"
    _write_jsonl(transcript_path, _conversation_entries())
    os.utime(transcript_path, (10, 10))

    import asyncio

    asyncio.run(_apply_mirror_migrations(db_path))
    _create_sessions_table(db_path)
    _insert_session_context(db_path, session_id="sess-1", transcript_path=transcript_path)

    monkeypatch.setattr(
        "teleclaude.mirrors.worker._discover_transcripts",
        lambda: [
            TranscriptCandidate(
                path=transcript_path,
                agent=AgentName.CLAUDE,
                mtime=transcript_path.stat().st_mtime,
            )
        ],
    )
    logger_info = Mock()
    monkeypatch.setattr("teleclaude.mirrors.worker.logger.info", logger_info)

    worker = MirrorWorker(db=str(db_path), interval_s=1)
    first = worker._reconcile_sync()
    second = worker._reconcile_sync()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT session_id, source_identity, message_count FROM mirrors WHERE conversation_text LIKE '%mirror reconciliation%'"
        ).fetchone()

    assert first.discovered == 1
    assert first.processed == 1
    assert first.failed == 0
    assert first.skipped_unchanged == 0
    assert first.skipped_no_context == 0
    assert first.duration_s >= 0
    assert second.processed == 0
    assert second.failed == 0
    assert second.skipped_unchanged == 1
    assert row == ("sess-1", "claude:teleclaude/session.jsonl", 2)
    assert any(
        "mirror.reconciliation.complete discovered=1 processed=1 failed=0 skipped_unchanged=0 skipped_no_context=0"
        in call.args[0]
        for call in logger_info.call_args_list
        if call.args
    )


def test_reconcile_sync_skips_candidates_without_session_context(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    transcript_path = tmp_path / ".claude" / "projects" / "teleclaude" / "missing.jsonl"
    _write_jsonl(transcript_path, _conversation_entries())
    os.utime(transcript_path, (10, 10))

    import asyncio

    asyncio.run(_apply_mirror_migrations(db_path))
    _create_sessions_table(db_path)

    monkeypatch.setattr(
        "teleclaude.mirrors.worker._discover_transcripts",
        lambda: [
            TranscriptCandidate(
                path=transcript_path,
                agent=AgentName.CLAUDE,
                mtime=transcript_path.stat().st_mtime,
            )
        ],
    )

    worker = MirrorWorker(db=str(db_path), interval_s=1)
    result = worker._reconcile_sync()

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM mirrors").fetchone()[0]

    assert result.discovered == 1
    assert result.processed == 0
    assert result.failed == 0
    assert result.skipped_no_context == 1
    assert count == 0


def test_reconcile_sync_continues_after_per_candidate_failure(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    broken_path = tmp_path / ".claude" / "projects" / "teleclaude" / "broken.jsonl"
    healthy_path = tmp_path / ".claude" / "projects" / "teleclaude" / "healthy.jsonl"
    _write_jsonl(broken_path, _conversation_entries())
    _write_jsonl(healthy_path, _conversation_entries())
    os.utime(broken_path, (10, 10))
    os.utime(healthy_path, (20, 20))

    import asyncio

    asyncio.run(_apply_mirror_migrations(db_path))
    _create_sessions_table(db_path)
    _insert_session_context(db_path, session_id="sess-broken", transcript_path=broken_path)
    _insert_session_context(db_path, session_id="sess-healthy", transcript_path=healthy_path)

    monkeypatch.setattr(
        "teleclaude.mirrors.worker._discover_transcripts",
        lambda: [
            TranscriptCandidate(path=broken_path, agent=AgentName.CLAUDE, mtime=broken_path.stat().st_mtime),
            TranscriptCandidate(path=healthy_path, agent=AgentName.CLAUDE, mtime=healthy_path.stat().st_mtime),
        ],
    )

    from teleclaude.mirrors.generator import generate_mirror_sync as real_generate_mirror_sync

    def fake_generate_mirror_sync(**kwargs):
        if kwargs["transcript_path"] == str(broken_path):
            raise FileNotFoundError("transcript disappeared")
        return real_generate_mirror_sync(**kwargs)

    logger_error = Mock()
    monkeypatch.setattr("teleclaude.mirrors.worker.generate_mirror_sync", fake_generate_mirror_sync)
    monkeypatch.setattr("teleclaude.mirrors.worker.logger.error", logger_error)

    worker = MirrorWorker(db=str(db_path), interval_s=1)
    result = worker._reconcile_sync()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("SELECT session_id, source_identity FROM mirrors ORDER BY session_id").fetchall()

    assert result.discovered == 2
    assert result.processed == 1
    assert result.failed == 1
    assert rows == [("sess-healthy", "claude:teleclaude/healthy.jsonl")]
    logger_error.assert_called_once()


def test_reconcile_sync_tombstones_empty_transcripts_until_the_file_changes(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    transcript_path = tmp_path / ".claude" / "projects" / "teleclaude" / "tool-only.jsonl"
    _write_jsonl(transcript_path, _tool_only_entries())
    os.utime(transcript_path, (10, 10))

    import asyncio

    asyncio.run(_apply_mirror_migrations(db_path))
    _create_sessions_table(db_path)
    _insert_session_context(db_path, session_id="sess-empty", transcript_path=transcript_path)

    monkeypatch.setattr(
        "teleclaude.mirrors.worker._discover_transcripts",
        lambda: [
            TranscriptCandidate(
                path=transcript_path,
                agent=AgentName.CLAUDE,
                mtime=transcript_path.stat().st_mtime,
            )
        ],
    )

    worker = MirrorWorker(db=str(db_path), interval_s=1)
    first = worker._reconcile_sync()
    second = worker._reconcile_sync()

    with sqlite3.connect(db_path) as conn:
        tombstone_count = conn.execute("SELECT COUNT(*) FROM mirror_tombstones").fetchone()[0]
        mirror_count = conn.execute("SELECT COUNT(*) FROM mirrors").fetchone()[0]

    assert first.processed == 1
    assert second.processed == 0
    assert tombstone_count == 1
    assert mirror_count == 0

    _write_jsonl(transcript_path, _conversation_entries())
    os.utime(transcript_path, (20, 20))

    third = worker._reconcile_sync()
    fourth = worker._reconcile_sync()

    with sqlite3.connect(db_path) as conn:
        tombstone_count_after = conn.execute("SELECT COUNT(*) FROM mirror_tombstones").fetchone()[0]
        row = conn.execute(
            "SELECT session_id, source_identity, message_count FROM mirrors WHERE session_id = ?",
            ("sess-empty",),
        ).fetchone()

    assert third.processed == 1
    assert fourth.processed == 0
    assert tombstone_count_after == 0
    assert row == ("sess-empty", "claude:teleclaude/tool-only.jsonl", 2)


def test_backfill_sync_removes_stale_rows_and_rebuilds_canonical_rows(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    db_path = tmp_path / "teleclaude.db"
    transcript_path = tmp_path / ".claude" / "projects" / "teleclaude" / "session.jsonl"
    non_canonical_path = tmp_path / ".claude" / "projects" / "teleclaude" / "subagents" / "worker" / "session.jsonl"
    _write_jsonl(transcript_path, _conversation_entries())
    os.utime(transcript_path, (10, 10))

    import asyncio

    asyncio.run(_apply_mirror_migrations(db_path))
    _create_sessions_table(db_path)
    _insert_session_context(db_path, session_id="sess-1", transcript_path=transcript_path)

    with sqlite3.connect(db_path) as conn:
        conn.execute(
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
            (
                "orphan-1",
                None,
                "MozBook",
                "claude",
                "teleclaude",
                "orphan row",
                "2026-03-01T10:00:00Z",
                "2026-03-01T10:00:01Z",
                "User: orphan",
                1,
                json.dumps({"agent": "claude", "transcript_path": str(transcript_path)}),
                "2026-03-01T10:00:00Z",
                "2026-03-01T10:00:01Z",
            ),
        )
        conn.execute(
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
            (
                "bad-1",
                "claude:teleclaude/subagents/worker/session.jsonl",
                "MozBook",
                "claude",
                "teleclaude",
                "non canonical row",
                "2026-03-01T10:00:00Z",
                "2026-03-01T10:00:01Z",
                "User: bad",
                1,
                json.dumps({"agent": "claude", "transcript_path": str(non_canonical_path)}),
                "2026-03-01T10:00:00Z",
                "2026-03-01T10:00:01Z",
            ),
        )
        conn.commit()

    monkeypatch.setattr(
        "teleclaude.mirrors.worker._discover_transcripts",
        lambda: [
            TranscriptCandidate(
                path=transcript_path,
                agent=AgentName.CLAUDE,
                mtime=transcript_path.stat().st_mtime,
            )
        ],
    )

    worker = MirrorWorker(db=str(db_path), interval_s=1)
    result = worker.backfill_sync()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT session_id, source_identity, title FROM mirrors ORDER BY session_id"
        ).fetchall()

    assert result.processed == 1
    assert rows == [("sess-1", "claude:teleclaude/session.jsonl", "Need mirror reconciliation.")]
