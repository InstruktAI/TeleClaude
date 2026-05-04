# pylint: disable=import-outside-toplevel,import-error,no-name-in-module,too-few-public-methods
"""Test spec (xfail) for R8: outbox migration on startup.

On daemon startup, pending rows in teleclaude.db's hook_outbox table are copied
to the new outbox database and the table is dropped. The migration is idempotent.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import TypedDict

import pytest

from teleclaude.core.db.connection_factory import create_sync_db_engine, get_outbox_db_path, init_outbox_schema
from teleclaude.core.db.outbox_migration import (
    migrate_outbox_on_startup,
)

pytestmark = [pytest.mark.unit]


class _OutboxSeedRow(TypedDict, total=False):
    """Typed seed data for outbox migration tests."""

    session_id: str
    event_type: str
    payload: str
    created_at: str
    next_attempt_at: str
    attempt_count: int


def _seed_old_outbox(db_path: Path, rows: list[_OutboxSeedRow]) -> None:
    """Seed teleclaude.db with the old hook_outbox table and pending rows."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS hook_outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            next_attempt_at TEXT DEFAULT CURRENT_TIMESTAMP,
            attempt_count INTEGER DEFAULT 0,
            last_error TEXT,
            locked_at TEXT
        )
    """)
    for row in rows:
        conn.execute(
            "INSERT INTO hook_outbox (session_id, event_type, payload, created_at, next_attempt_at, attempt_count)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                row["session_id"],
                row["event_type"],
                row["payload"],
                row.get("created_at", datetime.now(UTC).isoformat()),
                row.get("next_attempt_at", datetime.now(UTC).isoformat()),
                row.get("attempt_count", 0),
            ),
        )
    conn.commit()
    conn.close()


class TestOutboxMigrationCopiesPendingRows:
    """Pending rows are copied from teleclaude.db to the new outbox database."""

    def test_pending_rows_appear_in_outbox_db(self, tmp_path: Path) -> None:
        """After migration, all pending rows from teleclaude.db appear in the outbox DB."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        rows: list[_OutboxSeedRow] = [
            {
                "session_id": "sess-mig-001",
                "event_type": "agent_stop",
                "payload": json.dumps({"key": "value1"}),
            },
            {
                "session_id": "sess-mig-002",
                "event_type": "user_prompt_submit",
                "payload": json.dumps({"key": "value2"}),
            },
        ]
        _seed_old_outbox(main_db, rows)

        migrate_outbox_on_startup(str(main_db), str(outbox_db))

        # Verify rows in outbox DB
        conn = sqlite3.connect(str(outbox_db))
        result = conn.execute("SELECT session_id, event_type FROM hook_outbox ORDER BY id").fetchall()
        conn.close()

        assert len(result) == 2
        assert result[0][0] == "sess-mig-001"
        assert result[1][0] == "sess-mig-002"

    def test_payload_integrity_preserved(self, tmp_path: Path) -> None:
        """Migrated rows preserve their original payload content."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        original_payload = {"complex": {"nested": True}, "list": [1, 2, 3]}
        _seed_old_outbox(
            main_db,
            [
                {
                    "session_id": "sess-payload",
                    "event_type": "agent_stop",
                    "payload": json.dumps(original_payload),
                }
            ],
        )

        migrate_outbox_on_startup(str(main_db), str(outbox_db))

        conn = sqlite3.connect(str(outbox_db))
        payload_str = conn.execute("SELECT payload FROM hook_outbox LIMIT 1").fetchone()[0]
        conn.close()

        assert json.loads(payload_str) == original_payload


class TestOutboxMigrationDropsOldTable:
    """After migration, hook_outbox is removed from teleclaude.db."""

    def test_hook_outbox_table_removed_from_main(self, tmp_path: Path) -> None:
        """The hook_outbox table no longer exists in teleclaude.db after migration."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        _seed_old_outbox(
            main_db,
            [{"session_id": "sess-drop", "event_type": "test", "payload": "{}"}],
        )

        migrate_outbox_on_startup(str(main_db), str(outbox_db))

        conn = sqlite3.connect(str(main_db))
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "hook_outbox" not in tables


