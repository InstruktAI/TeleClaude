# pylint: disable=import-outside-toplevel,import-error,no-name-in-module,protected-access,too-few-public-methods
"""Test spec (xfail) for R2: outbox database isolation.

The hook_outbox table moves to its own dedicated database file. The receiver
writes via a sync engine; the daemon reads/deletes via an async engine. Both
engines come from the shared connection factory.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import text
from sqlmodel import Session as SqlSession

from teleclaude.core import db_models
from teleclaude.core.db import Db
from teleclaude.core.db.connection_factory import (
    create_sync_db_engine,
    get_outbox_db_path,
    init_outbox_schema,
)
from teleclaude.hooks.receiver import enqueue_hook_event

pytestmark = [pytest.mark.unit]


class TestOutboxDatabaseSeparation:
    """The outbox resides in its own file, not in teleclaude.db."""

    def test_outbox_db_file_is_separate_from_main(self, tmp_path: Path) -> None:
        """Outbox engine targets a different file than the main teleclaude.db engine."""
        main_path = tmp_path / "teleclaude.db"
        outbox_path = get_outbox_db_path(tmp_path)
        assert outbox_path != main_path
        assert outbox_path.name != "teleclaude.db"

    def test_outbox_table_exists_in_outbox_db(self, tmp_path: Path) -> None:
        """After explicit outbox schema initialization, hook_outbox table exists."""
        outbox_path = get_outbox_db_path(tmp_path)
        engine = create_sync_db_engine(outbox_path)
        # Explicit schema initialization is required — engine creation alone may not create tables
        init_outbox_schema(engine)  # pyright: ignore[reportCallIssue]
        with engine.connect() as conn:
            result = conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' AND name='hook_outbox'")
            assert result.scalar() == "hook_outbox"

    def test_outbox_table_absent_from_main_db_after_migration(self, tmp_path: Path) -> None:
        """After a fresh install, teleclaude.db does not contain hook_outbox."""
        # This verifies that new installs get the separated schema from the start.
        db = Db(str(tmp_path / "teleclaude.db"))
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(db.initialize())

            async def _assert_outbox_absent() -> None:
                async with db._session() as session:  # pylint: disable=protected-access
                    result = await session.exec(
                        text("SELECT name FROM sqlite_master WHERE type='table' AND name='hook_outbox'")
                    )
                    assert result.scalar() is None, "hook_outbox should not exist in teleclaude.db"

            loop.run_until_complete(_assert_outbox_absent())
        finally:
            loop.run_until_complete(db.close())
            loop.close()


class TestOutboxSchemaIntegrity:
    """The outbox schema in the new database matches the original definition."""

    def test_outbox_schema_has_required_columns(self, tmp_path: Path) -> None:
        """hook_outbox in the outbox DB has all required columns."""
        outbox_path = get_outbox_db_path(tmp_path)
        engine = create_sync_db_engine(outbox_path)
        init_outbox_schema(engine)  # pyright: ignore[reportCallIssue]
        with engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA table_info(hook_outbox)")
            columns = {row[1] for row in result.fetchall()}

        required = {
            "id",
            "session_id",
            "event_type",
            "payload",
            "created_at",
            "next_attempt_at",
            "attempt_count",
            "last_error",
            "locked_at",
        }
        assert required.issubset(columns), f"Missing columns: {required - columns}"


class TestReceiverWritesToOutboxDb:
    """The receiver's sync engine targets the outbox database, not teleclaude.db."""

    def test_receiver_enqueue_writes_to_outbox_db(self, tmp_path: Path) -> None:
        """When the receiver calls its public enqueue function, the row appears in the outbox DB.

        This test exercises the actual receiver code path rather than bypassing it.
        The receiver's enqueue function must write to the outbox DB, not teleclaude.db.
        """
        outbox_path = get_outbox_db_path(tmp_path)

        enqueue_hook_event(  # pyright: ignore[reportCallIssue]
            session_id="sess-recv-test",
            event_type="agent_stop",
            payload=json.dumps({"key": "value"}),
            outbox_db=str(outbox_path),
        )

        # The row must appear in the outbox DB, not in teleclaude.db
        conn = sqlite3.connect(str(outbox_path))
        rows = conn.execute("SELECT event_type FROM hook_outbox WHERE session_id='sess-recv-test'").fetchall()
        conn.close()
        assert len(rows) == 1
        assert rows[0][0] == "agent_stop"


class TestOutboxWriteIsolation:
    """Outbox writes are independent of teleclaude.db lock state."""

    def test_outbox_write_succeeds_when_main_db_locked(self, tmp_path: Path) -> None:
        """Receiver can enqueue to the outbox even when teleclaude.db is held by another writer.

        This is the core contention fix: the outbox lives in a separate file,
        so the receiver never contends with the daemon for teleclaude.db locks.
        """
        main_db_path = tmp_path / "teleclaude.db"
        outbox_path = get_outbox_db_path(tmp_path)

        # Create both databases
        main_conn = sqlite3.connect(str(main_db_path))
        main_conn.execute("CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY)")
        main_conn.commit()

        outbox_engine = create_sync_db_engine(outbox_path)

        # Hold an exclusive lock on teleclaude.db
        main_conn.execute("BEGIN EXCLUSIVE")
        try:
            # Outbox write should succeed despite main DB being locked
            now = datetime.now(UTC).isoformat()
            with SqlSession(outbox_engine) as session:
                row = db_models.HookOutbox(
                    session_id="sess-isolated",
                    event_type="test_event",
                    payload="{}",
                    created_at=now,
                    next_attempt_at=now,
                    attempt_count=0,
                )
                session.add(row)
                session.commit()  # Should NOT raise "database is locked"
        finally:
            main_conn.rollback()
            main_conn.close()
