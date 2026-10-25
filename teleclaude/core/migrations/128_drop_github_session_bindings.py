"""Drop the persistence of the abandoned two-agent GitHub workflow: session bindings and object associations."""

from __future__ import annotations

import aiosqlite

_DROP_BINDINGS = "DROP TABLE IF EXISTS github_session_bindings"
_DROP_ASSOCIATIONS = "DROP TABLE IF EXISTS github_object_associations"


async def up(db: aiosqlite.Connection) -> None:
    """Remove both tables; nothing on main reads or writes them, whatever rows they hold."""
    await db.execute(_DROP_BINDINGS)
    await db.execute(_DROP_ASSOCIATIONS)
    await db.commit()
