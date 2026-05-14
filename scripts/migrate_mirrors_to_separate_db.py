#!/usr/bin/env python3
"""One-shot migration: merge mirror rows from main DB into mirrors.db, then drop mirror tables from main DB.

Run after deploying the hardcode-db-paths code changes. Safe to re-run (idempotent).

Usage:
    python scripts/migrate_mirrors_to_separate_db.py [--dry-run]
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from teleclaude.paths import MAIN_DB_PATH, MIRRORS_DB_PATH

MAIN_DB = MAIN_DB_PATH
MIRRORS_DB = MIRRORS_DB_PATH

MIRROR_TABLES = ["mirrors_fts", "mirror_tombstones", "mirrors"]

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


def migrate(*, dry_run: bool = False) -> None:
    if not MAIN_DB.exists():
        print(f"Main DB not found: {MAIN_DB}")
        return

    main = sqlite3.connect(str(MAIN_DB))
    main.execute("PRAGMA busy_timeout = 5000")

    if not _has_table(main, "mirrors"):
        print("No mirrors table in main DB — nothing to migrate.")
        main.close()
        return

    main_count = main.execute("SELECT count(*) FROM mirrors").fetchone()[0]
    print(f"Main DB mirrors: {main_count}")

    # Ensure mirrors.db schema exists
    target = sqlite3.connect(str(MIRRORS_DB))
    target.execute("PRAGMA busy_timeout = 5000")
    target.executescript(MIRRORS_SCHEMA)

    target_count_before = target.execute("SELECT count(*) FROM mirrors").fetchone()[0]
    print(f"Mirrors DB before merge: {target_count_before}")

    if dry_run:
        print("[DRY RUN] Would merge mirrors and drop tables from main DB.")
        main.close()
        target.close()
        return

    # Merge: INSERT OR REPLACE keyed on source_identity
    main.execute(f"ATTACH DATABASE '{MIRRORS_DB}' AS dest")
    merged = main.execute(
        """
        INSERT OR REPLACE INTO dest.mirrors
            (session_id, source_identity, computer, agent, project, title,
             timestamp_start, timestamp_end, conversation_text, message_count,
             metadata, created_at, updated_at, summary, human_email, visibility)
        SELECT session_id, source_identity, computer, agent, project, title,
               timestamp_start, timestamp_end, conversation_text, message_count,
               metadata, created_at, updated_at, summary, human_email, visibility
        FROM mirrors
        """
    ).rowcount
    main.commit()
    print(f"Merged {merged} rows into mirrors.db")

    # Merge tombstones
    if _has_table(main, "mirror_tombstones"):
        tomb_merged = main.execute(
            """
            INSERT OR REPLACE INTO dest.mirror_tombstones
                (source_identity, agent, transcript_path, file_size, file_mtime, created_at)
            SELECT source_identity, agent, transcript_path, file_size, file_mtime, created_at
            FROM mirror_tombstones
            """
        ).rowcount
        main.commit()
        print(f"Merged {tomb_merged} tombstone rows")

    main.execute("DETACH DATABASE dest")
    main.commit()

    # Rebuild FTS in mirrors.db
    target.close()
    target = sqlite3.connect(str(MIRRORS_DB))
    target.execute("PRAGMA busy_timeout = 5000")
    target_count_after = target.execute("SELECT count(*) FROM mirrors").fetchone()[0]
    print(f"Mirrors DB after merge: {target_count_after}")

    print("Rebuilding FTS index...")
    target.execute("INSERT INTO mirrors_fts(mirrors_fts) VALUES('rebuild')")
    target.commit()
    target.close()
    print("FTS rebuild complete")

    # Drop mirror tables from main DB
    print("Dropping mirror tables from main DB...")
    for table in MIRROR_TABLES:
        try:
            main.execute(f"DROP TABLE IF EXISTS {table}")
        except sqlite3.OperationalError as e:
            print(f"  Warning dropping {table}: {e}")
    # Drop triggers
    for trigger in ("mirrors_ai", "mirrors_ad", "mirrors_au"):
        main.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    # Drop indexes
    for index in (
        "idx_mirrors_agent",
        "idx_mirrors_project",
        "idx_mirrors_timestamp",
        "idx_mirrors_source_identity",
        "idx_mirrors_human_email",
    ):
        main.execute(f"DROP INDEX IF EXISTS {index}")
    main.commit()
    main.close()

    print("Done. Mirror tables removed from main DB.")

    # Verify
    verify = sqlite3.connect(str(MAIN_DB))
    tables = [r[0] for r in verify.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    verify.close()
    mirror_remains = [t for t in tables if "mirror" in t.lower()]
    if mirror_remains:
        print(f"WARNING: mirror-related tables still present: {mirror_remains}")
    else:
        print("Verified: no mirror tables remain in main DB.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate mirrors from main DB to mirrors.db")
    parser.add_argument("--dry-run", action="store_true", help="Show counts without modifying anything")
    args = parser.parse_args()

    try:
        migrate(dry_run=args.dry_run)
    except Exception as e:
        print(f"Migration failed: {e}", file=sys.stderr)
        raise SystemExit(1) from e
