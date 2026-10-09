"""Published reader and clear operation for legacy Discord provider IDs."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from teleclaude.config.legacy_discord_handoff import (
    LegacyDiscordProviderId,
    LegacyDiscordProviderIds,
    LegacyProjectForumBinding,
    LegacyProjectForumBindings,
    clear,
    clear_project_forum_bindings,
    read,
    read_project_forum_bindings,
)
from teleclaude.config.machine_config_mutation import stored_machine_document
from teleclaude.config.migrations._chain import Destination, MigrationTrigger, in_transit
from teleclaude.config.migrations._runner import migrate_document
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import MACHINE_CONFIG_PATH

_COMPUTER_SUBJECT = SubjectRef(ConfigSubjectKind.COMPUTER)
_HANDOFF_DESTINATION = Destination.HANDOFF
_PROJECT_REGISTRY_DESTINATION = Destination.PROJECT_REGISTRY
_PROJECT_FORUM_PREFIX = "project_forum:"
_NAME_FIELD = "name"
_PATH_FIELD = "path"
_UTF8 = "utf-8"


def legacy_discord_provider_ids() -> LegacyDiscordProviderIds:
    """Return conflict-free identifiers from the hand-off and the in-transit machine document."""
    entries_by_key: dict[str, list[LegacyDiscordProviderId]] = {}
    for entry in read().entries:
        entries_by_key.setdefault(entry.logical_key, []).append(entry)
    document = stored_machine_document()
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


def legacy_project_forum_bindings() -> LegacyProjectForumBindings:
    """Return conflict-free forum-key bindings from stored and in-transit sources."""
    entries_by_key: dict[str, list[LegacyProjectForumBinding]] = {}
    for binding in read_project_forum_bindings().entries:
        entries_by_key.setdefault(binding.logical_key, []).append(binding)
    document = stored_machine_document()
    if document is not None:
        batches = in_transit(document, _COMPUTER_SUBJECT, _PROJECT_REGISTRY_DESTINATION)
        for batch in batches:
            if not isinstance(batch, tuple):
                continue
            for row in batch:
                if not isinstance(row, Mapping):
                    continue
                name = row.get(_NAME_FIELD)
                folder = row.get(_PATH_FIELD)
                if not isinstance(name, str) or not name or not isinstance(folder, str) or not folder:
                    continue
                binding = LegacyProjectForumBinding(
                    logical_key=f"{_PROJECT_FORUM_PREFIX}{name}",
                    folder=Path(folder).expanduser().resolve(),
                )
                entries_by_key.setdefault(binding.logical_key, []).append(binding)
    entries: list[LegacyProjectForumBinding] = []
    for logical_key in sorted(entries_by_key):
        matches = entries_by_key[logical_key]
        folders = {binding.folder for binding in matches}
        if len(folders) == 1:
            entries.append(matches[0])
    return LegacyProjectForumBindings(tuple(entries))


def clear_legacy_project_forum_bindings(logical_keys: frozenset[str] | None = None) -> None:
    """Store the machine document current, then clear selected forum bindings."""
    imported = legacy_project_forum_bindings()
    if not imported.present:
        return
    migrate_document(MACHINE_CONFIG_PATH, _COMPUTER_SUBJECT, MigrationTrigger.WRITER)
    selected_keys = (
        logical_keys if logical_keys is not None else frozenset(binding.logical_key for binding in imported.entries)
    )
    clear_project_forum_bindings(selected_keys)
