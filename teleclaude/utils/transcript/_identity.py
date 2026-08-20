"""Stable runtime-native identities for transcript entries."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from teleclaude.core.agents import AgentName

_ENTRY_UUID_FIELD = "uuid"
_IDENTITY_SEPARATOR = "␟"


def native_entry_id(entry: Mapping[str, object], agent_name: AgentName, *, timestamp: object, text: str) -> str:
    """Return a native UUID or deterministic entry-local fallback identity."""
    if agent_name is AgentName.CLAUDE:
        value = entry.get(_ENTRY_UUID_FIELD)
        if isinstance(value, str) and value:
            return value
    return hashlib.sha256(f"{timestamp}{_IDENTITY_SEPARATOR}{text}".encode()).hexdigest()
