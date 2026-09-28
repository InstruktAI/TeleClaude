"""Root-only project registry persisted at ``~/.teleclaude/projects.yaml``.

The manifest stores just the list of absolute project root paths. All metadata
(project name, description, jobs, docs index path) lives in each project's own
``teleclaude.yml`` and is loaded through the project catalog service.
"""

from __future__ import annotations

import stat
from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

import yaml

from teleclaude.paths import PROJECTS_MANIFEST_PATH, ConfigFileName

MANIFEST_PATH = PROJECTS_MANIFEST_PATH
_UTF8 = "utf-8"
_MANIFEST_READ_ERROR = "Unable to read the project registry."
_MANIFEST_SHAPE_ERROR = "Project registry must contain a projects list or a legacy root list."
_MANIFEST_ENTRY_ERROR = "Project registry contains an invalid root entry."
_DECLARATION_READ_ERROR = "Unable to read a registered folder's tier declaration: {path}"
_DECLARATION_SHAPE_ERROR = "Registered folder's tier declaration must be a YAML mapping: {path}"
_DECLARATION_KIND_ERROR = "Registered folder's tier declaration has an invalid kind: {path}"
_PROJECTS_FIELD = "projects"
_KIND_FIELD = "kind"


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


def _coerce_root(raw: object) -> Path | None:
    """Accept either a string path or a legacy ``{project_root: ...}`` dict."""
    if isinstance(raw, str):
        text = raw.strip()
        return Path(text).expanduser().resolve() if text else None
    if isinstance(raw, dict):
        candidate = raw.get("project_root")
        if isinstance(candidate, str) and candidate.strip():
            return Path(candidate).expanduser().resolve()
    return None


def _parse_manifest_data(raw_data: object) -> list[Path]:
    if isinstance(raw_data, dict):
        raw_entries = raw_data.get(_PROJECTS_FIELD)
    elif isinstance(raw_data, list):
        raw_entries = raw_data
    else:
        raise ValueError(_MANIFEST_SHAPE_ERROR)
    if not isinstance(raw_entries, list):
        raise ValueError(_MANIFEST_SHAPE_ERROR)

    roots: list[Path] = []
    seen: set[Path] = set()
    for entry in raw_entries:
        root = _coerce_root(entry)
        if root is None:
            raise ValueError(_MANIFEST_ENTRY_ERROR)
        if root in seen:
            continue
        seen.add(root)
        roots.append(root)
    return roots


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
    """Load registered project roots whose directories still exist on disk."""
    return [entry.path for entry in load_registered_roots(path) if entry.is_present]


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
    roots: list[Path] = []
    if _manifest_path_exists(manifest_path):
        try:
            raw_data: object = yaml.safe_load(manifest_path.read_text(encoding=_UTF8))
        except (yaml.YAMLError, OSError, UnicodeError) as exc:
            if strict:
                raise RuntimeError(_MANIFEST_READ_ERROR) from exc
            raise
        try:
            roots = _parse_manifest_data(raw_data)
        except ValueError as exc:
            if strict:
                raise RuntimeError(_MANIFEST_READ_ERROR) from exc
            raise
    entries: list[RegisteredProjectEntry] = []
    for root in roots:
        is_present = root.is_dir()
        kind = _declared_kind(root) if is_present else ConfigKind.PROJECT
        entries.append(RegisteredProjectEntry(path=root, is_present=is_present, kind=kind))
    return entries
