"""Normalize absent GitHub parent provenance without inferring workflow authority."""

from __future__ import annotations

import aiosqlite

_NORMALIZE_PARENT = """
UPDATE github_session_bindings
SET binding_json = json_insert(binding_json, '$.workflow_parent', NULL)
WHERE CASE WHEN json_valid(binding_json) THEN
    json_type(binding_json) = 'object'
    AND json_type(binding_json, '$.workflow_parent') IS NULL
ELSE 0 END
"""


async def up(db: aiosqlite.Connection) -> None:
    """Make missing provenance explicit null; retain existing values and all unrelated fields."""
    # Invalid/non-object payloads stay invalid; migration never repairs a partial binding.
    await db.execute(_NORMALIZE_PARENT)
    await db.commit()
