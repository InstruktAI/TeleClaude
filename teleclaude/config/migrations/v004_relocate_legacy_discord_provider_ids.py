"""Move retired machine Discord provider identifiers to a config-owned hand-off."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from typing import Final, cast

from teleclaude.config.legacy_discord_handoff import LegacyDiscordProviderId, append
from teleclaude.config.migrations._chain import Destination
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef

VERSION: Final = 4
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
MOVES: Final = Destination.HANDOFF
_DISCORD = "discord"
_COMPUTER = "computer"
_TRUSTED_DIRS = "trusted_dirs"
_CATEGORIES = "categories"
_DISCORD_FORUM = "discord_forum"
_NAME = "name"
_HANDOFF_TYPE_ERROR = "Legacy Discord hand-off requires provider identifier records"
_LEGACY_FIELDS: Final = frozenset(
    {
        "help_desk_channel_id",
        "escalation_channel_id",
        "all_sessions_channel_id",
        "operator_chat_channel_id",
        "announcements_channel_id",
        "general_channel_id",
    }
)


class HandoffConflict(ValueError):
    """A hand-off destination already owns a different identifier for a key."""


def _entries(document: Mapping[str, object]) -> tuple[LegacyDiscordProviderId, ...]:
    """Project valid retired integer identifiers using their logical destination keys."""
    values: list[LegacyDiscordProviderId] = []
    discord = document.get(_DISCORD)
    if isinstance(discord, MutableMapping):
        for field in _LEGACY_FIELDS:
            value = discord.get(field)
            if isinstance(value, int) and not isinstance(value, bool):
                source = f"{_DISCORD}.{field}"
                values.append(LegacyDiscordProviderId(source, source, value))
        categories = discord.get(_CATEGORIES)
        if isinstance(categories, MutableMapping):
            for name, value in categories.items():
                if isinstance(name, str) and isinstance(value, int) and not isinstance(value, bool):
                    source = f"{_DISCORD}.{_CATEGORIES}.{name}"
                    values.append(LegacyDiscordProviderId(source, source, value))
    computer = document.get(_COMPUTER)
    trusted_dirs = computer.get(_TRUSTED_DIRS) if isinstance(computer, MutableMapping) else None
    if isinstance(trusted_dirs, list):
        for index, entry in enumerate(trusted_dirs):
            if not isinstance(entry, MutableMapping):
                continue
            value = entry.get(_DISCORD_FORUM)
            if isinstance(value, int) and not isinstance(value, bool):
                source = f"{_COMPUTER}.{_TRUSTED_DIRS}.{index}.{_DISCORD_FORUM}"
                values.append(LegacyDiscordProviderId(source, f"project_forum:{entry.get(_NAME, index)}", value))
    return tuple(values)


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Drop retired Discord provider identifiers from the current document view."""
    discord = document.get(_DISCORD)
    if isinstance(discord, MutableMapping):
        for field in _LEGACY_FIELDS | {_CATEGORIES}:
            discord.pop(field, None)
    computer = document.get(_COMPUTER)
    trusted_dirs = computer.get(_TRUSTED_DIRS) if isinstance(computer, MutableMapping) else None
    if isinstance(trusted_dirs, list):
        for entry in trusted_dirs:
            if isinstance(entry, MutableMapping):
                entry.pop(_DISCORD_FORUM, None)


def pending(document: Mapping[str, object], _subject: SubjectRef) -> tuple[LegacyDiscordProviderId, ...] | None:
    """Return retired identifiers still carried by the source document."""
    entries = _entries(document)
    return entries or None


def deliver(value: object, _subject: SubjectRef) -> None:
    """Append all identifiers atomically to the config-owned hand-off."""
    if not isinstance(value, tuple) or any(not isinstance(entry, LegacyDiscordProviderId) for entry in value):
        raise TypeError(_HANDOFF_TYPE_ERROR)
    append(cast(tuple[LegacyDiscordProviderId, ...], value), conflict_type=HandoffConflict)
