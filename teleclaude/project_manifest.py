"""Versioned project registry persisted at ``~/.teleclaude/projects.yaml``."""

from __future__ import annotations

import stat
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

import yaml

from teleclaude.config.checkout_association import RegistryCheckout, read_registry_checkouts
from teleclaude.paths import PROJECTS_MANIFEST_PATH, ConfigFileName

MANIFEST_PATH = PROJECTS_MANIFEST_PATH
_UTF8 = "utf-8"
_MANIFEST_READ_ERROR = "Unable to read the project registry."
_DECLARATION_READ_ERROR = "Unable to read a registered folder's tier declaration: {path}"
_DECLARATION_SHAPE_ERROR = "Registered folder's tier declaration must be a YAML mapping: {path}"
_DECLARATION_KIND_ERROR = "Registered folder's tier declaration has an invalid kind: {path}"
_KIND_FIELD = "kind"
_REGISTRY_SCOPE = "project_registry_read_scope"


class ConfigKind(StrEnum):
    """Tier identity declared by a registered configuration folder."""

    GLOBAL = "global"
    PROJECT = "project"
    PERSON = "person"
    COMPANY = "company"


class RegisteredProjectRoot(NamedTuple):
    """One manifest entry and whether its registered directory is available."""

    path: Path
    is_present: bool


class RegisteredProjectEntry(NamedTuple):
    """One registered folder, its availability, and its declared tier."""

    path: Path
    is_present: bool
    kind: ConfigKind
    former_name: str | None = None
    development_checkout: Path | None = None


_PROJECT_ROOTS: ContextVar[dict[Path, tuple[Path, ...]] | None] = ContextVar(_REGISTRY_SCOPE, default=None)


@contextmanager
def project_registry_resolution() -> Iterator[None]:
    """Reuse successful project-root inventories within one synchronous operation."""
    if _PROJECT_ROOTS.get() is not None:
        yield
        return
    token = _PROJECT_ROOTS.set({})
    try:
        yield
    finally:
        _PROJECT_ROOTS.reset(token)


def _normalize_manifest_path(path: Path) -> Path:
    return path.expanduser().resolve()


def _manifest_path_exists(path: Path) -> bool:
    """Distinguish a missing registry from filesystem errors while inspecting it."""
    try:
        path.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise RuntimeError(_MANIFEST_READ_ERROR) from exc
    return True


def load_registry_checkouts(path: Path = MANIFEST_PATH) -> tuple[RegistryCheckout, ...]:
    """Load the parsed registry model through its cached leaf reader."""
    return read_registry_checkouts(_normalize_manifest_path(path))


def _declared_kind(root: Path) -> ConfigKind:
    """Read a registered folder's declared tier, rejecting malformed declarations."""
    declaration_path = root / ConfigFileName.OVERLAY
    try:
        link_stat = declaration_path.lstat()
    except FileNotFoundError:
        return ConfigKind.PROJECT
    except OSError as exc:
        raise ValueError(_DECLARATION_READ_ERROR.format(path=declaration_path)) from exc
    if not (stat.S_ISREG(link_stat.st_mode) or stat.S_ISLNK(link_stat.st_mode)):
        raise ValueError(_DECLARATION_SHAPE_ERROR.format(path=declaration_path))
    try:
        target_stat = declaration_path.stat()
    except (OSError, UnicodeError) as exc:
        raise ValueError(_DECLARATION_READ_ERROR.format(path=declaration_path)) from exc
    if not stat.S_ISREG(target_stat.st_mode):
        raise ValueError(_DECLARATION_SHAPE_ERROR.format(path=declaration_path))
    try:
        document: object = yaml.safe_load(declaration_path.read_text(encoding=_UTF8))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ValueError(_DECLARATION_READ_ERROR.format(path=declaration_path)) from exc
    if not isinstance(document, dict):
        raise ValueError(_DECLARATION_SHAPE_ERROR.format(path=declaration_path))
    if _KIND_FIELD not in document:
        return ConfigKind.PROJECT
    raw_kind = document.get(_KIND_FIELD)
    try:
        return ConfigKind(raw_kind)
    except (TypeError, ValueError) as exc:
        raise ValueError(_DECLARATION_KIND_ERROR.format(path=declaration_path)) from exc


def load_roots(path: Path = MANIFEST_PATH) -> list[Path]:
    """Load available project roots, reusing the active operation's inventory."""
    inventories = _PROJECT_ROOTS.get()
    manifest_path = _normalize_manifest_path(path) if inventories is not None else path
    if inventories is not None and manifest_path in inventories:
        return list(inventories[manifest_path])
    manifest_exists = inventories is not None and _manifest_path_exists(manifest_path)
    roots = [entry.path for entry in load_registered_roots(manifest_path) if entry.is_present]
    if inventories is not None and manifest_exists:
        inventories[manifest_path] = tuple(roots)
    return roots


def load_registered_roots(path: Path = MANIFEST_PATH, *, strict: bool = False) -> list[RegisteredProjectRoot]:
    """Load registered project roots only, retaining unavailable entries."""
    return [
        RegisteredProjectRoot(path=entry.path, is_present=entry.is_present)
        for entry in load_registered_entries(path, strict=strict)
        if entry.kind is ConfigKind.PROJECT
    ]


def load_registered_entries(
    path: Path = MANIFEST_PATH,
    *,
    strict: bool = False,
) -> list[RegisteredProjectEntry]:
    """Load manifest entries in adoption order, retaining availability and tier."""
    manifest_path = _normalize_manifest_path(path)
    entries: list[RegisteredProjectEntry] = []
    try:
        roots = load_registry_checkouts(manifest_path)
    except (OSError, ValueError) as exc:
        if strict:
            raise RuntimeError(_MANIFEST_READ_ERROR) from exc
        raise
    for registry_entry in roots:
        root = registry_entry.project_root
        is_present = root.is_dir()
        kind = _declared_kind(root) if is_present else ConfigKind.PROJECT
        entries.append(
            RegisteredProjectEntry(
                path=root,
                is_present=is_present,
                kind=kind,
                development_checkout=registry_entry.development_checkout,
            )
        )
    return entries
