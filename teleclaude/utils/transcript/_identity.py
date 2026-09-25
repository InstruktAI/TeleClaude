"""Stable runtime-native identities for transcript entries."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from teleclaude.core.agents import AgentName

_ENTRY_UUID_FIELD = "uuid"
_ENTRY_TIMESTAMP_FIELD = "timestamp"


def native_entry_id(entry: Mapping[str, object], agent_name: AgentName) -> str | None:
    """Return the entry's native identity, independent of how its content is classified.

    Claude stamps each entry with a UUID. Every runtime stamps each accepted
    input with its own write time, which no second input shares, so the
    timestamp identifies the entry wherever no UUID exists. An entry carrying
    neither has no identity rather than a colliding one.
    """
    if agent_name is AgentName.CLAUDE:
        value = entry.get(_ENTRY_UUID_FIELD)
        if isinstance(value, str) and value:
            return value
    timestamp = entry.get(_ENTRY_TIMESTAMP_FIELD)
    if not isinstance(timestamp, str) or not timestamp:
        return None
    return hashlib.sha256(timestamp.encode()).hexdigest()
