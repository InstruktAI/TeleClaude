"""Prepare and reuse the locked dependency-only environment the acceptance harness runs against."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import pwd
import re
import shutil
import sys
import time
import uuid
from enum import StrEnum
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from instrukt_ai_logging import get_logger

from tools.ci.bounded_process import ProcessExecution, run_bounded_process

LOG_APP_NAME = "teleclaude_runtime_acceptance"
_EMPTY = ""
_UTF8 = "utf-8"
_UNKNOWN_REVISION = "unknown"
_JSON_SEPARATORS = (",", ":")
_STORE_DIRECTORY = "teleclaude-runtime-acceptance"
_ENVIRONMENT_LOCK_SUFFIX = ".lock"
_ENVIRONMENT_MANIFESTS = ("pyproject.toml", "uv.lock", ".python-version")
_ENVIRONMENT_REQUIRED_MANIFESTS = ("pyproject.toml", "uv.lock")
_ENVIRONMENT_GROUPS = "runtime-only"
_ENVIRONMENT_MANIFEST_FILENAME = "environment.json"
_MANIFEST_KEY_FIELD = "key"
_MANIFEST_GROUPS_FIELD = "groups"
_VENV_CONFIG_FILENAME = "pyvenv.cfg"
_PYTHON_EXECUTABLE = "python"
_UV_EXECUTABLE = "uv"
_UV_SYNC_COMMAND = "sync"
_UV_PROJECT_OPTION = "--project"
_UV_LOCKED_OPTION = "--locked"
_UV_NO_INSTALL_PROJECT_OPTION = "--no-install-project"
_UV_NO_DEFAULT_GROUPS_OPTION = "--no-default-groups"
_UV_SYNC_ARGUMENTS = (
    _UV_EXECUTABLE,
    _UV_SYNC_COMMAND,
    _UV_PROJECT_OPTION,
)
_UV_CACHE_VARIABLE = "UV_CACHE_DIR"
_UV_SYNC_TIMEOUT_SECONDS = 900
_PATH_VARIABLE = "PATH"
_HOME_VARIABLE = "HOME"
_LOCALE_VARIABLE = "LANG"
_TMP_VARIABLE = "TMPDIR"
_DEFAULT_LANGUAGE = "C.UTF-8"
_SYNTHETIC_HOME_DIRECTORY = "home"
_SYNTHETIC_CACHE_DIRECTORY = "cache"
_SYNTHETIC_TEMP_DIRECTORY = "tmp"
_RETIRED_MARKER = ".retired-"
_CACHE_LOCK_FILENAME = "cache.lock"
_GENERATION_NAME = re.compile(r"[0-9a-f]{64}")
_RETIRED_NAME = re.compile(
    rf"(?:[0-9a-f]{{64}}|{_SYNTHETIC_CACHE_DIRECTORY}){re.escape(_RETIRED_MARKER)}[0-9a-f]{{32}}"
)
_SECONDS_PER_DAY = 24 * 60 * 60
_GENERATION_RETENTION_SECONDS = 14 * _SECONDS_PER_DAY
_DOWNLOAD_CACHE_CEILING_BYTES = 2 * 1024**3
_ENVIRONMENT_INVALID = "The dependency-only environment generation is incomplete: {path}"
_ENVIRONMENT_SYNC_FAILED = "Could not prepare the locked dependency-only environment: {detail}"
_ENVIRONMENT_INPUT_MISSING = "The dependency environment input is missing: {path}"
_SYNC_EVIDENCE_TAIL_LIMIT = 3072
_STORE_REFUSED = "The dependency environment store is a link, is not a directory, or belongs to another user."
_CACHE_VARIABLE = "XDG_CACHE_HOME"
_STORE_MODE = 0o700
_PROCESS_FAILURE_DETAIL = "The command failed with exit status {exit_status}."
DEPENDENCY_ENVIRONMENT_PLACEHOLDER = "<dependency-environment>"
SOURCE_TREE_PLACEHOLDER = "<source-tree>"
PROJECT_ENVIRONMENT_VARIABLE = "UV_PROJECT_ENVIRONMENT"
PYTHON_ENVIRONMENT_EXECUTABLE = Path("bin") / _PYTHON_EXECUTABLE


logger = get_logger(f"{LOG_APP_NAME}.dependency_environment")


def _environment_cache_key(source_root: Path) -> str:
    """Hash dependency inputs and interpreter identity for an immutable environment."""
    digest = hashlib.sha256()
    for relative_path in _ENVIRONMENT_MANIFESTS:
        manifest_path = source_root / relative_path
        digest.update(relative_path.encode(_UTF8))
        if manifest_path.is_file():
            digest.update(manifest_path.read_bytes())
        elif relative_path in _ENVIRONMENT_REQUIRED_MANIFESTS:
            raise FileNotFoundError(_ENVIRONMENT_INPUT_MISSING.format(path=relative_path))
    identity = (
        _ENVIRONMENT_GROUPS,
        str(Path(sys.executable).resolve()),
        sys.version,
        sys.implementation.cache_tag or _UNKNOWN_REVISION,
        platform.platform(),
    )
    digest.update(json.dumps(identity, separators=_JSON_SEPARATORS).encode(_UTF8))
    return digest.hexdigest()


def _cache_home() -> Path:
    """Return the user's cache directory: an absolute XDG_CACHE_HOME, else the default beneath the account home.

    The account home comes from the user database, not HOME, because the commit gate starts
    the controller without HOME and worktree tooling may redirect it.
    """
    configured = os.environ.get(_CACHE_VARIABLE, _EMPTY)
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / ".cache"


def _environment_cache_root() -> Path:
    """Return the per-user store directory, created private and refused when it is not ours."""
    cache_home = _cache_home()
    cache_home.mkdir(parents=True, exist_ok=True)
    store_root = cache_home / _STORE_DIRECTORY
    try:
        store_root.mkdir(mode=_STORE_MODE)
    except FileExistsError:
        pass
    # Open without following a link so ownership and permissions are read from, and set on, the directory itself.
    try:
        descriptor = os.open(store_root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as exc:
        raise RuntimeError(_STORE_REFUSED) from exc
    try:
        if os.fstat(descriptor).st_uid != os.getuid():
            raise RuntimeError(_STORE_REFUSED)
        os.fchmod(descriptor, _STORE_MODE)
    finally:
        os.close(descriptor)
    return store_root


class GenerationDefect(StrEnum):
    """Why a cached generation is not complete; the value is the reason the recovery record carries."""

    LINK = "link"
    MISSING = "missing"
    MANIFEST_MISSING = "manifest missing"
    INTERPRETER_MISSING = "interpreter missing"
    VENV_CONFIG_MISSING = "venv config missing"
    MANIFEST_UNREADABLE = "manifest unreadable"
    MANIFEST_MISMATCH = "manifest mismatch"


class EnvironmentLease:
    """A generation path held in use: its shared lock keeps every other run from retiring it until closed."""

    def __init__(self, path: Path, lock_file: IO[bytes]) -> None:
        self.path = path
        self._lock_file: IO[bytes] | None = lock_file

    def close(self) -> None:
        """Release the shared lock; closing twice is harmless."""
        lock_file, self._lock_file = self._lock_file, None
        if lock_file is not None:
            lock_file.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()


def ensure_dependency_environment(source_root: Path) -> EnvironmentLease:
    """Prepare or reuse a locked environment that contains dependencies but no app install.

    The caller holds the returned lease for as long as it uses the generation path.
    """
    resolved_root = source_root.expanduser().resolve()
    store_root = _environment_cache_root()
    generation = _environment_cache_key(resolved_root)
    environment_path = store_root / generation
    lock_file = (store_root / f"{generation}{_ENVIRONMENT_LOCK_SUFFIX}").open("a+b")
    try:
        # Runs reusing one generation share its lock and never wait on each other.
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        if _generation_defect(environment_path, generation) is None:
            _stamp_last_use(environment_path)
            _bound_store(store_root, generation, built=False)
            return EnvironmentLease(environment_path, lock_file)
        # Conversion is not atomic: another run may finish or retire the generation in the gap, so the
        # exclusive holder looks again before it builds.
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        defect = _generation_defect(environment_path, generation)
        built = defect is not None
        if defect is not None:
            _rebuild_generation(store_root, resolved_root, generation, defect)
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_SH)
        _bound_store(store_root, generation, built=built)
        return EnvironmentLease(environment_path, lock_file)
    except BaseException:
        lock_file.close()
        raise


def _rebuild_generation(store_root: Path, source_root: Path, generation: str, defect: GenerationDefect) -> None:
    """Build one generation under its exclusive lock, retiring whatever incomplete entry holds its path."""
    started = time.monotonic()
    environment_path = store_root / generation
    if os.path.lexists(environment_path):
        # A link, a thinned directory or a mismatched manifest is purge or kill damage, not state worth keeping.
        _retire_entry(store_root, environment_path)
        logger.warning("generation_recovered", generation=generation, reason=defect.value)
    # A sync holds the download-cache lock shared, so clearing the cache never runs under it.
    with (store_root / _CACHE_LOCK_FILENAME).open("a+b") as cache_lock:
        fcntl.flock(cache_lock.fileno(), fcntl.LOCK_SH)
        environment = _dependency_sync_environment(store_root, environment_path)
        sync_result = run_bounded_process(
            (
                *_UV_SYNC_ARGUMENTS,
                str(source_root),
                _UV_LOCKED_OPTION,
                _UV_NO_INSTALL_PROJECT_OPTION,
                _UV_NO_DEFAULT_GROUPS_OPTION,
            ),
            cwd=source_root,
            environment=environment,
            timeout_seconds=_UV_SYNC_TIMEOUT_SECONDS,
        )
    if sync_result.exit_status != 0 or sync_result.diagnostics:
        failure = RuntimeError(
            _ENVIRONMENT_SYNC_FAILED.format(detail=_sync_failure_detail(sync_result, store_root, source_root))
        )
        try:
            if os.path.lexists(environment_path):
                _retire_entry(store_root, environment_path)
        except OSError as retire_error:
            raise failure from retire_error
        raise failure
    manifest_path = environment_path / _ENVIRONMENT_MANIFEST_FILENAME
    manifest_path.write_text(
        json.dumps({_MANIFEST_KEY_FIELD: generation, _MANIFEST_GROUPS_FIELD: _ENVIRONMENT_GROUPS}),
        encoding=_UTF8,
    )
    if _generation_defect(environment_path, generation) is not None:
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name))
    _stamp_last_use(environment_path)
    logger.debug("generation_built", generation=generation, duration_seconds=round(time.monotonic() - started, 3))


def _sync_failure_detail(sync_result: ProcessExecution, store_root: Path, source_root: Path) -> str:
    """Describe a failed sync with uv's exit status and a bounded, path-free tail of its output."""
    parts = [_PROCESS_FAILURE_DETAIL.format(exit_status=sync_result.exit_status)]
    if sync_result.diagnostics:
        parts.append(sync_result.diagnostics)
    output = sync_result.stderr.strip() or sync_result.stdout.strip()
    if output:
        parts.append(
            "uv output (end): " + _sanitize_evidence(output[-_SYNC_EVIDENCE_TAIL_LIMIT:], store_root, source_root)
        )
    return " ".join(parts)


