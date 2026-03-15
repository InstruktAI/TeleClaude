from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude.memory import migrate_from_claude_mem as migrate_module

pytestmark = pytest.mark.unit


def _execute_script(path: Path, script: str) -> None:
    with sqlite3.connect(path) as conn:
        conn.executescript(script)
        conn.commit()


def _fetch_one_value(path: Path, sql: str) -> object:
    with sqlite3.connect(path) as conn:
        row = conn.execute(sql).fetchone()
    assert row is not None
    return row[0]


def _prepare_source_db(path: Path) -> None:
    _execute_script(
        path,
        """
        CREATE TABLE sdk_sessions (
            memory_session_id TEXT,
            project TEXT,
            started_at_epoch INTEGER
        );
        CREATE TABLE observations (
            id INTEGER PRIMARY KEY,
            memory_session_id TEXT,
            project TEXT,
            type TEXT,
            title TEXT,
            subtitle TEXT,
            facts TEXT,
            narrative TEXT,
            concepts TEXT,
            files_read TEXT,
            files_modified TEXT,
            prompt_number INTEGER,
            discovery_tokens INTEGER,
            created_at TEXT,
            created_at_epoch INTEGER
        );
        CREATE TABLE session_summaries (
            id INTEGER PRIMARY KEY,
            memory_session_id TEXT,
            project TEXT,
            request TEXT,
            investigated TEXT,
            learned TEXT,
            completed TEXT,
            next_steps TEXT,
            created_at TEXT,
            created_at_epoch INTEGER
        );
        INSERT INTO sdk_sessions VALUES ('session-1', 'alpha', 100);
        INSERT INTO sdk_sessions VALUES ('session-missing-project', NULL, 200);
        INSERT INTO observations VALUES (
            1,
            'session-1',
            'alpha',
            'bugfix',
            'Patched cache invalidation',
            'subtitle',
            '["cache"]',
            'Narrative text',
            '["gotcha"]',
            '[]',
            '[]',
            3,
            9,
            '2025-01-01T00:00:00+00:00',
            1735689600
        );
        INSERT INTO session_summaries VALUES (
            2,
            'session-1',
            'alpha',
            'Request',
            'Investigated',
            'Learned',
            'Completed',
            'Next',
            '2025-01-01T00:00:00+00:00',
            1735689600
        );
        """,
    )


def _prepare_target_db(path: Path) -> None:
    _execute_script(
        path,
        """
        CREATE TABLE memory_manual_sessions (
            memory_session_id TEXT PRIMARY KEY,
            project TEXT,
            created_at_epoch INTEGER
        );
        CREATE TABLE memory_observations (
            id INTEGER PRIMARY KEY,
            memory_session_id TEXT,
            project TEXT,
            type TEXT,
            title TEXT,
            subtitle TEXT,
            facts TEXT,
            narrative TEXT,
            concepts TEXT,
            files_read TEXT,
            files_modified TEXT,
            prompt_number INTEGER,
            discovery_tokens INTEGER,
            created_at TEXT,
            created_at_epoch INTEGER
        );
        CREATE TABLE memory_summaries (
            id INTEGER PRIMARY KEY,
            memory_session_id TEXT,
            project TEXT,
            request TEXT,
            investigated TEXT,
            learned TEXT,
            completed TEXT,
            next_steps TEXT,
            created_at TEXT,
            created_at_epoch INTEGER
        );
        """,
    )


class TestMapType:
    def test_map_type_preserves_current_values_and_coalesces_legacy_types(self) -> None:
        assert migrate_module._map_type("pattern") == "pattern"
        assert migrate_module._map_type("bugfix") == "discovery"
        assert migrate_module._map_type("unknown") == "discovery"


class TestMigrate:
    def test_migrate_copies_rows_and_keeps_target_idempotent_on_repeat(self, tmp_path: Path) -> None:
        source_db = tmp_path / "source.sqlite"
        target_db = tmp_path / "target.sqlite"
        _prepare_source_db(source_db)
        _prepare_target_db(target_db)

        first_counts = migrate_module.migrate(str(source_db), str(target_db))
        second_counts = migrate_module.migrate(str(source_db), str(target_db))

        assert first_counts == {"observations": 1, "summaries": 1, "sessions": 1}
        assert second_counts == {"observations": 1, "summaries": 1, "sessions": 1}
        assert _fetch_one_value(target_db, "SELECT COUNT(*) FROM memory_manual_sessions") == 1
        assert _fetch_one_value(target_db, "SELECT COUNT(*) FROM memory_observations") == 1
        assert _fetch_one_value(target_db, "SELECT COUNT(*) FROM memory_summaries") == 1
        assert _fetch_one_value(target_db, "SELECT type FROM memory_observations WHERE id = 1") == "discovery"
