"""Backfill registered person workspace claims."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import yaml

from teleclaude.config.declaration import write_declared_config
from teleclaude.config.loader import load_global_config
from teleclaude.config.schema import ConfigKind
from teleclaude.paths import PEOPLE_DIR, ConfigFileName

_PEOPLE_DIR = PEOPLE_DIR
_PERSON_SLUG_FIELD = "slug"


def check() -> bool:
    """Return whether every established registered workspace carries its claim."""
    for path, _ in _registered_person_config_paths():
        document = _load_document(path)
        if document is None:
            return False
        if _PERSON_SLUG_FIELD not in document:
            return False
    return True


def migrate() -> bool:
    """Write missing claims for established registry-designated person workspaces."""
    for path, slug in _registered_person_config_paths():
        document = _load_document(path)
        if document is None:
            return False
        if _PERSON_SLUG_FIELD in document:
            continue
        updated_document = {**document, _PERSON_SLUG_FIELD: slug}
        write_declared_config(path, ConfigKind.PERSON, updated_document, schema_root=path.parent.parent.parent)
    return True


def _registered_person_config_paths() -> list[tuple[Path, str]]:
    """Return existing person overlays at registry-designated workspace paths."""
    paths: list[tuple[Path, str]] = []
    for person in load_global_config().people:
        if person.slug is None:
            continue
        path = _PEOPLE_DIR / person.slug / ConfigFileName.OVERLAY
        if path.is_file():
            paths.append((path, person.slug))
    return paths


def _load_document(path: Path) -> Mapping[str, object] | None:
    """Load a person overlay mapping without treating malformed data as migratable."""
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    return document if isinstance(document, dict) else None
