"""Config-owned storage for legacy Discord identifiers awaiting their owner."""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from teleclaude.file_transaction import file_transaction
from teleclaude.paths import LEGACY_DISCORD_HANDOFF_PATH

_SOURCE = "source"
_LOGICAL_KEY = "logical_key"
_PROVIDER_ID = "provider_id"
_FOLDER = "folder"
_ENTRIES = "entries"
_PROJECT_FORUM_BINDINGS = "project_forum_bindings"
_INVALID_PAYLOAD = "Legacy Discord hand-off must contain an entries list"
_CONFLICT_MESSAGE = "Legacy Discord provider identifier conflicts for {key}"
_PROJECT_FORUM_CONFLICT_MESSAGE = "Legacy Discord project forum binding conflicts for {key}"
_UTF8 = "utf-8"


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


@dataclass(frozen=True)
class LegacyProjectForumBinding:
    """Bind a retired name-based forum key to the folder that owned it."""

    logical_key: str
    folder: Path


@dataclass(frozen=True)
class LegacyProjectForumBindings:
    """Conflict-free project forum bindings projected from hand-off sources."""

    entries: tuple[LegacyProjectForumBinding, ...]

    @property
    def present(self) -> bool:
        """Return whether any project forum binding remains in transit."""
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


def _decode_project_forum_bindings(content: str) -> list[LegacyProjectForumBinding]:
    """Parse persisted project forum bindings, rejecting malformed state."""
    if not content:
        return []
    payload: object = json.loads(content)
    if not isinstance(payload, dict):
        raise ValueError(_INVALID_PAYLOAD)
    raw_bindings = payload.get(_PROJECT_FORUM_BINDINGS, [])
    if not isinstance(raw_bindings, list):
        raise ValueError(_INVALID_PAYLOAD)
    bindings: list[LegacyProjectForumBinding] = []
    for row in raw_bindings:
        if not isinstance(row, dict):
            raise ValueError(_INVALID_PAYLOAD)
        logical_key = row.get(_LOGICAL_KEY)
        folder = row.get(_FOLDER)
        if not isinstance(logical_key, str) or not isinstance(folder, str):
            raise ValueError(_INVALID_PAYLOAD)
        bindings.append(LegacyProjectForumBinding(logical_key, Path(folder).expanduser().resolve()))
    return bindings


def _encode(
    entries: Iterable[LegacyDiscordProviderId],
    bindings: Iterable[LegacyProjectForumBinding],
) -> str:
    """Serialize both hand-off families in stable logical-key order."""
    rows = [
        {_SOURCE: entry.source, _LOGICAL_KEY: entry.logical_key, _PROVIDER_ID: entry.provider_id}
        for entry in sorted(entries, key=lambda item: item.logical_key)
    ]
    binding_rows = [
        {_LOGICAL_KEY: entry.logical_key, _FOLDER: str(entry.folder)}
        for entry in sorted(bindings, key=lambda item: item.logical_key)
    ]
    return json.dumps({_ENTRIES: rows, _PROJECT_FORUM_BINDINGS: binding_rows}, indent=2) + "\n"


def append(entries: tuple[LegacyDiscordProviderId, ...], *, conflict_type: type[ValueError]) -> None:
    """Atomically append entries, rejecting any existing key with another value."""
    with file_transaction(LEGACY_DISCORD_HANDOFF_PATH) as transaction:
        content = transaction.read_text(encoding=_UTF8)
        existing = _decode(content)
        bindings = _decode_project_forum_bindings(content)
        by_key = {entry.logical_key: entry for entry in existing}
        for entry in entries:
            current = by_key.get(entry.logical_key)
            if current is not None and current.provider_id != entry.provider_id:
                raise conflict_type(_CONFLICT_MESSAGE.format(key=entry.logical_key))
            by_key.setdefault(entry.logical_key, entry)
        if len(by_key) != len(existing):
            transaction.replace_text(_encode(by_key.values(), bindings))


def append_project_forum_bindings(
    bindings: tuple[LegacyProjectForumBinding, ...],
    *,
    conflict_type: type[ValueError],
) -> None:
    """Atomically bind legacy logical keys to folders, rejecting conflicting owners."""
    with file_transaction(LEGACY_DISCORD_HANDOFF_PATH) as transaction:
        content = transaction.read_text(encoding=_UTF8)
        entries = _decode(content)
        existing = _decode_project_forum_bindings(content)
        by_key = {entry.logical_key: entry for entry in existing}
        for binding in bindings:
            normalized = LegacyProjectForumBinding(binding.logical_key, binding.folder.expanduser().resolve())
            current = by_key.get(normalized.logical_key)
            if current is not None and current.folder != normalized.folder:
                raise conflict_type(_PROJECT_FORUM_CONFLICT_MESSAGE.format(key=normalized.logical_key))
            by_key.setdefault(normalized.logical_key, normalized)
        if len(by_key) != len(existing):
            transaction.replace_text(_encode(entries, by_key.values()))


def read() -> LegacyDiscordProviderIds:
    """Read all values currently in the hand-off."""
    try:
        content = LEGACY_DISCORD_HANDOFF_PATH.read_text(encoding=_UTF8)
    except FileNotFoundError:
        content = ""
    return LegacyDiscordProviderIds(tuple(_decode(content)))


def read_project_forum_bindings() -> LegacyProjectForumBindings:
    """Read project forum bindings currently stored in the hand-off."""
    try:
        content = LEGACY_DISCORD_HANDOFF_PATH.read_text(encoding=_UTF8)
    except FileNotFoundError:
        content = ""
    return LegacyProjectForumBindings(tuple(_decode_project_forum_bindings(content)))


def clear(logical_keys: frozenset[str] | None = None) -> None:
    """Clear all entries or only the selected logical keys under the hand-off lock."""
    with file_transaction(LEGACY_DISCORD_HANDOFF_PATH) as transaction:
        content = transaction.read_text(encoding=_UTF8)
        entries = _decode(content)
        bindings = _decode_project_forum_bindings(content)
        remaining = [entry for entry in entries if logical_keys is not None and entry.logical_key not in logical_keys]
        if len(remaining) != len(entries):
            transaction.replace_text(_encode(remaining, bindings))


def clear_project_forum_bindings(logical_keys: frozenset[str] | None = None) -> None:
    """Clear all project forum bindings or only selected keys under the hand-off lock."""
    with file_transaction(LEGACY_DISCORD_HANDOFF_PATH) as transaction:
        content = transaction.read_text(encoding=_UTF8)
        entries = _decode(content)
        bindings = _decode_project_forum_bindings(content)
        remaining = [
            binding for binding in bindings if logical_keys is not None and binding.logical_key not in logical_keys
        ]
        if len(remaining) != len(bindings):
            transaction.replace_text(_encode(entries, remaining))
