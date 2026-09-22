"""Lossless normalization of recognized stored configuration fields."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Final

from ruamel.yaml import YAML

from teleclaude.config._file_io import FileTransaction, file_transaction
from teleclaude.config.schema import PersonEntry
from teleclaude.paths import INVITATIONS_PATH, ConfigFileName

_YAML = YAML()
_YAML.preserve_quotes = True
_GIT: Final = "git"
_CHECKOUT_ROOT: Final = "checkout_root"
_PEOPLE: Final = "people"
_SLUG: Final = "slug"
_EXPERTISE: Final = "expertise"
_PREFERENCES: Final = "preferences"
_SETTINGS: Final = "settings"
_OUTPUT_VISIBILITY: Final = "output_visibility"
_NOTIFICATIONS: Final = "notifications"
_SYSTEM_MESSAGES: Final = "system_messages"
_TOOL_CALLS: Final = "tool_calls"
_LEGACY_OUTPUT_VISIBILITY_WEB: Final = "web"
_OUTPUT_VISIBILITY_FULL: Final = "full"
_COMPUTER: Final = "computer"
_TMUX_BINARY: Final = "tmux_binary"
_API: Final = "api"
_TCP_PORT: Final = "tcp_port"
_INVITE_TOKEN: Final = "invite_token"
_LEGACY_GIT_CONFLICT: Final = "Legacy git.checkout_root conflicts with checkout_root in {path}"
_PEOPLE_MAPPING_ERROR: Final = "Invalid people mapping in {path}"
_LEGACY_FIELD_CONFLICT: Final = "Legacy {field} conflicts for {path}"
_INVITE_TOKEN_ERROR: Final = "invite_token must be a non-empty string in {path}"
_INVITATIONS_MAPPING_ERROR: Final = "Invitations store must be a mapping"
_INVITATION_OWNERSHIP_ERROR: Final = "Invitation token ownership conflicts for {path}"
_DOCUMENT_MAPPING_ERROR: Final = "Configuration document must be a mapping"
_JSON_INDENT: Final = 2
_NEWLINE: Final = "\n"
_DISCORD: Final = "discord"
_CREDS: Final = "creds"
_VOICE_CHANNEL_ID: Final = "voice_channel_id"
_COMPUTER_SECTION: Final = "computer"
_TRUSTED_DIRS: Final = "trusted_dirs"
_NAME: Final = "name"
_DISCORD_FORUM: Final = "discord_forum"
_CATEGORIES: Final = "categories"
_LEGACY_DISCORD_FIELD_NAMES: Final = frozenset(
    {
        "help_desk_channel_id",
        "escalation_channel_id",
        "all_sessions_channel_id",
        "operator_chat_channel_id",
        "announcements_channel_id",
        "general_channel_id",
    }
)


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


def partition_legacy_discord_provider_ids(
    raw_document: object,
) -> tuple[dict[object, object], LegacyDiscordProviderIds]:
    """Return a current-schema projection while retaining the source document unchanged."""
    if not isinstance(raw_document, dict):
        return {}, LegacyDiscordProviderIds(entries=())
    projected = deepcopy(raw_document)
    entries: list[LegacyDiscordProviderId] = []
    discord = projected.get(_DISCORD)
    if isinstance(discord, dict):
        for field in _LEGACY_DISCORD_FIELD_NAMES:
            value = discord.pop(field, None)
            if isinstance(value, int):
                source = f"{_DISCORD}.{field}"
                entries.append(LegacyDiscordProviderId(source=source, logical_key=source, provider_id=value))
        categories = discord.pop(_CATEGORIES, None)
        if isinstance(categories, dict):
            for name, value in categories.items():
                if isinstance(value, int):
                    entries.append(
                        LegacyDiscordProviderId(
                            source=f"{_DISCORD}.{_CATEGORIES}.{name}",
                            logical_key=f"{_DISCORD}.{_CATEGORIES}.{name}",
                            provider_id=value,
                        )
                    )
    computer = projected.get(_COMPUTER_SECTION)
    trusted_dirs = computer.get(_TRUSTED_DIRS) if isinstance(computer, dict) else None
    if isinstance(trusted_dirs, list):
        for index, entry in enumerate(trusted_dirs):
            if not isinstance(entry, dict):
                continue
            value = entry.pop(_DISCORD_FORUM, None)
            if isinstance(value, int):
                entries.append(
                    LegacyDiscordProviderId(
                        source=f"{_COMPUTER_SECTION}.{_TRUSTED_DIRS}.{index}.{_DISCORD_FORUM}",
                        logical_key=f"project_forum:{entry.get(_NAME, index)}",
                        provider_id=value,
                    )
                )
    return projected, LegacyDiscordProviderIds(entries=tuple(entries))


def contains_legacy_discord_provider_fields(raw_document: object) -> bool:
    """Return whether a raw edit candidate introduces retired provider-ID keys."""
    if not isinstance(raw_document, dict):
        return False
    discord = raw_document.get(_DISCORD)
    if isinstance(discord, dict) and (set(discord) & _LEGACY_DISCORD_FIELD_NAMES or _CATEGORIES in discord):
        return True
    computer = raw_document.get(_COMPUTER_SECTION)
    trusted_dirs = computer.get(_TRUSTED_DIRS) if isinstance(computer, dict) else None
    return isinstance(trusted_dirs, list) and any(
        isinstance(entry, dict) and _DISCORD_FORUM in entry for entry in trusted_dirs
    )


def migrate_global_file(path: Path, people_dir: Path | None = None) -> bool:
    """Promote global legacy fields and registered canonical-person metadata."""
    changed = False
    with file_transaction(path) as global_transaction:
        global_document = _load_mapping(global_transaction.read_text())
        git = global_document.get(_GIT)
        if isinstance(git, dict) and _CHECKOUT_ROOT in git:
            legacy = git[_CHECKOUT_ROOT]
            current = global_document.get(_CHECKOUT_ROOT)
            if current is not None and current != legacy:
                raise ValueError(_LEGACY_GIT_CONFLICT.format(path=path))
            global_document[_CHECKOUT_ROOT] = legacy
            git.pop(_CHECKOUT_ROOT)
            if not git:
                global_document.pop(_GIT)
            changed = True

        if people_dir is None:
            if changed:
                _write_mapping(global_transaction, global_document)
            return changed
        people = global_document.get(_PEOPLE, [])
        if not isinstance(people, list):
            raise ValueError(_PEOPLE_MAPPING_ERROR.format(path=path))
        for entry in people:
            if not isinstance(entry, dict) or not entry.get(_SLUG):
                continue
            person_path = people_dir / str(entry[_SLUG]) / ConfigFileName.OVERLAY
            if not person_path.exists():
                continue
            with file_transaction(person_path) as person_transaction:
                person_document = _load_mapping(person_transaction.read_text())
                moved: list[str] = []
                for field in (_EXPERTISE, _PREFERENCES):
                    if field not in person_document:
                        continue
                    legacy = person_document[field]
                    current = entry.get(field)
                    if current is not None and current != legacy:
                        raise ValueError(_LEGACY_FIELD_CONFLICT.format(field=field, path=person_path))
                    candidate = dict(entry)
                    candidate[field] = legacy
                    PersonEntry.model_validate(candidate)
                    entry[field] = legacy
                    moved.append(field)
                if moved:
                    _write_mapping(global_transaction, global_document)
                    for field in moved:
                        person_document.pop(field)
                    _write_mapping(person_transaction, person_document)
                    changed = True
        if changed:
            _write_mapping(global_transaction, global_document)
    return changed


def remove_person_notifications(path: Path) -> bool:
    """Remove the retired per-person output notification preference."""
    with file_transaction(path) as transaction:
        document = _load_mapping(transaction.read_text())
        settings = document.get(_SETTINGS)
        visibility = settings.get(_OUTPUT_VISIBILITY) if isinstance(settings, dict) else None
        if not isinstance(visibility, dict) or _NOTIFICATIONS not in visibility:
            return False
        visibility.pop(_NOTIFICATIONS)
        _write_mapping(transaction, document)
        return True


def rename_person_output_visibility_web_value(path: Path) -> bool:
    """Rewrite the retired ``web`` output-visibility token to ``full``."""
    with file_transaction(path) as transaction:
        document = _load_mapping(transaction.read_text())
        settings = document.get(_SETTINGS)
        visibility = settings.get(_OUTPUT_VISIBILITY) if isinstance(settings, dict) else None
        if not isinstance(visibility, dict):
            return False
        changed = False
        for field in (_SYSTEM_MESSAGES, _TOOL_CALLS):
            if visibility.get(field) == _LEGACY_OUTPUT_VISIBILITY_WEB:
                visibility[field] = _OUTPUT_VISIBILITY_FULL
                changed = True
        if not changed:
            return False
        _write_mapping(transaction, document)
        return True


def remove_person_voice_channel_id(path: Path) -> bool:
    """Drop the retired configured room; Discord voice state now owns it."""
    with file_transaction(path) as transaction:
        document = _load_mapping(transaction.read_text())
        creds = document.get(_CREDS)
        discord = creds.get(_DISCORD) if isinstance(creds, dict) else None
        if not isinstance(discord, dict) or _VOICE_CHANNEL_ID not in discord:
            return False
        discord.pop(_VOICE_CHANNEL_ID)
        _write_mapping(transaction, document)
        return True


def remove_matching_tmux_binary(path: Path, runtime_binary: str) -> bool:
    """Drop the retired stored binary only when runtime policy agrees."""
    with file_transaction(path) as transaction:
        document = _load_mapping(transaction.read_text())
        computer = document.get(_COMPUTER)
        if not isinstance(computer, dict) or _TMUX_BINARY not in computer:
            return False
        if computer[_TMUX_BINARY] != runtime_binary:
            return False
        computer.pop(_TMUX_BINARY)
        _write_mapping(transaction, document)
        return True


def remove_retired_api_tcp_port(path: Path) -> bool:
    """Drop the retired loopback TCP listener's stored port key."""
    with file_transaction(path) as transaction:
        document = _load_mapping(transaction.read_text())
        api = document.get(_API)
        if not isinstance(api, dict) or _TCP_PORT not in api:
            return False
        api.pop(_TCP_PORT)
        _write_mapping(transaction, document)
        return True


