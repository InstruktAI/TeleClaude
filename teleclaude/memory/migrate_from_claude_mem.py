"""Migrate data from external claude-mem database to TeleClaude's memory tables.

The old claude-mem DB uses different table names and has extra columns:
  - observations → memory_observations (extra 'text' column, old type enum)
  - session_summaries → memory_summaries (extra files_read/files_edited/notes/prompt_number/discovery_tokens)
  - sdk_sessions → memory_manual_sessions (different column set)

Old activity-tracking types (bugfix, feature, refactor, change) are mapped to 'discovery'.

Usage:
    python -m teleclaude.memory.migrate_from_claude_mem [--source PATH] [--target PATH]
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from teleclaude.memory.types import ObservationType

_VALID_TYPES = {t.value for t in ObservationType}

_TYPE_MAP = {
    "bugfix": "discovery",
    "feature": "discovery",
    "refactor": "discovery",
    "change": "discovery",
}


def _map_type(old_type: str) -> str:
    """Map old activity-tracking types to relationship-centric types."""
    if old_type in _VALID_TYPES:
        return old_type
    return _TYPE_MAP.get(old_type, "discovery")


def migrate(source_db: str, target_db: str) -> dict[str, int]:
    """Migrate observations + summaries from claude-mem to teleclaude.db.

    Transaction-wrapped, re-run safe (INSERT OR IGNORE).
    Returns: {"observations": N, "summaries": N, "sessions": N}
    """
    source = sqlite3.connect(source_db)
    target = sqlite3.connect(target_db)

    target.execute("PRAGMA journal_mode = WAL")
    target.execute("PRAGMA busy_timeout = 5000")

    counts = {"observations": 0, "summaries": 0, "sessions": 0}

    try:
        # Migrate sessions: sdk_sessions → memory_manual_sessions
        try:
            rows = source.execute("SELECT memory_session_id, project, started_at_epoch FROM sdk_sessions").fetchall()
            for row in rows:
                session_id, project, epoch = row
                if not session_id or not project:
                    continue
                target.execute(
                    "INSERT OR IGNORE INTO memory_manual_sessions "
                    "(memory_session_id, project, created_at_epoch) VALUES (?, ?, ?)",
                    (session_id, project, epoch),
                )
                counts["sessions"] += 1
        except sqlite3.OperationalError:
            pass  # Table may not exist in source

        # Migrate observations: observations → memory_observations
        try:
            rows = source.execute(
                "SELECT id, memory_session_id, project, type, title, subtitle, "
                "facts, narrative, concepts, files_read, files_modified, "
                "prompt_number, discovery_tokens, created_at, created_at_epoch "
                "FROM observations"
            ).fetchall()
            for row in rows:
                (
                    obs_id,
                    session_id,
                    project,
                    obs_type,
                    title,
                    subtitle,
                    facts,
                    narrative,
                    concepts,
                    files_read,
                    files_modified,
                    prompt_number,
                    discovery_tokens,
                    created_at,
                    created_at_epoch,
                ) = row
                mapped_type = _map_type(obs_type or "discovery")
                target.execute(
                    "INSERT OR IGNORE INTO memory_observations "
                    "(id, memory_session_id, project, type, title, subtitle, "
                    "facts, narrative, concepts, files_read, files_modified, "
                    "prompt_number, discovery_tokens, created_at, created_at_epoch) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        obs_id,
                        session_id,
                        project,
                        mapped_type,
                        title,
                        subtitle,
                        facts,
                        narrative,
                        concepts,
                        files_read,
                        files_modified,
                        prompt_number,
                        discovery_tokens,
                        created_at,
                        created_at_epoch,
                    ),
                )
                counts["observations"] += 1
        except sqlite3.OperationalError:
            pass

        # Migrate summaries: session_summaries → memory_summaries
        try:
            rows = source.execute(
                "SELECT id, memory_session_id, project, request, investigated, "
                "learned, completed, next_steps, created_at, created_at_epoch "
                "FROM session_summaries"
            ).fetchall()
            for row in rows:
                target.execute(
                    "INSERT OR IGNORE INTO memory_summaries "
                    "(id, memory_session_id, project, request, investigated, "
                    "learned, completed, next_steps, created_at, created_at_epoch) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    row,
                )
                counts["summaries"] += 1
        except sqlite3.OperationalError:
            pass

        target.commit()

        # Rebuild FTS5 index
        try:
            target.execute("INSERT INTO memory_observations_fts(memory_observations_fts) VALUES('rebuild')")
            target.commit()
        except sqlite3.OperationalError:
            pass  # FTS5 may not be available

    finally:
        source.close()
        target.close()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate claude-mem data to TeleClaude")
    parser.add_argument(
        "--source",
        default=str(Path.home() / ".claude-mem" / "claude-mem.db"),
        help="Source claude-mem database path",
    )
    parser.add_argument(
        "--target",
        default="teleclaude.db",
        help="Target TeleClaude database path",
    )
    args = parser.parse_args()

    if not Path(args.source).exists():
        print(f"Source database not found: {args.source}")
        return

    print(f"Migrating from {args.source} to {args.target}")
    counts = migrate(args.source, args.target)
    print(
        f"Done: {counts['observations']} observations, {counts['summaries']} summaries, {counts['sessions']} sessions"
    )


if __name__ == "__main__":
    main()
