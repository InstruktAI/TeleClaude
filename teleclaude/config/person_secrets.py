"""Owner-local storage for person-scoped MCP credentials."""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from teleclaude.config._environment import mutate_environment_value
from teleclaude.paths import PEOPLE_DIR, ConfigFileName
from teleclaude.slug import validate_slug

_OWNER_ONLY_MODE = 0o600


class PersonSecretStorageError(ValueError):
    """Raised when a personal secret store cannot safely supply credentials."""


class MissingPersonSecretError(ValueError):
    """Raised when one or more required personal credentials are absent."""

    def __init__(self, names: tuple[str, ...]) -> None:
        super().__init__("Personal MCP credentials are missing")
        self.names = names


@dataclass(frozen=True)
class PersonMcpSecretRequirement:
    """One registry-derived personal secret requirement."""

    name: str
    requiring_servers: tuple[str, ...]


@dataclass(frozen=True)
class PersonMcpSecretStatus:
    """Write-only status for one required personal secret."""

    name: str
    is_set: bool
    requiring_servers: tuple[str, ...]


def person_secret_store_path(person_slug: str, *, people_dir: Path = PEOPLE_DIR) -> Path:
    """Return the confined personal environment-file location for one canonical slug."""
    validate_slug(person_slug)
    root = people_dir.expanduser().resolve()
    candidate = root / person_slug / ConfigFileName.ENV
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise PersonSecretStorageError("Personal secret store is unavailable") from exc
    return candidate


def list_person_mcp_secret_statuses(
    person_slug: str,
    requirements: Mapping[str, tuple[str, ...]],
    *,
    people_dir: Path = PEOPLE_DIR,
) -> list[PersonMcpSecretStatus]:
    """Return registry-required personal-secret status without exposing values."""
    values = _read_person_secret_values(person_secret_store_path(person_slug, people_dir=people_dir))
    return [
        PersonMcpSecretStatus(name=name, is_set=bool(values.get(name)), requiring_servers=servers)
        for name, servers in sorted(requirements.items())
    ]


def resolve_person_mcp_secret_values(
    person_slug: str,
    required_names: tuple[str, ...],
    *,
    people_dir: Path = PEOPLE_DIR,
) -> dict[str, str]:
    """Return required non-empty values only to the MCP runtime boundary."""
    values = _read_person_secret_values(person_secret_store_path(person_slug, people_dir=people_dir))
    missing = tuple(name for name in required_names if not values.get(name))
    if missing:
        raise MissingPersonSecretError(missing)
    return {name: values[name] for name in required_names}


def replace_person_mcp_secret(
    person_slug: str,
    name: str,
    value: str,
    *,
    people_dir: Path = PEOPLE_DIR,
) -> None:
    """Atomically replace one personal secret without reading it back to a caller."""
    path = person_secret_store_path(person_slug, people_dir=people_dir)
    _require_safe_person_secret_store(path, allow_absent=True)
    mutate_environment_value(path, name, value, creation_mode=_OWNER_ONLY_MODE)


def secure_person_secret_store(person_slug: str, *, people_dir: Path = PEOPLE_DIR) -> bool:
    """Converge an existing personal environment file to owner-only mode.

    Returns whether the file mode changed. Non-regular and foreign-owned paths
    remain unavailable rather than being repaired across an ownership boundary.
    """
    path = person_secret_store_path(person_slug, people_dir=people_dir)
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise PersonSecretStorageError("Personal secret store is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise PersonSecretStorageError("Personal secret store is unavailable")
    if not metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        return False
    path.chmod(_OWNER_ONLY_MODE)
    return True


def clear_person_mcp_secret(person_slug: str, name: str, *, people_dir: Path = PEOPLE_DIR) -> None:
    """Atomically remove every assignment for one personal secret."""
    path = person_secret_store_path(person_slug, people_dir=people_dir)
    _require_safe_person_secret_store(path, allow_absent=True)
    if path.exists():
        mutate_environment_value(path, name, None)


def _read_person_secret_values(path: Path) -> dict[str, str]:
    if not path.exists() and not path.is_symlink():
        return {}
    _require_safe_person_secret_store(path, allow_absent=False)
    try:
        return {name: value for name, value in dotenv_values(path).items() if isinstance(value, str)}
    except OSError as exc:
        raise PersonSecretStorageError("Personal secret store is unavailable") from exc


def _require_safe_person_secret_store(path: Path, *, allow_absent: bool) -> None:
    try:
        metadata = os.lstat(path)
    except FileNotFoundError:
        if allow_absent:
            return
        raise PersonSecretStorageError("Personal secret store is unavailable") from None
    except OSError as exc:
        raise PersonSecretStorageError("Personal secret store is unavailable") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise PersonSecretStorageError("Personal secret store is unavailable")
    if metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO) or metadata.st_uid != os.getuid():
        raise PersonSecretStorageError("Personal secret store is unavailable")
    if not os.access(path, os.R_OK):
        raise PersonSecretStorageError("Personal secret store is unavailable")
