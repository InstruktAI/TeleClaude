"""Deployment migration discovery and execution."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import tomllib
import traceback
from operator import itemgetter
from pathlib import Path
from typing import TypedDict, cast

from instrukt_ai_logging import get_logger

from teleclaude.core.migration_signal import MigrationStore, signal_migration_started
from teleclaude.deployment import parse_version, version_cmp, version_in_range
from teleclaude.git import GitCommandError, Repo
from teleclaude.logging_config import setup_logging
from teleclaude.paths import MIGRATION_STATE_PATH

_REPO_ROOT = Path(__file__).resolve().parents[2]
MIGRATIONS_DIR = _REPO_ROOT / "migrations"
MIGRATION_STATE_FILE = MIGRATION_STATE_PATH

_VERSION_DIR_RE = re.compile(r"^v\d+\.\d+\.\d+$")
_MIGRATION_FILE_RE = re.compile(r"^(\d{3})_[a-zA-Z0-9_]+\.py$")
_PROJECT_TABLE = "project"
_VERSION_KEY = "version"
_PYPROJECT_FILENAME = "pyproject.toml"
_COMMITTED_FILE_TEMPLATE = "{commit}:{path}"
_VERSION_ERROR = "{path} declares no project version"
_VERSION_UNREADABLE_ERROR = "the committed version at {commit} is unreadable: {error}"
_MIGRATION_ERROR = "migrations failed: {error}"
_BEFORE_SHA_FLAG = "--before-sha"
_AFTER_SHA_FLAG = "--after-sha"
_NO_MIGRATIONS_EVENT = "deployment_migrations_not_required"
_NO_BEFORE_REVISION = "activation has no before revision"
_MIGRATIONS_COMPLETED_EVENT = "deployment_migrations_completed"
_FAILED_EXIT_CODE = 1
logger = get_logger(__name__)


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
        """Return True if migration is needed."""
        raise NotImplementedError

    def migrate(self) -> bool:
        """Execute the migration and return True on success."""
        raise NotImplementedError


class DeploymentMigrationError(ValueError):
    """A committed project version could not be read for deployment migration."""


def committed_version(repository: Repo, commit: str) -> str:
    """Read the project version declared by one commit's pyproject, independent of working-tree state."""
    try:
        text = str(repository.git.show(_COMMITTED_FILE_TEMPLATE.format(commit=commit, path=_PYPROJECT_FILENAME)))
        project = tomllib.loads(text).get(_PROJECT_TABLE)
        version = project.get(_VERSION_KEY) if isinstance(project, dict) else None
        if not isinstance(version, str) or not version:
            path = _COMMITTED_FILE_TEMPLATE.format(commit=commit, path=_PYPROJECT_FILENAME)
            raise DeploymentMigrationError(_VERSION_ERROR.format(path=path))
        return version
    except (GitCommandError, tomllib.TOMLDecodeError) as error:
        raise DeploymentMigrationError(_VERSION_UNREADABLE_ERROR.format(commit=commit, error=error)) from error


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
        raw_state_obj: object = json.load(handle)

    if not isinstance(raw_state_obj, dict):
        raise ValueError(f"Invalid migration state payload in {state_path}")

    raw_state = cast(dict[str, object], raw_state_obj)  # guard: loose-dict - YAML state file — dynamic shape
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

    eligible_versions.sort(key=itemgetter(0))

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

        files.sort(key=itemgetter(0, 1))
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
    except Exception:
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
        except Exception:
            result["error"] = f"Migration failed: {migration_name}\n{traceback.format_exc()}"
            return result

        if already_applied:
            result["migrations_skipped"] += 1
            continue

        try:
            signal_migration_started(MigrationStore.INSTALLATION)
            migrated = _as_bool(module.migrate(), migration_name, "migrate")
            if not migrated:
                raise RuntimeError(f"Migration returned False: {migration_name}")
        except Exception:
            result["error"] = f"Migration failed: {migration_name}\n{traceback.format_exc()}"
            return result

        applied.add(migration_name)
        try:
            _write_state(MIGRATION_STATE_FILE, applied)
        except Exception:
            result["error"] = f"Failed to persist state after {migration_name}\n{traceback.format_exc()}"
            return result

        result["migrations_run"] += 1

    return result


def migrate_committed_range(root: Path, before_sha: str | None, after_sha: str) -> int:
    """Run the installation migrations a committed range owes; zero on success, non-zero with the reason printed."""
    if before_sha is None:
        logger.info(_NO_MIGRATIONS_EVENT, reason=_NO_BEFORE_REVISION)
        return 0

    try:
        repository = Repo(str(root))
        from_version = committed_version(repository, before_sha)
        to_version = committed_version(repository, after_sha)
        if version_cmp(from_version, to_version) >= 0:
            logger.info(
                _NO_MIGRATIONS_EVENT,
                before_version=from_version,
                after_version=to_version,
            )
            return 0
        result = run_migrations(from_version, to_version)
    except (DeploymentMigrationError, GitCommandError, OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return _FAILED_EXIT_CODE

    if result["error"] is not None:
        print(_MIGRATION_ERROR.format(error=result["error"]), file=sys.stderr)
        return _FAILED_EXIT_CODE
    logger.info(
        _MIGRATIONS_COMPLETED_EVENT,
        from_version=from_version,
        to_version=to_version,
        migrations_run=result["migrations_run"],
        migrations_skipped=result["migrations_skipped"],
    )
    return 0


def main(arguments: list[str] | None = None) -> int:
    """Run installation migrations when a committed activation advances the declared project version."""
    setup_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(_BEFORE_SHA_FLAG)
    parser.add_argument(_AFTER_SHA_FLAG, required=True)
    args = parser.parse_args(arguments)
    return migrate_committed_range(Path.cwd(), args.before_sha, args.after_sha)


__all__ = [
    "MIGRATIONS_DIR",
    "MIGRATION_STATE_FILE",
    "DeploymentMigrationError",
    "committed_version",
    "discover_migrations",
    "main",
    "migrate_committed_range",
    "run_migrations",
]


if __name__ == "__main__":
    raise SystemExit(main())
