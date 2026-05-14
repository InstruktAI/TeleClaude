from __future__ import annotations

import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
from sqlalchemy import text

from teleclaude.constants import DB_IN_MEMORY
from teleclaude.core import db_models
from teleclaude.core.db._base import DbBase, SqliteDatabaseStats
from teleclaude.core.db.connection_factory import get_outbox_db_path


def test_to_core_session_reads_system_role_and_job_from_columns() -> None:
    row = db_models.Session(
        session_id="sess-001",
        computer_name="builder-mac",
        tmux_session_name="tmux-001",
        last_input_origin="telegram",
        title=None,
        system_role="reviewer",
        job="chartest",
        initiated_by_ai=1,
        notification_sent=0,
        tui_capture_started=1,
        char_offset="7",
        lifecycle_status=None,
        visibility=None,
        created_at="2025-01-02T03:04:05Z",
        last_activity=datetime(2025, 1, 2, 3, 5, 0),
    )

    session = DbBase._to_core_session(row)

    assert session.title == ""
    assert session.system_role == "reviewer"
    assert session.job == "chartest"
    assert session.initiated_by_ai is True
    assert session.notification_sent is False
    assert session.tui_capture_started is True
    assert session.char_offset == 7
    assert session.lifecycle_status == "active"
    assert session.visibility is None
    assert session.created_at == datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert session.last_activity == datetime(2025, 1, 2, 3, 5, 0, tzinfo=UTC)


def test_session_requires_initialize_before_opening_runtime_session() -> None:
    db = DbBase("unused.db")

    with pytest.raises(RuntimeError, match="Database not initialized"):
        db._session()


@pytest.mark.asyncio
async def test_initialize_in_memory_cleans_up_temp_file() -> None:
    db = DbBase(DB_IN_MEMORY)
    await db.initialize()
    assert db.is_initialized() is True
    assert db._temp_db_path is not None

    temp_db_path = db._temp_db_path
    await db.wal_checkpoint()
    await db.close()

    assert temp_db_path is not None
    assert os.path.exists(temp_db_path) is False


@pytest.mark.asyncio
async def test_initialize_sessions_schema_excludes_dead_linked_output_column() -> None:
    db = DbBase(DB_IN_MEMORY)
    await db.initialize()

    async with db._session() as session:
        result = await session.exec(text("SELECT name FROM pragma_table_info('sessions')"))  # guard: raw-sql
        rows = result.fetchall()

    columns = {str(row[0]) for row in rows}
    assert "turn_triggered_by_linked_output" not in columns

    await db.close()


@pytest.mark.asyncio
async def test_initialize_sessions_schema_excludes_dead_session_metadata_column() -> None:
    db = DbBase(DB_IN_MEMORY)
    await db.initialize()

    async with db._session() as session:
        result = await session.exec(text("SELECT name FROM pragma_table_info('sessions')"))  # guard: raw-sql
        rows = result.fetchall()

    columns = {str(row[0]) for row in rows}
    assert "session_metadata" not in columns

    await db.close()


def _create_fragmented_sqlite_database(db_path: Path) -> None:
    payload = "x" * 4096
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA page_size = 1024")  # guard: raw-sql
        conn.execute("CREATE TABLE payload (body TEXT)")  # guard: raw-sql
        conn.executemany(
            "INSERT INTO payload (body) VALUES (?)",  # guard: raw-sql
            [(payload,) for _ in range(200)],
        )
        conn.commit()
        conn.execute("DELETE FROM payload")  # guard: raw-sql
        conn.commit()


@pytest.mark.asyncio
async def test_sqlite_database_stats_report_freelist_and_free_bytes(tmp_path: Path) -> None:
    db_path = tmp_path / "fragmented.db"
    _create_fragmented_sqlite_database(db_path)
    db = DbBase(str(tmp_path / "teleclaude.db"))

    stats = await db.get_sqlite_database_stats(db_path)

    assert isinstance(stats, SqliteDatabaseStats)
    assert stats.page_count > 0
    assert stats.page_size > 0
    assert stats.freelist_count > 0
    assert stats.free_bytes == stats.freelist_count * stats.page_size
    assert stats.freelist_ratio == pytest.approx(stats.freelist_count / stats.page_count)


@pytest.mark.asyncio
async def test_compact_sqlite_database_if_needed_respects_thresholds(tmp_path: Path) -> None:
    db_path = tmp_path / "fragmented.db"
    _create_fragmented_sqlite_database(db_path)
    db = DbBase(str(tmp_path / "teleclaude.db"))

    skipped = await db.compact_sqlite_database_if_needed(
        db_path,
        min_freelist_ratio=1.0,
        min_free_bytes=1_000_000_000,
    )
    compacted = await db.compact_sqlite_database_if_needed(
        db_path,
        min_freelist_ratio=0.0,
        min_free_bytes=0,
    )
    after = await db.get_sqlite_database_stats(db_path)

    assert skipped is False
    assert compacted is True
    assert after.freelist_count == 0


@pytest.mark.asyncio
async def test_compact_sqlite_database_if_needed_warns_on_sqlite_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = tmp_path / "fragmented.db"
    _create_fragmented_sqlite_database(db_path)
    db = DbBase(str(tmp_path / "teleclaude.db"))

    async def _fail_compaction(path: Path) -> None:
        _ = path
        raise sqlite3.OperationalError("locked")

    monkeypatch.setattr(db, "_compact_sqlite_database", _fail_compaction)

    warning_mock = Mock()
    debug_mock = Mock()
    monkeypatch.setattr("teleclaude.core.db._base.logger.warning", warning_mock)
    monkeypatch.setattr("teleclaude.core.db._base.logger.debug", debug_mock)

    compacted = await db.compact_sqlite_database_if_needed(
        db_path,
        min_freelist_ratio=0.0,
        min_free_bytes=0,
    )

    assert compacted is False
    warning_mock.assert_called_once()
    debug_mock.assert_not_called()


@pytest.mark.asyncio
async def test_compact_runtime_databases_if_needed_targets_runtime_dbs_excluding_mirrors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_path = tmp_path / "teleclaude.db"
    outbox_path = get_outbox_db_path(tmp_path)
    events_path = tmp_path / "events.db"
    mirrors_path = tmp_path / "mirrors.db"
    for db_path in (main_path, outbox_path, events_path, mirrors_path):
        db_path.touch()
    db = DbBase(str(main_path))
    compacted_paths: list[Path] = []

    async def _record_compaction(
        path: str | Path,
        *,
        min_freelist_ratio: float = 0.0,
        min_free_bytes: int = 0,
    ) -> bool:
        _ = (min_freelist_ratio, min_free_bytes)
        compacted_paths.append(Path(path))
        return True

    monkeypatch.setattr(db, "compact_sqlite_database_if_needed", _record_compaction)

    compacted = await db.compact_runtime_databases_if_needed()

    assert compacted == 3
    assert set(compacted_paths) == {main_path, outbox_path, events_path}
    assert mirrors_path not in compacted_paths
