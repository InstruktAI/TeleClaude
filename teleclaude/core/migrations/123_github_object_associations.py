"""Retain verified GitHub object creation provenance with session state."""

from __future__ import annotations

import aiosqlite

_CREATE_ASSOCIATIONS = """
CREATE TABLE IF NOT EXISTS github_object_associations (
    repository_id INTEGER NOT NULL,
    container_number INTEGER NOT NULL,
    object_kind TEXT NOT NULL,
    provider_id INTEGER NOT NULL,
    creation_json TEXT NOT NULL,
    PRIMARY KEY (repository_id, container_number, object_kind, provider_id)
)
"""


async def up(db: aiosqlite.Connection) -> None:
    """Add immutable creation records without reconstructing any existing provider object."""
    await db.execute(_CREATE_ASSOCIATIONS)
    await db.commit()
