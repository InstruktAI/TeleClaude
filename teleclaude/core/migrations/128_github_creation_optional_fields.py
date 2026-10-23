"""Normalize absent GitHub creation fields without reconstructing attribution or placement."""

from __future__ import annotations

import aiosqlite

_NORMALIZE_CREATION = """
UPDATE github_object_associations
SET creation_json = json_insert(
    creation_json,
    '$.pull_request', NULL,
    '$.review_comment', NULL,
    '$.producer_principal', NULL,
    '$.producer_computer', NULL,
    '$.producer_target', NULL
)
WHERE CASE WHEN json_valid(creation_json) THEN
    json_type(creation_json) = 'object'
    AND (
        json_type(creation_json, '$.pull_request') IS NULL
        OR json_type(creation_json, '$.review_comment') IS NULL
        OR json_type(creation_json, '$.producer_principal') IS NULL
        OR json_type(creation_json, '$.producer_computer') IS NULL
        OR json_type(creation_json, '$.producer_target') IS NULL
    )
ELSE 0 END
"""


async def up(db: aiosqlite.Connection) -> None:
    """Make missing fields explicit null while preserving every present value and creator fact."""
    # Invalid/non-object payloads remain invalid; null supplies no missing provenance or placement.
    await db.execute(_NORMALIZE_CREATION)
    await db.commit()