def _sanitize_evidence(text: str, store_root: Path, source_root: Path) -> str:
    """Replace the source tree, the store and the account home, longest first, with their placeholders."""
    text = text.replace(str(source_root), SOURCE_TREE_PLACEHOLDER)
    text = text.replace(str(store_root), DEPENDENCY_ENVIRONMENT_PLACEHOLDER)
    return text.replace(pwd.getpwuid(os.getuid()).pw_dir, "<account-home>")


def _rename_aside(store_root: Path, entry: Path) -> Path:
    """Rename a store entry to a unique retired name inside the store; the rename frees its path atomically.

    The rename follows no link: a symlink is renamed as a link and its target is untouched.
    """
    retired = store_root / f"{entry.name}{_RETIRED_MARKER}{uuid.uuid4().hex}"
    os.rename(entry, retired)
    return retired


def _retire_entry(store_root: Path, entry: Path) -> None:
    """Rename a store entry aside, then remove what was renamed.

    A failed removal leaves the renamed entry for a later retention pass and does not fail the caller.
    """
    _remove_retired_entry(_rename_aside(store_root, entry))


def _remove_retired_entry(retired: Path) -> None:
    """Delete one renamed-aside entry; a link is unlinked, a directory is removed without following links."""
    try:
        if retired.is_symlink():
            os.unlink(retired)
        else:
            shutil.rmtree(retired)
    except OSError as error:
        logger.warning("store_entry_removal_failed", entry=retired.name, error_class=type(error).__name__)


