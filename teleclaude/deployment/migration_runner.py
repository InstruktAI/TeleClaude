"""Deployment migration discovery and execution."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import traceback
from pathlib import Path
from typing import TypedDict, cast

from teleclaude.deployment import parse_version, version_cmp, version_in_range

_REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = _REPO_ROOT / "migrations"
MIGRATION_STATE_FILE = Path.home() / ".teleclaude" / "migration_state.json"

_VERSION_DIR_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_MIGRATION_FILE_RE = re.compile(r"^(\d{3})_[a-zA-Z0-9_]+\.py$")


class MigrationState(TypedDict):
    """Serialized migration state written to disk."""

    applied: list[str]


class MigrationRunResult(TypedDict):
    """Result from ``run_migrations``."""

    migrations_run: int
    migrations_skipped: int
    error: str | None
    planned_migrations: list[str]


class MigrationModuleContract:
    """Runtime contract expected from migration scripts."""

    def check(self) -> bool:
        raise NotImplementedError

    def migrate(self) -> bool:
        raise NotImplementedError


def _normalize_version(version: str) -> str:
    stripped = version.strip()
    if stripped.startswith("v"):
        return stripped[1:]
    return stripped


def _migration_id(version: str, migration_path: Path) -> str:
    return f"{_normalize_version(version)}/{migration_path.name}"


def _load_state(state_path: Path) -> set[str]:
    if not state_path.exists():
        return set()

    with state_path.open("r", encoding="utf-8") as handle:
        raw_state = json.load(handle)

    if not isinstance(raw_state, dict):
        raise ValueError(f"Invalid migration state payload in {state_path}")

    applied = raw_state.get("applied")
    if not isinstance(applied, list) or any(not isinstance(item, str) for item in applied):
        raise ValueError(f"Invalid migration state payload in {state_path}")

    return set(applied)


def _write_state(state_path: Path, applied: set[str]) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload: MigrationState = {"applied": sorted(applied)}

    temp_name = f".{state_path.name}.{os.getpid()}.tmp"
    temp_path = state_path.with_name(temp_name)

    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")

    os.rename(temp_path, state_path)


def _load_migration_module(migration_path: Path) -> MigrationModuleContract:
    module_name = f"deployment_migration_{hash(str(migration_path.resolve()))}_{migration_path.stem}"
    spec = importlib.util.spec_from_file_location(module_name, migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load migration module spec: {migration_path}")

    module = importlib.util.module_from_spec(spec)
    loader = spec.loader
    loader.exec_module(module)

    check_func = getattr(module, "check", None)
    migrate_func = getattr(module, "migrate", None)
    if not callable(check_func) or not callable(migrate_func):
        raise RuntimeError(f"Migration missing required callables check()/migrate(): {migration_path}")

    return cast(MigrationModuleContract, module)


def _as_bool(value: object, migration_name: str, fn_name: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{migration_name}: {fn_name}() must return bool, got {type(value).__name__}")
    return value


def discover_migrations(from_ver: str, to_ver: str) -> list[tuple[str, Path]]:
    """Return ordered migration scripts where ``from_ver < version <= to_ver``."""
    if version_cmp(from_ver, to_ver) > 0:
        raise ValueError(f"Invalid version range: {from_ver!r} > {to_ver!r}")

    if not MIGRATIONS_DIR.exists():
        return []

    eligible_versions: list[tuple[tuple[int, int, int], str, Path]] = []
    for entry in MIGRATIONS_DIR.iterdir():
        if not entry.is_dir() or _VERSION_DIR_RE.match(entry.name) is None:
            continue
        if not version_in_range(entry.name, from_ver, to_ver):
            continue

        normalized = _normalize_version(entry.name)
        eligible_versions.append((parse_version(normalized), normalized, entry))

    eligible_versions.sort(key=lambda item: item[0])

    discovered: list[tuple[str, Path]] = []
    for _, version, version_dir in eligible_versions:
        files: list[tuple[int, str, Path]] = []
        for migration_file in version_dir.iterdir():
            if not migration_file.is_file():
                continue
            match = _MIGRATION_FILE_RE.match(migration_file.name)
            if match is None:
                continue
            order = int(match.group(1))
            files.append((order, migration_file.name, migration_file))

        files.sort(key=lambda item: (item[0], item[1]))
        for _, _, migration_file in files:
            discovered.append((version, migration_file))

    return discovered


def run_migrations(from_ver: str, to_ver: str, dry_run: bool = False) -> MigrationRunResult:
    """Run migration scripts in order for the target version range."""
    migrations = discover_migrations(from_ver, to_ver)
    result: MigrationRunResult = {
        "migrations_run": 0,
        "migrations_skipped": 0,
        "error": None,
        "planned_migrations": [_migration_id(version, path) for version, path in migrations],
    }

    if dry_run:
        return result

    try:
        applied = _load_state(MIGRATION_STATE_FILE)
    except Exception:  # noqa: BLE001
        result["error"] = f"Failed to load migration state: {traceback.format_exc()}"
        return result

    for version, migration_path in migrations:
        migration_name = _migration_id(version, migration_path)

        if migration_name in applied:
            result["migrations_skipped"] += 1
            continue

        try:
            module = _load_migration_module(migration_path)
            already_applied = _as_bool(module.check(), migration_name, "check")
        except Exception:  # noqa: BLE001
            result["error"] = f"Migration failed: {migration_name}\n{traceback.format_exc()}"
            return result

        if already_applied:
            result["migrations_skipped"] += 1
            continue

        try:
            migrated = _as_bool(module.migrate(), migration_name, "migrate")
            if not migrated:
                raise RuntimeError(f"Migration returned False: {migration_name}")
        except Exception:  # noqa: BLE001
            result["error"] = f"Migration failed: {migration_name}\n{traceback.format_exc()}"
            return result

        applied.add(migration_name)
        try:
            _write_state(MIGRATION_STATE_FILE, applied)
        except Exception:  # noqa: BLE001
            result["error"] = f"Failed to persist state after {migration_name}\n{traceback.format_exc()}"
            return result

        result["migrations_run"] += 1

    return result


__all__ = ["discover_migrations", "run_migrations", "MIGRATION_STATE_FILE", "MIGRATIONS_DIR"]