class TestOutboxMigrationIdempotent:
    """Running the migration multiple times produces the same result."""

    def test_second_run_is_noop(self, tmp_path: Path) -> None:
        """Running migration a second time does not duplicate rows or error."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        _seed_old_outbox(
            main_db,
            [{"session_id": "sess-idem", "event_type": "test", "payload": "{}"}],
        )

        migrate_outbox_on_startup(str(main_db), str(outbox_db))
        # Second run should be a no-op (table already dropped from main)
        migrate_outbox_on_startup(str(main_db), str(outbox_db))

        conn = sqlite3.connect(str(outbox_db))
        count = conn.execute("SELECT COUNT(*) FROM hook_outbox").fetchone()[0]
        conn.close()
        assert count == 1  # No duplicates

    def test_no_pending_rows_is_noop(self, tmp_path: Path) -> None:
        """When no hook_outbox table exists in teleclaude.db, migration is a no-op."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        # Create teleclaude.db without hook_outbox table
        conn = sqlite3.connect(str(main_db))
        conn.execute("CREATE TABLE sessions (session_id TEXT PRIMARY KEY)")
        conn.commit()
        conn.close()

        # Should not raise
        migrate_outbox_on_startup(str(main_db), str(outbox_db))

    def test_empty_table_is_noop_and_drops_table(self, tmp_path: Path) -> None:
        """When hook_outbox exists but has zero rows, table is dropped (no data to migrate)."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        # Create empty hook_outbox
        _seed_old_outbox(main_db, [])

        migrate_outbox_on_startup(str(main_db), str(outbox_db))

        # Table should be dropped even when empty
        conn = sqlite3.connect(str(main_db))
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        conn.close()
        assert "hook_outbox" not in tables


class TestOutboxMigrationAttemptCountPreserved:
    """Migration preserves operational fields like attempt_count and timestamps."""

    def test_attempt_count_and_timestamps_copied(self, tmp_path: Path) -> None:
        """Migrated rows retain their attempt_count, created_at, and next_attempt_at."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        created = "2026-04-03T10:00:00+00:00"
        next_attempt = "2026-04-03T10:05:00+00:00"
        _seed_old_outbox(
            main_db,
            [
                {
                    "session_id": "sess-fields",
                    "event_type": "agent_stop",
                    "payload": "{}",
                    "created_at": created,
                    "next_attempt_at": next_attempt,
                    "attempt_count": 3,
                }
            ],
        )

        migrate_outbox_on_startup(str(main_db), str(outbox_db))

        conn = sqlite3.connect(str(outbox_db))
        row = conn.execute("SELECT created_at, next_attempt_at, attempt_count FROM hook_outbox LIMIT 1").fetchone()
        conn.close()

        assert row[0] == created
        assert row[1] == next_attempt
        assert row[2] == 3


class TestOutboxMigrationCollisionSafety:
    """Migration must not silently drop legacy rows when the outbox DB has pre-existing rows."""

    def test_preexisting_outbox_rows_do_not_block_legacy_copy(self, tmp_path: Path) -> None:
        """Legacy rows are inserted with new IDs even when the outbox DB already has rows."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        _seed_old_outbox(
            main_db,
            [
                {"session_id": "legacy-sess", "event_type": "agent_stop", "payload": "{}"},
                {"session_id": "legacy-sess-2", "event_type": "tool_use", "payload": "{}"},
            ],
        )

        # Pre-populate the outbox DB with rows that would collide on integer IDs
        outbox_db.parent.mkdir(parents=True, exist_ok=True)
        engine = create_sync_db_engine(str(outbox_db))
        init_outbox_schema(engine)
        engine.dispose()

        pre_conn = sqlite3.connect(str(outbox_db))
        pre_conn.execute(
            "INSERT INTO hook_outbox (session_id, event_type, payload) VALUES (?, ?, ?)",
            ("new-sess", "tool_use", "{}"),
        )
        pre_conn.commit()
        pre_conn.close()

        migrate_outbox_on_startup(str(main_db), str(outbox_db))

        conn = sqlite3.connect(str(outbox_db))
        all_rows = conn.execute("SELECT session_id FROM hook_outbox ORDER BY id").fetchall()
        conn.close()

        session_ids = [row[0] for row in all_rows]
        assert "new-sess" in session_ids, "Pre-existing row must survive"
        assert "legacy-sess" in session_ids, "Legacy row must be copied"
        assert "legacy-sess-2" in session_ids, "Legacy row must be copied"
        assert len(all_rows) == 3

    def test_legacy_table_dropped_after_successful_copy(self, tmp_path: Path) -> None:
        """The legacy table is dropped only after all rows are verified as inserted."""
        main_db = tmp_path / "teleclaude.db"
        outbox_db = get_outbox_db_path(tmp_path)

        _seed_old_outbox(
            main_db,
            [{"session_id": "sess-gate", "event_type": "agent_stop", "payload": "{}"}],
        )

        # Pre-populate outbox DB
        outbox_db.parent.mkdir(parents=True, exist_ok=True)
        engine = create_sync_db_engine(str(outbox_db))
        init_outbox_schema(engine)
        engine.dispose()

        pre_conn = sqlite3.connect(str(outbox_db))
        pre_conn.execute(
            "INSERT INTO hook_outbox (session_id, event_type, payload) VALUES (?, ?, ?)",
            ("existing-sess", "tool_use", "{}"),
        )
        pre_conn.commit()
        pre_conn.close()

        migrate_outbox_on_startup(str(main_db), str(outbox_db))

        # Legacy table must be gone
        main_conn = sqlite3.connect(str(main_db))
        tables = {r[0] for r in main_conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        main_conn.close()
        assert "hook_outbox" not in tables