def move_person_invite_token(path: Path, slug: str) -> bool:
    """Move one stored invitation token before strict person validation."""
    with file_transaction(path) as person_transaction:
        document = _load_mapping(person_transaction.read_text())
        token = document.get(_INVITE_TOKEN)
        if token is None:
            return False
        if not isinstance(token, str) or not token:
            raise ValueError(_INVITE_TOKEN_ERROR.format(path=path))
        with file_transaction(INVITATIONS_PATH) as invitation_transaction:
            raw = invitation_transaction.read_text()
            invitations = json.loads(raw) if raw else {}
            if not isinstance(invitations, dict):
                raise ValueError(_INVITATIONS_MAPPING_ERROR)
            owner = invitations.get(token)
            if owner is not None and owner != slug:
                raise ValueError(_INVITATION_OWNERSHIP_ERROR.format(path=path))
            invitations[token] = slug
            invitation_transaction.replace_text(json.dumps(invitations, indent=_JSON_INDENT) + _NEWLINE)
            document.pop(_INVITE_TOKEN)
            _write_mapping(person_transaction, document)
            return True


def _load_mapping(content: str) -> dict[object, object]:
    document = _YAML.load(content) or {}
    if not isinstance(document, dict):
        raise ValueError(_DOCUMENT_MAPPING_ERROR)
    return document


def _write_mapping(transaction: FileTransaction, document: object) -> None:
    buffer = StringIO()
    _YAML.dump(document, buffer)
    transaction.replace_text(buffer.getvalue())
