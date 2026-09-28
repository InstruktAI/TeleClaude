"""Move trusted directories into the tier-declared project registry."""

from __future__ import annotations

from collections.abc import Mapping, MutableMapping
from pathlib import Path
from typing import Final, TypedDict, cast

from instrukt_ai_logging import get_logger

from teleclaude.config.legacy_discord_handoff import LegacyProjectForumBinding, append_project_forum_bindings
from teleclaude.config.migrations._chain import Destination
from teleclaude.config.schema import ConfigKind
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import ConfigFileName

VERSION: Final = 9
KINDS: Final = frozenset({ConfigSubjectKind.COMPUTER})
READ_REQUIRES_REGISTRY: Final = False
MOVES: Final = Destination.PROJECT_REGISTRY

_COMPUTER_FIELD = "computer"
_TRUSTED_DIRS_FIELD = "trusted_dirs"
_PATH_FIELD = "path"
_NAME_FIELD = "name"
_DESCRIPTION_FIELD = "description"
_LEGACY_DESCRIPTION_FIELD = "desc"
_PROJECT_FORUM_KEY_PREFIX = "project_forum:"
_HOME_REFERENCE = "${HOME}"
_USER_HOME = str(Path.home())
_MISSING_DIRECTORY_EVENT = "trusted_directory_missing_during_registry_fold"
_INVALID_TRUSTED_DIRECTORY = "Trusted-directory migration entry has an invalid path, name, or description."
_INVALID_PENDING_VALUE = "Trusted-directory migration pending value must be an entry tuple."

logger = get_logger(__name__)


class PendingTrustedDirectory(TypedDict):
    """One expanded trusted-directory row carried between migration steps."""

    path: str
    name: str
    description: str


class RegistryConflict(ValueError):
    """A project identity or forum binding conflicts with an existing registry entry."""


def _expanded_path(value: str) -> Path:
    """Expand the home markers accepted by the machine trusted-directory list."""
    expanded = value.replace(_HOME_REFERENCE, _USER_HOME)
    return Path(expanded).expanduser()


def _pending_entries(document: Mapping[str, object]) -> tuple[PendingTrustedDirectory, ...] | None:
    """Project valid trusted-directory entries into the move destination shape."""
    computer = document.get(_COMPUTER_FIELD)
    if not isinstance(computer, Mapping) or _TRUSTED_DIRS_FIELD not in computer:
        return None
    raw_entries = computer[_TRUSTED_DIRS_FIELD]
    if not isinstance(raw_entries, list):
        raise ValueError(_INVALID_TRUSTED_DIRECTORY)
    entries: list[PendingTrustedDirectory] = []
    for row in raw_entries:
        if not isinstance(row, Mapping):
            raise ValueError(_INVALID_TRUSTED_DIRECTORY)
        raw_path = row.get(_PATH_FIELD)
        name = row.get(_NAME_FIELD)
        description = row.get(_LEGACY_DESCRIPTION_FIELD)
        if (
            not isinstance(raw_path, str)
            or not raw_path.strip()
            or not isinstance(name, str)
            or not isinstance(description, str)
        ):
            raise ValueError(_INVALID_TRUSTED_DIRECTORY)
        path = _expanded_path(raw_path)
        if not path.is_absolute():
            raise ValueError(_INVALID_TRUSTED_DIRECTORY)
        entries.append(
            PendingTrustedDirectory(
                path=str(path),
                name=name,
                description=description,
            ),
        )
    return tuple(entries) or None


def up(document: MutableMapping[str, object], _subject: SubjectRef) -> None:
    """Remove the retired field from the current in-memory machine shape."""
    computer = document.get(_COMPUTER_FIELD)
    if isinstance(computer, MutableMapping):
        raw_entries = computer.get(_TRUSTED_DIRS_FIELD)
        if _TRUSTED_DIRS_FIELD in computer and not isinstance(raw_entries, list):
            raise ValueError(_INVALID_TRUSTED_DIRECTORY)
        computer.pop(_TRUSTED_DIRS_FIELD, None)


def pending(document: Mapping[str, object], _subject: SubjectRef) -> tuple[PendingTrustedDirectory, ...] | None:
    """Return expanded trusted-directory entries while they remain in the document."""
    return _pending_entries(document)


def deliver(value: object, _subject: SubjectRef) -> None:
    """Adopt each present folder, preserve tier metadata, and hand off its forum key."""
    if not isinstance(value, tuple) or any(not isinstance(row, Mapping) for row in value):
        raise TypeError(_INVALID_PENDING_VALUE)

    # These runtime dependencies would cycle through the statically imported migration list.
    from teleclaude.config.loader import (  # noqa: PLC0415 - import after migration-step registration.
        carry_adopted_metadata as _carry_adopted_metadata,
    )
    from teleclaude.project_root import (  # noqa: PLC0415 - import after migration-step registration.
        resolve_project_root as _resolve_project_root,
    )
    from teleclaude.project_setup.init_flow import (  # noqa: PLC0415 - import after migration-step registration.
        ProjectIdentityConflict,
        ProjectInitializationTrigger,
    )
    from teleclaude.project_setup.init_flow import (  # noqa: PLC0415 - avoids the migration-step import cycle.
        init_project as _init_project,
    )

    pending_rows = cast(tuple[Mapping[str, object], ...], value)
    legacy_forum_candidates: list[tuple[str, str]] = []
    for row in pending_rows:
        raw_path = row.get(_PATH_FIELD)
        name = row.get(_NAME_FIELD)
        if not isinstance(raw_path, str) or not isinstance(name, str) or not name:
            continue
        folder = Path(raw_path).expanduser().resolve()
        if folder.is_dir():
            legacy_forum_candidates.append((str(folder), name))
    legacy_forum_candidates.sort(key=lambda candidate: len(candidate[0]), reverse=True)
    legacy_forum_owner_by_key: dict[str, str] = {}
    for legacy_folder, name in legacy_forum_candidates:
        legacy_forum_owner_by_key[name] = legacy_folder

    project_forum_bindings: dict[str, LegacyProjectForumBinding] = {}
    for row in pending_rows:
        raw_path = row.get(_PATH_FIELD)
        name = row.get(_NAME_FIELD)
        description = row.get(_DESCRIPTION_FIELD)
        if not isinstance(raw_path, str) or not isinstance(name, str) or not isinstance(description, str):
            raise ValueError(_INVALID_TRUSTED_DIRECTORY)
        folder = Path(raw_path).expanduser().resolve()
        if not folder.is_dir():
            logger.warning(_MISSING_DIRECTORY_EVENT, trusted_directory_name=name)
            continue
        try:
            result = _init_project(folder, trigger=ProjectInitializationTrigger.FOLD)
        except ProjectIdentityConflict as error:
            raise RegistryConflict(str(error)) from error

        registered_root = _resolve_project_root(folder) if result.kind is ConfigKind.PROJECT else folder
        _carry_adopted_metadata(
            registered_root / ConfigFileName.OVERLAY,
            result.kind,
            name=name,
            description=description,
        )
        forum_owner = legacy_forum_owner_by_key.get(name)
        if name and forum_owner == str(folder):
            logical_key = f"{_PROJECT_FORUM_KEY_PREFIX}{name}"
            project_forum_bindings[logical_key] = LegacyProjectForumBinding(
                logical_key=logical_key,
                folder=registered_root,
            )

    if project_forum_bindings:
        append_project_forum_bindings(tuple(project_forum_bindings.values()), conflict_type=RegistryConflict)