def _stamp_last_use(environment_path: Path) -> None:
    """Record that a run used this generation now; retention reads the stamp."""
    os.utime(environment_path / _ENVIRONMENT_MANIFEST_FILENAME)


def _dependency_sync_environment(cache_root: Path, environment_path: Path) -> dict[str, str]:
    """Build an allowlisted environment for uv without inheriting credentials or project config."""
    runtime_home = cache_root / _SYNTHETIC_HOME_DIRECTORY
    runtime_cache = cache_root / _SYNTHETIC_CACHE_DIRECTORY
    runtime_temp = cache_root / _SYNTHETIC_TEMP_DIRECTORY
    runtime_home.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime_cache.mkdir(mode=0o700, parents=True, exist_ok=True)
    runtime_temp.mkdir(mode=0o700, parents=True, exist_ok=True)
    child_environment = {
        _PATH_VARIABLE: os.environ.get(_PATH_VARIABLE, _EMPTY),
        _HOME_VARIABLE: str(runtime_home),
        _UV_CACHE_VARIABLE: str(runtime_cache),
        PROJECT_ENVIRONMENT_VARIABLE: str(environment_path),
        _LOCALE_VARIABLE: os.environ.get(_LOCALE_VARIABLE, _DEFAULT_LANGUAGE),
        _TMP_VARIABLE: str(runtime_temp),
    }
    return child_environment


