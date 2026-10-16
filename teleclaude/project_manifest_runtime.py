"""Mutation and migration-transition operations for the project registry."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import yaml

from teleclaude.config.checkout_association import RegistryCheckout, parse_registry_checkouts, render_registry_checkouts
from teleclaude.config.machine_config_mutation import stored_machine_document
from teleclaude.config.migrations._chain import Destination, in_transit
from teleclaude.config_subjects import ConfigSubjectKind, SubjectRef
from teleclaude.file_transaction import file_transaction
from teleclaude.project_manifest import (
    MANIFEST_PATH,
    ConfigKind,
    RegisteredProjectEntry,
    _manifest_path_exists,
    _normalize_manifest_path,
    load_registry_checkouts,
)
from teleclaude.project_manifest import (
    load_registered_entries as _load_manifest_entries,
)

_UTF8 = "utf-8"
_MANIFEST_READ_ERROR = "Unable to read the project registry."
_ADOPTION_LOCK_SUFFIX = ".adoption"
_TRANSIT_PATH_FIELD = "path"
_TRANSIT_NAME_FIELD = "name"
_SCHEMA_VERSION_FIELD = "schema_version"
_CURRENT_REGISTRY_SCHEMA_VERSION = 1
_ASSOCIATION_REFUSAL = "Development checkout association conflicts with the registered project registry."


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
    document = stored_machine_document()
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
            existing = list(load_registry_checkouts(manifest_path))
        else:
            existing = []
        if any(entry.project_root == normalized for entry in existing):
            return False
        existing.append(RegistryCheckout(normalized, None))
        payload = render_registry_checkouts(existing)
        transaction.replace_text(yaml.safe_dump(payload, sort_keys=False), encoding=_UTF8)
    return True


def migrate_project_registry(path: Path | None = None) -> bool:
    """Persist the current registry shape during installation, preserving legacy order."""
    manifest_path = _normalize_manifest_path(path if path is not None else MANIFEST_PATH)
    with project_adoption_lock(manifest_path):
        if not _manifest_path_exists(manifest_path):
            return False
        with file_transaction(manifest_path) as transaction:
            try:
                raw: object = yaml.safe_load(transaction.read_text(encoding=_UTF8))
                entries = parse_registry_checkouts(raw)
            except (yaml.YAMLError, OSError, UnicodeError, ValueError) as exc:
                raise RuntimeError(_MANIFEST_READ_ERROR) from exc
            if isinstance(raw, dict) and raw.get(_SCHEMA_VERSION_FIELD) == _CURRENT_REGISTRY_SCHEMA_VERSION:
                return False
            transaction.replace_text(
                yaml.safe_dump(render_registry_checkouts(entries), sort_keys=False),
                encoding=_UTF8,
            )
    return True


def write_development_association(
    *,
    path: Path | None = None,
    project_root: Path,
    development_checkout: Path,
) -> bool:
    """Add a development location to its registered primary entry atomically."""
    manifest_path = _normalize_manifest_path(path if path is not None else MANIFEST_PATH)
    primary = project_root.expanduser().resolve()
    development = development_checkout.expanduser().resolve()
    with file_transaction(manifest_path) as transaction:
        try:
            raw: object = yaml.safe_load(transaction.read_text(encoding=_UTF8))
            entries = list(parse_registry_checkouts(raw))
        except (yaml.YAMLError, OSError, UnicodeError, ValueError) as exc:
            raise RuntimeError(_MANIFEST_READ_ERROR) from exc
        matching_index = next((index for index, entry in enumerate(entries) if entry.project_root == primary), None)
        if matching_index is None:
            raise ValueError(_ASSOCIATION_REFUSAL)
        current = entries[matching_index]
        if current.development_checkout == development:
            return False
        if current.development_checkout is not None or any(
            entry.project_root == development or entry.development_checkout == development for entry in entries
        ):
            raise ValueError(_ASSOCIATION_REFUSAL)
        entries[matching_index] = RegistryCheckout(primary, development)
        transaction.replace_text(
            yaml.safe_dump(render_registry_checkouts(entries), sort_keys=False),
            encoding=_UTF8,
        )
    return True


def _project_registry_transit(document: Mapping[str, object]) -> tuple[object, ...]:
    """Read entries still moving from the machine document into the registry."""
    return in_transit(document, SubjectRef(ConfigSubjectKind.COMPUTER), Destination.PROJECT_REGISTRY)
