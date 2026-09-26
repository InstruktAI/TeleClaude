"""Durable operator migration command for moving mirror rows into mirrors.db.

Run after deploying the hardcode-db-paths code changes. Safe to re-run (idempotent).
This internal migration command uses the repository's project environment.

Usage:
    uv run --project <repo-root> python tools/migrations/migrate_mirrors_to_separate_db.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.paths import MAIN_DB_PATH, MIRRORS_DB_PATH  # noqa: E402 -- resolve owner paths from this checkout

MAIN_DB = MAIN_DB_PATH
MIRRORS_DB = MIRRORS_DB_PATH

MIRROR_TABLES = ["mirrors_fts", "mirror_tombstones", "mirrors"]
_MIRRORS_TABLE = "mirrors"
_MIRROR_TOMBSTONES_TABLE = "mirror_tombstones"
_MIRROR_NAME_MARKER = "mirror"
_SOURCE_DESTINATION_EQUAL_ERROR = "Source and destination database paths must differ"
_MIRRORS_COUNT_QUERY = "SELECT count(*) FROM mirrors"
_MIRRORS_TABLE_NAMES_QUERY = "SELECT name FROM sqlite_master WHERE type='table'"
_ATTACH_DESTINATION_QUERY = "ATTACH DATABASE ? AS dest"
_DETACH_DESTINATION_QUERY = "DETACH DATABASE dest"
_BUSY_TIMEOUT_QUERY = "PRAGMA busy_timeout = 5000"
_READ_ONLY_QUERY_SUFFIX = "?mode=ro"
_REBUILD_MIRRORS_FTS_QUERY = "INSERT INTO mirrors_fts(mirrors_fts) VALUES('rebuild')"
_DROP_TABLE_QUERY = "DROP TABLE IF EXISTS {table}"
_DROP_TRIGGER_QUERY = "DROP TRIGGER IF EXISTS {trigger}"
_DROP_INDEX_QUERY = "DROP INDEX IF EXISTS {index}"
_MIRRORS_NOT_FOUND = "Main DB not found: {path}"
_NO_MIRRORS_TABLE = "No mirrors table in main DB — nothing to migrate."
_MAIN_MIRRORS_COUNT = "Main DB mirrors: {count}"
_DESTINATION_MIRRORS_COUNT = "Mirrors DB before merge: {count}"
_DRY_RUN_RESULT = "[DRY RUN] Would merge mirrors and drop tables from main DB."
_MERGED_MIRRORS = "Merged {count} rows into mirrors.db"
_MERGED_TOMBSTONES = "Merged {count} tombstone rows"
_DESTINATION_AFTER_COUNT = "Mirrors DB after merge: {count}"
_REBUILD_FTS = "Rebuilding FTS index..."
_FTS_COMPLETE = "FTS rebuild complete"
_DROP_MAIN_TABLES = "Dropping mirror tables from main DB..."
_DROP_WARNING = "  Warning dropping {table}: {error}"
_MIRRORS_REMOVED = "Done. Mirror tables removed from main DB."
_MIRRORS_REMAIN_WARNING = "WARNING: mirror-related tables still present: {tables}"
_NO_MIRRORS_REMAIN = "Verified: no mirror tables remain in main DB."
_MIRROR_TRIGGER_NAMES = ("mirrors_ai", "mirrors_ad", "mirrors_au")
_MIRROR_INDEX_NAMES = (
    "idx_mirrors_agent",
    "idx_mirrors_project",
    "idx_mirrors_timestamp",
    "idx_mirrors_source_identity",
    "idx_mirrors_human_email",
)
_MERGE_MIRRORS_QUERY = """
INSERT OR REPLACE INTO dest.mirrors
    (session_id, source_identity, computer, agent, project, title,
     timestamp_start, timestamp_end, conversation_text, message_count,
     metadata, created_at, updated_at, summary, human_email, visibility)
SELECT session_id, source_identity, computer, agent, project, title,
       timestamp_start, timestamp_end, conversation_text, message_count,
       metadata, created_at, updated_at, summary, human_email, visibility
FROM mirrors
"""
_MERGE_TOMBSTONES_QUERY = """
INSERT OR REPLACE INTO dest.mirror_tombstones
    (source_identity, agent, transcript_path, file_size, file_mtime, created_at)
