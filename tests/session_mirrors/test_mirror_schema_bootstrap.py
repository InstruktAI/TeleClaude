"""Functional bindings for mirror schema bootstrap and compatibility migration."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from teleclaude.mirrors import store

pytestmark = [pytest.mark.functional]

_SPEC = "project/spec/feature/session_mirrors/mirror-schema-bootstrap"

_DERIVED_COLUMNS = {"command", "slug", "is_agent_spawn", "derivation_version"}
_SPAWN_INDEX = {"idx_mirrors_is_agent_spawn"}

_OLD_SHAPE_SCHEMA = """
CREATE TABLE mirrors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    source_identity TEXT UNIQUE,
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
    updated_at TEXT NOT NULL,
    summary TEXT,
    human_email TEXT,
    visibility TEXT DEFAULT 'private'
);
"""


def _reset_store_caches(path: str) -> None:
    store._schema_initialized.discard(path)


def _table_columns(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {str(row[1]) for row in conn.execute("PRAGMA table_info(mirrors)")}


def _index_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")}


@pytest.mark.spec(_SPEC, "UC-MSB-2")
def test_compatibility_migration_on_fresh_and_old_shape_stores(tmp_path: Path) -> None:
    # Fresh store: a read drives lazy bootstrap and yields the full derived schema.
    fresh = tmp_path / "fresh.db"
    _reset_store_caches(str(fresh.resolve()))
    assert store.list_mirrors(db=str(fresh)) == []
    assert _DERIVED_COLUMNS <= _table_columns(fresh)
    assert _SPAWN_INDEX <= _index_names(fresh)

    # Old-shape store seeded without the derived columns migrates and stays readable.
    db_path = tmp_path / "old.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_OLD_SHAPE_SCHEMA)
        conn.execute(
            "INSERT INTO mirrors (session_id, source_identity, computer, agent, title, "
            "conversation_text, created_at, updated_at) "
            "VALUES ('sess-old', 'src-old', 'box', 'claude', 'legacy title', 'hi there', 'c', 'u')"
        )
        conn.commit()

    resolved = str(db_path.resolve())
    _reset_store_caches(resolved)

    # Opening through the store runs the idempotent compatibility migration.
    record = store.get_mirror(source_identity="src-old", db=str(db_path))
    assert record is not None
    assert record.is_agent_spawn is False
    assert record.derivation_version == 0
    assert _DERIVED_COLUMNS <= _table_columns(db_path)
    assert _SPAWN_INDEX <= _index_names(db_path)

    # Re-running the migration over the already-migrated table is a no-op (idempotent).
    with sqlite3.connect(db_path) as conn:
        store._migrate_add_mirror_columns(conn)
        conn.commit()
    assert _DERIVED_COLUMNS <= _table_columns(db_path)
