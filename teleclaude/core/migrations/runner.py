"""Database migration runner - executes pending migrations in order."""

import importlib.util
import re
from pathlib import Path
from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.migration_signal import MigrationStore, signal_migration_started

logger = get_logger(__name__)

_SKIP_FILES = {"__init__.py", "runner.py"}

MIGRATIONS_DIR = Path(__file__).parent

_VERSION_FILE_PATTERN = r"^\d{3}_"

_CREATE_MIGRATIONS_TABLE_SQL = """
    CREATE TABLE IF NOT EXISTS schema_migrations (
        version TEXT PRIMARY KEY,
        applied_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
"""
_SELECT_APPLIED_SQL = "SELECT version FROM schema_migrations"
_INSERT_APPLIED_SQL = "INSERT INTO schema_migrations (version) VALUES (?)"

_UP_ATTRIBUTE = "up"

_LOG_APPLYING = "Applying migration: %s"
_LOG_APPLIED = "Migration applied: %s"
_LOG_LOAD_FAILED = "Failed to load migration: %s"
_LOG_MISSING_UP = "Migration %s missing up() function"
_LOG_BASELINED = "Baselined %d migration(s) against the freshly created schema"


def _migration_files(migrations_dir: Path) -> list[Path]:
    """Return every migration file of one store in version order."""
    return sorted(
        f for f in migrations_dir.glob("*.py") if re.match(_VERSION_FILE_PATTERN, f.name) and f.name not in _SKIP_FILES
    )


async def _ensure_migrations_table(db: aiosqlite.Connection) -> None:
    """Create the migration ledger when it does not yet exist."""
    await db.execute(_CREATE_MIGRATIONS_TABLE_SQL)
    await db.commit()


async def _applied_versions(db: aiosqlite.Connection) -> set[str]:
    """Return the versions the ledger already records as applied."""
    cursor = await db.execute(_SELECT_APPLIED_SQL)
    rows = await cursor.fetchall()
    return {cast(str, row[0]) for row in rows}


async def baseline_migrations(db: aiosqlite.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> int:
    """Record every migration as applied without executing any of it.

    A database created from the current schema already holds the end state that
    the migration history exists to reach. Replaying that history over it is
    redundant where a migration's result is already present, and fatal where the
    schema has since been reshaped past the shape the migration was written
    against. Migrations upgrade databases born under an older schema; a database
    born under the current one has nothing to upgrade.

    Args:
        db: Database connection to a schema that was just created
        migrations_dir: The store's migration directory; defaults to the core database's

    Returns:
        Number of migrations recorded as applied
    """
    await _ensure_migrations_table(db)
    applied = await _applied_versions(db)

    baselined = 0
    for migration_file in _migration_files(migrations_dir):
        version = migration_file.stem
        if version in applied:
            continue
        await db.execute(_INSERT_APPLIED_SQL, (version,))
        baselined += 1
    await db.commit()

    logger.info(_LOG_BASELINED, baselined)
    return baselined


async def run_pending_migrations(
    db: aiosqlite.Connection,
    migrations_dir: Path = MIGRATIONS_DIR,
    store: MigrationStore = MigrationStore.CORE_DATABASE,
) -> int:
    """Run all pending migrations of one store in order.

    Args:
        db: Connection to the store's database file
        migrations_dir: The store's migration directory; defaults to the core database's
        store: The store whose owner signals before each migration; defaults to the core database

    Returns:
        Number of migrations applied
    """
    await _ensure_migrations_table(db)
    applied = await _applied_versions(db)

    applied_count = 0
    for migration_file in _migration_files(migrations_dir):
        version = migration_file.stem  # e.g., "001_add_ux_columns"

        if version in applied:
            continue

        logger.info(_LOG_APPLYING, version)

        # Load and execute migration
        spec = importlib.util.spec_from_file_location(version, migration_file)
        if spec is None or spec.loader is None:
            logger.error(_LOG_LOAD_FAILED, version)
            continue

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, _UP_ATTRIBUTE):
            logger.error(_LOG_MISSING_UP, version)
            continue

        signal_migration_started(store)
        await module.up(db)  # type: ignore[misc, unused-ignore]  # Dynamic module load

        await db.execute(_INSERT_APPLIED_SQL, (version,))
        await db.commit()

        logger.info(_LOG_APPLIED, version)
        applied_count += 1

    return applied_count
