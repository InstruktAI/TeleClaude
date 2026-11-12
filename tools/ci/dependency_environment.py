"""Prepare and reuse the locked dependency-only environment the acceptance harness runs against."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import platform
import pwd
import shutil
import sys
from pathlib import Path

from tools.ci.bounded_process import run_bounded_process

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
_ENVIRONMENT_INVALID = "The dependency-only environment generation is incomplete: {path}"
_ENVIRONMENT_SYNC_FAILED = "Could not prepare the locked dependency-only environment: {detail}"
_ENVIRONMENT_INPUT_MISSING = "The dependency environment input is missing: {path}"
_STORE_REFUSED = "The dependency environment store is a link, is not a directory, or belongs to another user."
_CACHE_VARIABLE = "XDG_CACHE_HOME"
_DEFAULT_CACHE_DIRECTORY = ".cache"
_STORE_MODE = 0o700
_PROCESS_FAILURE_DETAIL = "The command failed with exit status {exit_status}."
PROJECT_ENVIRONMENT_VARIABLE = "UV_PROJECT_ENVIRONMENT"
PYTHON_ENVIRONMENT_EXECUTABLE = Path("bin") / _PYTHON_EXECUTABLE


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
    """Return the user's cache directory: an absolute XDG_CACHE_HOME, else the account home's .cache.

    The account home comes from the user database, not HOME, because the commit gate starts
    the controller without HOME and worktree tooling may redirect it.
    """
    configured = os.environ.get(_CACHE_VARIABLE, _EMPTY)
    if configured and Path(configured).is_absolute():
        return Path(configured)
    return Path(pwd.getpwuid(os.getuid()).pw_dir) / _DEFAULT_CACHE_DIRECTORY


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


def ensure_dependency_environment(source_root: Path) -> Path:
    """Prepare or reuse a locked environment that contains dependencies but no app install."""
    resolved_root = source_root.expanduser().resolve()
    cache_root = _environment_cache_root()
    generation = _environment_cache_key(resolved_root)
    environment_path = cache_root / generation
    lock_path = cache_root / f"{generation}{_ENVIRONMENT_LOCK_SUFFIX}"
    with lock_path.open("a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if environment_path.exists():
            _validate_dependency_environment(environment_path, generation)
            return environment_path
        environment = _dependency_sync_environment(cache_root, environment_path)
        sync_result = run_bounded_process(
            (
                *_UV_SYNC_ARGUMENTS,
                str(resolved_root),
                _UV_LOCKED_OPTION,
                _UV_NO_INSTALL_PROJECT_OPTION,
                _UV_NO_DEFAULT_GROUPS_OPTION,
            ),
            cwd=resolved_root,
            environment=environment,
            timeout_seconds=_UV_SYNC_TIMEOUT_SECONDS,
        )
        if sync_result.exit_status != 0 or sync_result.diagnostics:
            if environment_path.exists() and not environment_path.is_symlink():
                shutil.rmtree(environment_path)
            detail = _PROCESS_FAILURE_DETAIL.format(exit_status=sync_result.exit_status)
            raise RuntimeError(_ENVIRONMENT_SYNC_FAILED.format(detail=detail))
        manifest_path = environment_path / _ENVIRONMENT_MANIFEST_FILENAME
        manifest_path.write_text(json.dumps({"key": generation, "groups": _ENVIRONMENT_GROUPS}), encoding=_UTF8)
        _validate_dependency_environment(environment_path, generation)
        return environment_path


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


def _validate_dependency_environment(environment_path: Path, generation: str) -> None:
    """Refuse an incomplete or mismatched cached environment without mutating it."""
    manifest_path = environment_path / _ENVIRONMENT_MANIFEST_FILENAME
    python_path = environment_path / PYTHON_ENVIRONMENT_EXECUTABLE
    config_path = environment_path / _VENV_CONFIG_FILENAME
    if (
        environment_path.is_symlink()
        or not environment_path.is_dir()
        or not manifest_path.is_file()
        or not python_path.is_file()
        or not config_path.is_file()
    ):
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name))
    try:
        manifest: object = json.loads(manifest_path.read_text(encoding=_UTF8))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name)) from exc
    if manifest != {_MANIFEST_KEY_FIELD: generation, _MANIFEST_GROUPS_FIELD: _ENVIRONMENT_GROUPS}:
        raise RuntimeError(_ENVIRONMENT_INVALID.format(path=environment_path.name))
