"""Config-owned storage for legacy Discord identifiers awaiting their owner."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

from teleclaude.config._file_io import file_transaction
from teleclaude.paths import LEGACY_DISCORD_HANDOFF_PATH

_SOURCE = "source"
_LOGICAL_KEY = "logical_key"
_PROVIDER_ID = "provider_id"
_ENTRIES = "entries"
_INVALID_PAYLOAD = "Legacy Discord hand-off must contain an entries list"
_CONFLICT_MESSAGE = "Legacy Discord provider identifier conflicts for {key}"


@dataclass(frozen=True)
class LegacyDiscordProviderId:
    """One provider identifier retained only until reflection import completes."""

    source: str
    logical_key: str
    provider_id: int


@dataclass(frozen=True)
class LegacyDiscordProviderIds:
    """Retired Discord identifiers projected out of current-schema config input."""

    entries: tuple[LegacyDiscordProviderId, ...]

    @property
    def present(self) -> bool:
        """Return whether the stored document still carries legacy provider state."""
        return bool(self.entries)


def _decode(content: str) -> list[LegacyDiscordProviderId]:
    """Parse the persisted hand-off, rejecting malformed state."""
    if not content:
        return []
    payload: object = json.loads(content)
    if not isinstance(payload, dict) or not isinstance(payload.get(_ENTRIES), list):
        raise ValueError(_INVALID_PAYLOAD)
    entries: list[LegacyDiscordProviderId] = []
    for row in payload[_ENTRIES]:
        if not isinstance(row, dict):
            raise ValueError(_INVALID_PAYLOAD)
        source = row.get(_SOURCE)
        logical_key = row.get(_LOGICAL_KEY)
        provider_id = row.get(_PROVIDER_ID)
        if not isinstance(source, str) or not isinstance(logical_key, str) or not isinstance(provider_id, int):
            raise ValueError(_INVALID_PAYLOAD)
        entries.append(LegacyDiscordProviderId(source, logical_key, provider_id))
    return entries


def _encode(entries: Iterable[LegacyDiscordProviderId]) -> str:
    """Serialize the logical-key map in stable order."""
    rows = [
        {_SOURCE: entry.source, _LOGICAL_KEY: entry.logical_key, _PROVIDER_ID: entry.provider_id}
        for entry in sorted(entries, key=lambda item: item.logical_key)
    ]
    return json.dumps({_ENTRIES: rows}, indent=2) + "\n"


def append(entries: tuple[LegacyDiscordProviderId, ...], *, conflict_type: type[ValueError]) -> None:
    """Atomically append entries, rejecting any existing key with another value."""
    with file_transaction(LEGACY_DISCORD_HANDOFF_PATH) as transaction:
        existing = _decode(transaction.read_text(encoding="utf-8"))
        by_key = {entry.logical_key: entry for entry in existing}
        for entry in entries:
            current = by_key.get(entry.logical_key)
            if current is not None and current.provider_id != entry.provider_id:
                raise conflict_type(_CONFLICT_MESSAGE.format(key=entry.logical_key))
            by_key.setdefault(entry.logical_key, entry)
        if len(by_key) != len(existing):
            transaction.replace_text(_encode(by_key.values()))


def read() -> LegacyDiscordProviderIds:
    """Read all values currently in the hand-off."""
    try:
        content = LEGACY_DISCORD_HANDOFF_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        content = ""
    return LegacyDiscordProviderIds(tuple(_decode(content)))


def clear(logical_keys: frozenset[str] | None = None) -> None:
    """Clear all entries or only the selected logical keys under the hand-off lock."""
    with file_transaction(LEGACY_DISCORD_HANDOFF_PATH) as transaction:
        entries = _decode(transaction.read_text(encoding="utf-8"))
        remaining = [entry for entry in entries if logical_keys is not None and entry.logical_key not in logical_keys]
        if len(remaining) != len(entries):
            transaction.replace_text(_encode(remaining))
