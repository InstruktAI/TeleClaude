"""Remove file and derived-read state from persisted procedure invocations."""

from __future__ import annotations

import json
from collections.abc import MutableMapping
from enum import StrEnum
from typing import Final, TypedDict, cast

import aiosqlite
from instrukt_ai_logging import get_logger

logger = get_logger(__name__)


class RetiredInvocationField(StrEnum):
    """Persisted invocation keys retired by the reference-loader cutover."""

    ENTRY_READS = "entry_reads"
    BRIEF_PATH = "brief_path"


class LaunchIntentPayload(TypedDict, total=False):
    """The launch-intent field containing a persisted procedure invocation."""

    invocation: object


_HANDOVERS_TABLE: Final = "session_startup_handovers"
_SELECT_HANDOVERS_SQL: Final = f"SELECT session_id, launch_intent_json FROM {_HANDOVERS_TABLE}"
_UPDATE_HANDOVER_SQL: Final = f"UPDATE {_HANDOVERS_TABLE} SET launch_intent_json = ? WHERE session_id = ?"
_INVOCATION_KEY: Final = "invocation"
_MIGRATION_COMPLETE_EVENT: Final = "procedure invocation loader migration complete"


def _remove_retired_invocation_fields(invocation: MutableMapping[str, object]) -> None:
    """Remove retired persisted keys using their semantic owner."""
    for field in RetiredInvocationField:
        invocation.pop(field.value, None)


def _migrate_launch_intent(raw: str) -> str | None:
    """Return a current-shape launch intent when its invocation carries retired keys."""
    payload: object = json.loads(raw)
    if not isinstance(payload, dict) or not all(isinstance(key, str) for key in payload):
        return None
    intent = cast(LaunchIntentPayload, payload)
    raw_invocation: object = intent.get(_INVOCATION_KEY)
    if not isinstance(raw_invocation, dict) or not all(isinstance(key, str) for key in raw_invocation):
        return None
    if not any(field.value in raw_invocation for field in RetiredInvocationField):
        return None
    _remove_retired_invocation_fields(raw_invocation)
    intent[_INVOCATION_KEY] = raw_invocation
    return json.dumps(intent, ensure_ascii=False)


async def up(db: aiosqlite.Connection) -> None:
    """Rewrite every stored launch intent carrying retired invocation fields in one transaction."""
    async with db.execute(_SELECT_HANDOVERS_SQL) as cursor:
        rows = [(str(row[0]), str(row[1])) for row in await cursor.fetchall()]

    updates: list[tuple[str, str]] = []
    for session_id, raw in rows:
        migrated = _migrate_launch_intent(raw)
        if migrated is not None:
            updates.append((session_id, migrated))

    await db.execute("BEGIN")
    try:
        for session_id, launch_intent_json in updates:
            await db.execute(_UPDATE_HANDOVER_SQL, (launch_intent_json, session_id))
    except Exception:
        await db.rollback()
        raise
    await db.commit()
    logger.info(_MIGRATION_COMPLETE_EVENT, migrated_count=len(updates))


async def down(db: aiosqlite.Connection) -> None:
    """The removed file path and derived-read values have no valid reverse migration."""
    del db
