"""Database migration runner - executes pending migrations in order."""

import importlib.util
import re
from pathlib import Path
from typing import cast

import aiosqlite
from instrukt_ai_logging import get_logger

from teleclaude.core.migrations.constants import INIT_FILE_NAME

logger = get_logger(__name__)

MIGRATIONS_DIR = Path(__file__).parent


async def run_pending_migrations(db: aiosqlite.Connection) -> int:
    """Run all pending migrations in order.

    Args:
        db: Database connection

    Returns:
        Number of migrations applied
    """
    # Ensure schema_migrations table exists
    await db.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db.commit()

    # Get applied migrations
    cursor = await db.execute("SELECT version FROM schema_migrations")
    rows = await cursor.fetchall()
    applied: set[str] = set()
    for row in rows:
        applied.add(cast(str, row[0]))

    # Find migration files (###_name.py pattern)
    migration_files = sorted(
        f for f in MIGRATIONS_DIR.glob("*.py") if re.match(r"^\d{3}_", f.name) and f.name != INIT_FILE_NAME
    )

    applied_count = 0
    for migration_file in migration_files:
        version = migration_file.stem  # e.g., "001_add_ux_columns"

        if version in applied:
            continue

        logger.info("Applying migration: %s", version)

        # Load and execute migration
        spec = importlib.util.spec_from_file_location(version, migration_file)
        if spec is None or spec.loader is None:
            logger.error("Failed to load migration: %s", version)
            continue

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        if not hasattr(module, "up"):
            logger.error("Migration %s missing up() function", version)
            continue

        await module.up(db)  # type: ignore[misc]  # Dynamic module load

        # Record migration
        await db.execute(
            "INSERT INTO schema_migrations (version) VALUES (?)",
            (version,),
        )
        await db.commit()

        logger.info("Migration applied: %s", version)
        applied_count += 1

    return applied_count
