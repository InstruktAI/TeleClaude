"""Mutation and migration-transition operations for the project registry."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import yaml

from teleclaude.config._file_io import file_transaction
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.migrations import Destination, in_transit
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import MACHINE_CONFIG_PATH
from teleclaude.project_manifest import (
    _PROJECTS_FIELD,
    MANIFEST_PATH,
    ConfigKind,
    RegisteredProjectEntry,
    _manifest_path_exists,
    _normalize_manifest_path,
    _parse_manifest_data,
)
from teleclaude.project_manifest import (
    load_registered_entries as _load_manifest_entries,
)

_UTF8 = "utf-8"
_MANIFEST_READ_ERROR = "Unable to read the project registry."
_ADOPTION_LOCK_SUFFIX = ".adoption"
_TRANSIT_PATH_FIELD = "path"
_TRANSIT_NAME_FIELD = "name"


@contextmanager
def project_adoption_lock(path: Path | None = None) -> Iterator[None]:
    """Serialize identity checks and registration across local adoption calls."""
    manifest_path = _normalize_manifest_path(path if path is not None else MANIFEST_PATH)
    lock_path = manifest_path.with_suffix(f"{manifest_path.suffix}{_ADOPTION_LOCK_SUFFIX}")
    with file_transaction(lock_path):
        yield


def load_registered_entries(
    path: Path = MANIFEST_PATH,
    *,
    strict: bool = False,
    include_in_transit: bool = True,
) -> list[RegisteredProjectEntry]:
    """Include registry entries and, when requested, folders awaiting migration fold."""
    entries = _load_manifest_entries(path, strict=strict)
    if not include_in_transit:
        return entries
    document = _stored_machine_document()
    if document is None:
        return entries
    known_roots = {entry.path for entry in entries}
    for batch in _project_registry_transit(document):
        if not isinstance(batch, tuple):
            continue
        for row in batch:
            if not isinstance(row, Mapping):
                continue
            raw_path = row.get(_TRANSIT_PATH_FIELD)
            former_name = row.get(_TRANSIT_NAME_FIELD)
            if not isinstance(raw_path, str) or not raw_path.strip():
                continue
            root = Path(raw_path).expanduser().resolve()
            if root in known_roots or not root.is_dir():
                continue
            if not isinstance(former_name, str) or not former_name:
                continue
            entries.append(
                RegisteredProjectEntry(
                    path=root,
                    is_present=True,
                    kind=ConfigKind.PROJECT,
                    former_name=former_name,
                )
            )
            known_roots.add(root)
    return entries


def register_root(*, path: Path | None = None, project_root: Path) -> bool:
    """Append ``project_root`` when new and return whether the entry was added."""
    manifest_path = _normalize_manifest_path(path if path is not None else MANIFEST_PATH)
    normalized = project_root.expanduser().resolve()
    with file_transaction(manifest_path) as transaction:
        if _manifest_path_exists(manifest_path):
            try:
                existing_raw: object = yaml.safe_load(transaction.read_text(encoding=_UTF8))
            except (yaml.YAMLError, OSError, UnicodeError) as exc:
                raise RuntimeError(_MANIFEST_READ_ERROR) from exc
            roots = _parse_manifest_data(existing_raw)
        else:
            roots = []
        if normalized in roots:
            return False
        roots.append(normalized)
        payload = {_PROJECTS_FIELD: [str(root) for root in roots]}
        transaction.replace_text(yaml.safe_dump(payload, sort_keys=False), encoding=_UTF8)
    return True


def _stored_machine_document() -> Mapping[str, object] | None:
    """Read the stored machine document without validating or rewriting it."""
    with file_transaction(MACHINE_CONFIG_PATH) as transaction:
        content = transaction.read_text(encoding=_UTF8)
    if not content:
        return {}
    document: object = round_trip_yaml().load(content)
    return document if isinstance(document, Mapping) else None


def _project_registry_transit(document: Mapping[str, object]) -> tuple[object, ...]:
    """Read entries still moving from the machine document into the registry."""
    return in_transit(document, SubjectRef(ConfigSubjectKind.COMPUTER), Destination.PROJECT_REGISTRY)
