"""One path that opens every store the daemon opens at startup, through each owner's own initialization.

The daemon calls it as the first step of its startup, and the install act's migration entrypoint
calls it inside the stopped window, so the window opens exactly what the daemon would open and
open-time schema and data migrations run while no older reader serves. Each store's initialization
stays its owner's: the hook outbox move, the core database and its migration ledger, the event
store, the session mirrors and every registered project's todo store.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    await get_event_db()
    ensure_mirrors_store()
    failed: list[Path] = []
    for root in load_roots():
        try:
            await get_todos_db(root)
        except Exception:  # supervision boundary: one project's store never blocks the others
            logger.error(_PROJECT_STORE_OPEN_FAILED, project_root=str(root), exc_info=True)
            failed.append(root)
    return StoreOpening(failed_projects=tuple(failed))
