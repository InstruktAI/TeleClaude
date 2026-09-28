"""Root-only project registry persisted at ``~/.teleclaude/projects.yaml``.

The manifest stores just the list of absolute project root paths. All metadata
(project name, description, jobs, docs index path) lives in each project's own
``teleclaude.yml`` and is loaded through the project catalog service.
"""

from __future__ import annotations

import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

import yaml

from teleclaude.config._file_io import file_transaction
from teleclaude.config._yaml import round_trip_yaml
from teleclaude.config.schema import ConfigKind
from teleclaude.config.subjects import ConfigSubjectKind, SubjectRef
from teleclaude.paths import MACHINE_CONFIG_PATH, PROJECTS_MANIFEST_PATH, ConfigFileName

MANIFEST_PATH = PROJECTS_MANIFEST_PATH
_UTF8 = "utf-8"
_MANIFEST_READ_ERROR = "Unable to read the project registry."
_MANIFEST_SHAPE_ERROR = "Project registry must contain a projects list or a legacy root list."
_MANIFEST_ENTRY_ERROR = "Project registry contains an invalid root entry."
_DECLARATION_READ_ERROR = "Unable to read a registered folder's tier declaration: {path}"
_DECLARATION_SHAPE_ERROR = "Registered folder's tier declaration must be a YAML mapping: {path}"
_DECLARATION_KIND_ERROR = "Registered folder's tier declaration has an invalid kind: {path}"
_PROJECTS_FIELD = "projects"
_ADOPTION_LOCK_SUFFIX = ".adoption"
_KIND_FIELD = "kind"
_TRANSIT_PATH_FIELD = "path"
_TRANSIT_NAME_FIELD = "name"


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


@contextmanager
def project_adoption_lock(path: Path | None = None) -> Iterator[None]:
    """Serialize identity checks and registration across local adoption calls."""
    manifest_path = _normalize_manifest_path(path if path is not None else MANIFEST_PATH)
    lock_path = manifest_path.with_suffix(f"{manifest_path.suffix}{_ADOPTION_LOCK_SUFFIX}")
    with file_transaction(lock_path):
        yield


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
        for entry in load_registered_entries(path, strict=strict, include_in_transit=False)
        if entry.kind is ConfigKind.PROJECT
    ]


def load_registered_entries(
    path: Path = MANIFEST_PATH,
    *,
    strict: bool = False,
    include_in_transit: bool = True,
) -> list[RegisteredProjectEntry]:
    """Load every registered folder in order, retaining availability and tier."""
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
    known_roots: set[Path] = set()
    for root in roots:
        is_present = root.is_dir()
        kind = _declared_kind(root) if is_present else ConfigKind.PROJECT
        entries.append(RegisteredProjectEntry(path=root, is_present=is_present, kind=kind))
        known_roots.add(root)

    if include_in_transit:
        document = _stored_machine_document()
        if document is not None:
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
                        ),
                    )
                    known_roots.add(root)
    return entries


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
    from teleclaude.config.migrations import (  # noqa: PLC0415 - avoids the migration-step import cycle.
        Destination,
        in_transit,
    )

    return in_transit(document, SubjectRef(ConfigSubjectKind.COMPUTER), Destination.PROJECT_REGISTRY)


def register_root(*, path: Path | None = None, project_root: Path) -> bool:
    """Append ``project_root`` when new and return whether the entry was added.

    ``path`` defaults to the module-level ``MANIFEST_PATH`` when omitted. We
    resolve the default at call time (not at function-definition time) so
    tests that monkeypatch ``project_manifest.MANIFEST_PATH`` observe the
    override without needing to reload the module.
    """
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
