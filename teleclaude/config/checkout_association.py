"""Dependency-light reads for the registered installed/development checkout pair."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import TypedDict

import yaml

_PROJECTS_FIELD = "projects"
_SCHEMA_VERSION_FIELD = "schema_version"
_PROJECT_ROOT_FIELD = "project_root"
_DEVELOPMENT_CHECKOUT_FIELD = "development_checkout"
_CURRENT_SCHEMA_VERSION = 1
_REGISTRY_SHAPE_ERROR = "Project registry has an unsupported or invalid shape"


class CheckoutPurpose(StrEnum):
    """The role of one checkout in its logical project's registered pair."""

    INSTALLED = "installed"
    DEVELOPMENT = "development"


@dataclass(frozen=True)
class RegistryCheckout:
    """One logical project's primary root and optional development location."""

    project_root: Path
    development_checkout: Path | None


class RegistryEntryDocument(TypedDict):
    """One serialized registry location pair."""

    project_root: str
    development_checkout: str | None


class RegistryDocument(TypedDict):
    """Versioned project registry document written to disk."""

    schema_version: int
    projects: list[RegistryEntryDocument]


@dataclass(frozen=True)
class CheckoutAssociation:
    """The logical project and purpose matched by a path inside an associated checkout."""

    project_root: Path
    development_checkout: Path
    purpose: CheckoutPurpose


def read_registry_checkouts(registry_path: Path) -> tuple[RegistryCheckout, ...]:
    """Read current or legacy registry data without importing runtime configuration."""
    resolved_path = registry_path.expanduser().resolve()
    try:
        metadata = resolved_path.stat()
    except FileNotFoundError:
        return ()
    signature = (metadata.st_dev, metadata.st_ino, metadata.st_mtime_ns, metadata.st_size)
    return _read_registry_checkouts_cached(resolved_path, signature)


@lru_cache(maxsize=64)
def _read_registry_checkouts_cached(
    registry_path: Path,
    signature: tuple[int, int, int, int],
) -> tuple[RegistryCheckout, ...]:
    del signature
    try:
        document: object = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(_REGISTRY_SHAPE_ERROR) from exc

    return parse_registry_checkouts(document)


def parse_registry_checkouts(document: object) -> tuple[RegistryCheckout, ...]:
    """Normalize legacy registry shapes to the current checkout model."""

    is_current = False
    if isinstance(document, list):
        raw_entries = document
    elif isinstance(document, dict):
        version = document.get(_SCHEMA_VERSION_FIELD)
        if _SCHEMA_VERSION_FIELD in document and (type(version) is not int or version != _CURRENT_SCHEMA_VERSION):
            raise ValueError(_REGISTRY_SHAPE_ERROR)
        is_current = _SCHEMA_VERSION_FIELD in document
        raw_entries = document.get(_PROJECTS_FIELD)
    else:
        raise ValueError(_REGISTRY_SHAPE_ERROR)
    if not isinstance(raw_entries, list):
        raise ValueError(_REGISTRY_SHAPE_ERROR)

    entries: list[RegistryCheckout] = []
    seen: set[Path] = set()
    for raw_entry in raw_entries:
        if isinstance(raw_entry, str):
            raw_root = raw_entry
            raw_development = None
        elif isinstance(raw_entry, dict):
            if is_current and _DEVELOPMENT_CHECKOUT_FIELD not in raw_entry:
                raise ValueError(_REGISTRY_SHAPE_ERROR)
            raw_root = raw_entry.get(_PROJECT_ROOT_FIELD)
            raw_development = raw_entry.get(_DEVELOPMENT_CHECKOUT_FIELD)
        else:
            raise ValueError(_REGISTRY_SHAPE_ERROR)
        if not isinstance(raw_root, str) or not raw_root.strip():
            raise ValueError(_REGISTRY_SHAPE_ERROR)
        project_root = Path(raw_root).expanduser().resolve()
        if project_root in seen:
            continue
        development_checkout: Path | None = None
        if raw_development is not None:
            if not isinstance(raw_development, str) or not raw_development.strip():
                raise ValueError(_REGISTRY_SHAPE_ERROR)
            development_checkout = Path(raw_development).expanduser().resolve()
            if development_checkout == project_root:
                raise ValueError(_REGISTRY_SHAPE_ERROR)
        entries.append(RegistryCheckout(project_root, development_checkout))
        seen.add(project_root)
    return tuple(entries)


def render_registry_checkouts(entries: tuple[RegistryCheckout, ...] | list[RegistryCheckout]) -> RegistryDocument:
    """Render the versioned registry document while retaining entry order."""
    rendered_entries: list[RegistryEntryDocument] = [
        RegistryEntryDocument(
            project_root=str(entry.project_root),
            development_checkout=(str(entry.development_checkout) if entry.development_checkout is not None else None),
        )
        for entry in entries
    ]
    return RegistryDocument(schema_version=_CURRENT_SCHEMA_VERSION, projects=rendered_entries)


def checkout_association_for(path: Path, registry_path: Path) -> CheckoutAssociation | None:
    """Resolve a path within an associated checkout using the supplied registry path."""
    resolved = path.expanduser().resolve()
    for entry in read_registry_checkouts(registry_path):
        development = entry.development_checkout
        if development is None:
            continue
        if resolved == entry.project_root or entry.project_root in resolved.parents:
            return CheckoutAssociation(entry.project_root, development, CheckoutPurpose.INSTALLED)
        if resolved == development or development in resolved.parents:
            return CheckoutAssociation(entry.project_root, development, CheckoutPurpose.DEVELOPMENT)
    return None
