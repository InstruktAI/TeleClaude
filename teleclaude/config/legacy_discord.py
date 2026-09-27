"""Published reader and clear operation for legacy Discord provider IDs."""

from __future__ import annotations

from collections.abc import Mapping

from teleclaude.config._file_io import file_transaction
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.legacy_discord_handoff import LegacyDiscordProviderId, LegacyDiscordProviderIds, clear, read
from teleclaude.config.migrations import Destination, MigrationTrigger, in_transit, migrate_document
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import MACHINE_CONFIG_PATH

_COMPUTER_SUBJECT = SubjectRef(ConfigSubjectKind.COMPUTER)
_HANDOFF_DESTINATION = Destination.HANDOFF


def _machine_document() -> Mapping[str, object] | None:
    """Read the stored machine document without validating or rewriting it."""
    with file_transaction(MACHINE_CONFIG_PATH) as transaction:
        content = transaction.read_text(encoding="utf-8")
    if not content:
        return {}
    document: object = round_trip_yaml().load(content)
    return document if isinstance(document, Mapping) else None


def legacy_discord_provider_ids() -> LegacyDiscordProviderIds:
    """Return conflict-free identifiers from the hand-off and the in-transit machine document."""
    entries_by_key: dict[str, list[LegacyDiscordProviderId]] = {}
    for entry in read().entries:
        entries_by_key.setdefault(entry.logical_key, []).append(entry)
    document = _machine_document()
    if document is not None:
        for batch in in_transit(document, _COMPUTER_SUBJECT, _HANDOFF_DESTINATION):
            if isinstance(batch, tuple):
                for entry in batch:
                    if isinstance(entry, LegacyDiscordProviderId):
                        entries_by_key.setdefault(entry.logical_key, []).append(entry)
    entries: list[LegacyDiscordProviderId] = []
    for logical_key in sorted(entries_by_key):
        matches = entries_by_key[logical_key]
        if len({entry.provider_id for entry in matches}) == 1:
            entries.append(matches[0])
    return LegacyDiscordProviderIds(tuple(entries))


def clear_legacy_discord_provider_ids() -> None:
    """Store the machine document current, then clear only imported hand-off keys."""
    imported = legacy_discord_provider_ids()
    if not imported.present:
        return
    migrate_document(MACHINE_CONFIG_PATH, _COMPUTER_SUBJECT, MigrationTrigger.WRITER)
    clear(frozenset(entry.logical_key for entry in imported.entries))
