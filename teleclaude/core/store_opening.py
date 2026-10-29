"""One path that opens every store the daemon opens at startup, through each owner's own initialization.

The daemon calls it as the first step of its startup, and the install act's migration entrypoint
calls it inside the stopped window, so the window opens exactly what the daemon would open and
open-time schema and data migrations run while no older reader serves. Each store's initialization
stays its owner's: the hook outbox move, the core database with its split stores and their migration
ledgers, the event store, the session mirrors and every registered project's todo store. Opening also
prunes the expired runtime state and compacts the files whose freed space crosses the threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from instrukt_ai_logging import get_logger

from teleclaude.core.db import db
from teleclaude.core.db.connection_factory import get_outbox_db_path
from teleclaude.core.db.outbox_migration import migrate_outbox_on_startup
from teleclaude.core.todos_db._adapter import get_todos_db
from teleclaude.events.db import get_event_db
from teleclaude.mirrors.store import ensure_mirrors_store
from teleclaude.paths import MAIN_DB_PATH, TELECLAUDE_HOME
from teleclaude.project_manifest import load_roots

logger = get_logger(__name__)

_PROJECT_STORE_OPEN_FAILED = "project_todo_store_open_failed"


@dataclass(frozen=True)
class StoreOpening:
    """What the opening could not complete: the registered projects whose todo store would not open."""

    failed_projects: tuple[Path, ...]


async def open_stores() -> StoreOpening:
    """Open every startup store; a project's unopenable todo store is reported, never fatal to the others."""
    migrate_outbox_on_startup(str(MAIN_DB_PATH), str(get_outbox_db_path(TELECLAUDE_HOME)))
    await db.initialize()
    # The backlog of the tables that stay in the core database leaves before serving, so no maintenance
    # pass has to remove it while writers wait. The hourly pass retries what a failure here leaves.
    try:
        await db.prune_runtime_retention(datetime.now(UTC))
    except Exception:  # supervision boundary: housekeeping never keeps the stores from opening
        logger.error("store_opening_retention_failed", exc_info=True)
    await get_event_db()
    ensure_mirrors_store()
    # Compaction rewrites a file under its write lock, so it runs only here, while nothing is served.
    try:
        await db.compact_runtime_databases_if_needed()
    except Exception:  # supervision boundary: housekeeping never keeps the stores from opening
        logger.error("store_opening_compaction_failed", exc_info=True)
    failed: list[Path] = []
    for root in load_roots():
        try:
            await get_todos_db(root)
        except Exception:  # supervision boundary: one project's store never blocks the others
            logger.error(_PROJECT_STORE_OPEN_FAILED, project_root=str(root), exc_info=True)
            failed.append(root)
    return StoreOpening(failed_projects=tuple(failed))