SELECT source_identity, agent, transcript_path, file_size, file_mtime, created_at
FROM mirror_tombstones
"""

MIRRORS_SCHEMA = """\
CREATE TABLE IF NOT EXISTS mirrors (
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
CREATE INDEX IF NOT EXISTS idx_mirrors_agent ON mirrors(agent);
CREATE INDEX IF NOT EXISTS idx_mirrors_project ON mirrors(project);
CREATE INDEX IF NOT EXISTS idx_mirrors_timestamp ON mirrors(timestamp_start DESC);
CREATE INDEX IF NOT EXISTS idx_mirrors_source_identity ON mirrors(source_identity);
CREATE INDEX IF NOT EXISTS idx_mirrors_human_email ON mirrors(human_email);
CREATE TABLE IF NOT EXISTS mirror_tombstones (
    source_identity TEXT PRIMARY KEY,
    agent TEXT NOT NULL DEFAULT '',
    transcript_path TEXT NOT NULL DEFAULT '',
    file_size INTEGER NOT NULL DEFAULT 0,
    file_mtime TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT ''
);
CREATE VIRTUAL TABLE IF NOT EXISTS mirrors_fts USING fts5(
    title,
    conversation_text,
    content='mirrors',
    content_rowid='id'
);
CREATE TRIGGER IF NOT EXISTS mirrors_ai AFTER INSERT ON mirrors BEGIN
    INSERT INTO mirrors_fts(rowid, title, conversation_text)
    VALUES (new.id, new.title, new.conversation_text);
END;
CREATE TRIGGER IF NOT EXISTS mirrors_ad AFTER DELETE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
    VALUES ('delete', old.id, old.title, old.conversation_text);
END;
CREATE TRIGGER IF NOT EXISTS mirrors_au AFTER UPDATE ON mirrors BEGIN
    INSERT INTO mirrors_fts(mirrors_fts, rowid, title, conversation_text)
    VALUES ('delete', old.id, old.title, old.conversation_text);
    INSERT INTO mirrors_fts(rowid, title, conversation_text)
    VALUES (new.id, new.title, new.conversation_text);
END;
"""


def _has_table(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()
    return bool(row and row[0])


def _connect_read_only(path: Path) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}{_READ_ONLY_QUERY_SUFFIX}"
    return sqlite3.connect(uri, uri=True)


def _table_count(conn: sqlite3.Connection) -> int:
    row = conn.execute(_MIRRORS_COUNT_QUERY).fetchone()
    return int(row[0]) if row else 0


def migrate(
    *,
    dry_run: bool = False,
    source_path: Path = MAIN_DB,
    destination_path: Path = MIRRORS_DB,
) -> None:
    if source_path.resolve() == destination_path.resolve():
        raise ValueError(_SOURCE_DESTINATION_EQUAL_ERROR)
    if not source_path.exists():
        print(_MIRRORS_NOT_FOUND.format(path=source_path))
        return

    main = _connect_read_only(source_path) if dry_run else sqlite3.connect(str(source_path))
    target: sqlite3.Connection | None = None
    try:
        main.execute(_BUSY_TIMEOUT_QUERY)

        if not _has_table(main, _MIRRORS_TABLE):
            print(_NO_MIRRORS_TABLE)
            return

        main_count = _table_count(main)
        print(_MAIN_MIRRORS_COUNT.format(count=main_count))

        target_count_before = 0
        if destination_path.exists():
            target = _connect_read_only(destination_path) if dry_run else sqlite3.connect(str(destination_path))
            target.execute(_BUSY_TIMEOUT_QUERY)
            if _has_table(target, _MIRRORS_TABLE):
                target_count_before = _table_count(target)
        print(_DESTINATION_MIRRORS_COUNT.format(count=target_count_before))

        if dry_run:
            print(_DRY_RUN_RESULT)
            return

        destination_path.parent.mkdir(parents=True, exist_ok=True)
        if target is None:
            target = sqlite3.connect(str(destination_path))
        target.executescript(MIRRORS_SCHEMA)
        target.commit()
        target.close()
        target = None

        main.execute(_ATTACH_DESTINATION_QUERY, (str(destination_path.resolve()),))
        merged = main.execute(_MERGE_MIRRORS_QUERY).rowcount
        main.commit()
        print(_MERGED_MIRRORS.format(count=merged))

        if _has_table(main, _MIRROR_TOMBSTONES_TABLE):
            tomb_merged = main.execute(_MERGE_TOMBSTONES_QUERY).rowcount
            main.commit()
            print(_MERGED_TOMBSTONES.format(count=tomb_merged))

        main.execute(_DETACH_DESTINATION_QUERY)
        main.commit()

        target = sqlite3.connect(str(destination_path))
        target.execute(_BUSY_TIMEOUT_QUERY)
        target_count_after = _table_count(target)
        print(_DESTINATION_AFTER_COUNT.format(count=target_count_after))

        print(_REBUILD_FTS)
        target.execute(_REBUILD_MIRRORS_FTS_QUERY)
        target.commit()
        target.close()
        target = None
        print(_FTS_COMPLETE)

        print(_DROP_MAIN_TABLES)
        for table in MIRROR_TABLES:
            try:
                main.execute(_DROP_TABLE_QUERY.format(table=table))
            except sqlite3.OperationalError as error:
                print(_DROP_WARNING.format(table=table, error=error))
        for trigger in _MIRROR_TRIGGER_NAMES:
            main.execute(_DROP_TRIGGER_QUERY.format(trigger=trigger))
        for index in _MIRROR_INDEX_NAMES:
            main.execute(_DROP_INDEX_QUERY.format(index=index))
        main.commit()

        print(_MIRRORS_REMOVED)
        tables = [row[0] for row in main.execute(_MIRRORS_TABLE_NAMES_QUERY).fetchall()]
        mirror_remains = [table for table in tables if _MIRROR_NAME_MARKER in table.lower()]
        if mirror_remains:
            print(_MIRRORS_REMAIN_WARNING.format(tables=mirror_remains))
        else:
            print(_NO_MIRRORS_REMAIN)
    finally:
        if target is not None:
            target.close()
        main.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate mirrors from main DB to mirrors.db")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without modifying anything")
    parser.add_argument("--source", type=Path, default=MAIN_DB, help="Source database path")
    parser.add_argument("--destination", type=Path, default=MIRRORS_DB, help="Destination database path")
    args = parser.parse_args()

    try:
        migrate(dry_run=args.dry_run, source_path=args.source, destination_path=args.destination)
    except Exception as e:
        print(f"Migration failed: {e}", file=sys.stderr)
        raise SystemExit(1) from e