def _generation_defect(environment_path: Path, generation: str) -> GenerationDefect | None:
    """Name what is missing or wrong with a cached generation, or None when its markers are complete.

    This is a predicate the caller acts on: it never mutates the generation, and the caller decides
    whether an incomplete one is rebuilt.
    """
    manifest_path = environment_path / _ENVIRONMENT_MANIFEST_FILENAME
    python_path = environment_path / PYTHON_ENVIRONMENT_EXECUTABLE
    config_path = environment_path / _VENV_CONFIG_FILENAME
    if environment_path.is_symlink():
        return GenerationDefect.LINK
    if not environment_path.is_dir():
        return GenerationDefect.MISSING
    if not manifest_path.is_file():
        return GenerationDefect.MANIFEST_MISSING
    if not python_path.is_file():
        return GenerationDefect.INTERPRETER_MISSING
    if not config_path.is_file():
        return GenerationDefect.VENV_CONFIG_MISSING
    try:
        manifest: object = json.loads(manifest_path.read_text(encoding=_UTF8))
    except (OSError, json.JSONDecodeError):
        return GenerationDefect.MANIFEST_UNREADABLE
    if manifest != {_MANIFEST_KEY_FIELD: generation, _MANIFEST_GROUPS_FIELD: _ENVIRONMENT_GROUPS}:
        return GenerationDefect.MANIFEST_MISMATCH
    return None


def _bound_store(store_root: Path, current_generation: str, *, built: bool) -> None:
    """Keep the store to the generations in recent use and a download cache under its ceiling.

    Housekeeping never fails the run: an entry it cannot remove stays for the next pass, and it
    only ever tries other generations' locks without waiting.
    """
    try:
        names = [entry.name for entry in os.scandir(store_root)]
    except OSError as error:
        logger.warning("store_sweep_failed", error_class=type(error).__name__)
        return
    for name in names:
        if _RETIRED_NAME.fullmatch(name):
            _remove_retired_entry(store_root / name)
        elif _GENERATION_NAME.fullmatch(name) and name != current_generation:
            _retire_unused_generation(store_root, name)
    if built:
        _clear_oversized_download_cache(store_root)


def _last_use(entry: Path) -> float:
    """Return when a generation was last used: its manifest stamp, else the entry's own modification time."""
    try:
        return os.stat(entry / _ENVIRONMENT_MANIFEST_FILENAME).st_mtime
    except OSError:
        return os.lstat(entry).st_mtime


def _try_lock_exclusive(lock_path: Path) -> IO[bytes] | None:
    """Take a lock exclusively without waiting; None when another run holds it in any mode."""
    lock_file = lock_path.open("a+b")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_file.close()
        return None
    except BaseException:
        lock_file.close()
        raise
    return lock_file


def _is_stale(entry: Path) -> bool:
    return time.time() - _last_use(entry) > _GENERATION_RETENTION_SECONDS


def _retire_unused_generation(store_root: Path, name: str) -> None:
    """Retire one generation no run has used within the retention window and no run holds now."""
    entry = store_root / name
    try:
        if not _is_stale(entry):
            return
        lock_file = _try_lock_exclusive(store_root / f"{name}{_ENVIRONMENT_LOCK_SUFFIX}")
        if lock_file is None:
            return
        with lock_file:
            # A run that took the lock between the first look and now has refreshed the stamp.
            if _is_stale(entry):
                _retire_entry(store_root, entry)
                logger.debug("generation_retired", generation=name)
    except OSError as error:
        logger.warning("store_entry_retention_failed", entry=name, error_class=type(error).__name__)


def _tree_size_bytes(root: Path) -> int:
    """Sum the apparent size of every file under a directory, following no link."""
    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
                    else:
                        total += entry.stat(follow_symlinks=False).st_size
        except FileNotFoundError:
            continue
    return total


def _clear_oversized_download_cache(store_root: Path) -> None:
    """Clear the download cache when a build left it above the ceiling and no sync is using it."""
    cache_path = store_root / _SYNTHETIC_CACHE_DIRECTORY
    try:
        if not cache_path.is_dir():
            return
        size_bytes = _tree_size_bytes(cache_path)
        if size_bytes <= _DOWNLOAD_CACHE_CEILING_BYTES:
            return
        lock_file = _try_lock_exclusive(store_root / _CACHE_LOCK_FILENAME)
        if lock_file is None:
            logger.debug("download_cache_clear_skipped", size_bytes=size_bytes, reason="in_use")
            return
        with lock_file:
            # Held only for the rename: a sync never sees a partly deleted cache.
            retired = _rename_aside(store_root, cache_path)
        _remove_retired_entry(retired)
        logger.debug("download_cache_cleared", size_bytes=size_bytes)
    except OSError as error:
        logger.warning(
            "store_entry_clearing_failed", entry=_SYNTHETIC_CACHE_DIRECTORY, error_class=type(error).__name__
        )
