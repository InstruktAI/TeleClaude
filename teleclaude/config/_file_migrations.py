"""Lossless normalization of recognized stored configuration fields."""

from __future__ import annotations

import json
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
_COMPUTER: Final = "computer"
_TMUX_BINARY: Final = "tmux_binary"
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
                    PersonEntry.model_validate(candidate, extra="forbid")
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
