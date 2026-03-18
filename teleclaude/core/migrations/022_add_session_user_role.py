"""Legacy no-op for retired user_role migration slot."""
# pylint: disable=invalid-name  # Migration filenames are versioned on purpose.


from __future__ import annotations

import aiosqlite


async def up(db: aiosqlite.Connection) -> None:
    """Retired migration slot kept for ordering stability."""
    await db.commit()


async def down(_db: aiosqlite.Connection) -> None:
    """Retired migration slot kept for ordering stability."""
